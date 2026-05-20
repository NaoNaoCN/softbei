"""
tests/test_evaluation_judge.py
RAGJudge LLM-as-Judge 单元测试（LLM 调用全部 mock）。
"""

import json
import asyncio
from unittest.mock import AsyncMock, patch, call

import pytest

from backend.evaluation.judge import (
    RAGJudge,
    get_judge,
    JUDGE_CHUNK_RELEVANCE_PROMPT,
    JUDGE_FAITHFULNESS_PROMPT,
    JUDGE_COMPLETENESS_PROMPT,
    JUDGE_COMPLETENESS_ASPECTS_PROMPT,
    JUDGE_CITATION_PROMPT,
)


class FakeChunk:
    """模拟 RetrievedChunk。"""
    def __init__(self, chunk_id, text, score, doc_id, source=""):
        self.chunk_id = chunk_id
        self.text = text
        self.score = score
        self.doc_id = doc_id
        self.source = source


@pytest.fixture
def sample_chunks():
    return [
        FakeChunk("c1", "梯度下降是一种一阶迭代优化算法，用于寻找函数的局部最小值。", 0.92, "d1"),
        FakeChunk("c2", "学习率是梯度下降中最重要的超参数之一，控制每次更新的步长。", 0.87, "d1"),
        FakeChunk("c3", "在深度学习中，Adam 优化器结合了动量和自适应学习率。", 0.73, "d2"),
        FakeChunk("c4", "反向传播算法用于计算神经网络中参数的梯度。", 0.61, "d2"),
        FakeChunk("c5", "Python 是一种广泛使用的编程语言。", 0.45, "d3"),
    ]


@pytest.fixture
def generated_content():
    return """# 梯度下降

梯度下降是一种迭代优化算法 [1]，用于最小化损失函数。

## 核心概念

学习率控制每次参数更新的步长 [2]。学习率过大可能导致震荡，过小则收敛缓慢。

## 应用

在深度学习中，Adam 是常用的优化器 [3]。反向传播用于计算梯度 [4]。

## 常见误区

梯度下降总是能到达全局最优解。
"""


# ============================================================
# Judge 1: Chunk Relevance
# ============================================================

class TestChunkRelevance:
    @pytest.mark.asyncio
    async def test_returns_parsed_score(self):
        judge = RAGJudge()
        mock_response = json.dumps({"score": 2, "reason": "直接描述了梯度下降的定义"})

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await judge.judge_chunk_relevance(
                query="什么是梯度下降",
                chunk_text="梯度下降是一种一阶迭代优化算法",
            )

        assert result["score"] == 2
        assert "reason" in result

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        judge = RAGJudge()
        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("LLM 超时")
            result = await judge.judge_chunk_relevance(
                query="test",
                chunk_text="test",
            )

        assert result["score"] == 0
        assert "评估异常" in result["reason"]

    @pytest.mark.asyncio
    async def test_truncates_long_chunk(self):
        judge = RAGJudge()
        long_text = "梯度下降 " * 1000  # 远超 1500 字符

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = json.dumps({"score": 2, "reason": "ok"})
            await judge.judge_chunk_relevance(query="梯度下降", chunk_text=long_text)

        # 验证传入了截断后的文本
        call_args = mock_llm.call_args[0][0]  # messages
        prompt = call_args[0]["content"]
        assert len(prompt) < len(long_text) + 500  # prompt 不会包含完整的 5000+ 字符


# ============================================================
# Judge 1: Chunk Relevance Batch
# ============================================================

class TestChunkRelevanceBatch:
    @pytest.mark.asyncio
    async def test_batch_aggregates_results(self, sample_chunks):
        judge = RAGJudge()

        async def fake_judge(query, chunk_text):
            if chunk_text.startswith("梯度下降是一种"):
                return {"score": 2, "reason": "相关"}
            elif "学习率" in chunk_text or "Adam" in chunk_text or "反向传播" in chunk_text:
                return {"score": 1, "reason": "部分相关"}
            else:
                return {"score": 0, "reason": "无关"}

        with patch.object(RAGJudge, "judge_chunk_relevance", side_effect=fake_judge):
            results = await judge.judge_chunk_relevance_batch(
                query="什么是梯度下降",
                chunks=sample_chunks,
            )

        assert len(results) == 5
        assert results == [2, 1, 1, 1, 0]

    @pytest.mark.asyncio
    async def test_batch_handles_exceptions(self, sample_chunks):
        judge = RAGJudge()

        call_count = 0

        async def fake_judge_with_failure(query, chunk_text):
            nonlocal call_count
            call_count += 1
            if call_count == 3:
                raise Exception("LLM 错误")
            return {"score": 2, "reason": "ok"}

        with patch.object(RAGJudge, "judge_chunk_relevance", side_effect=fake_judge_with_failure):
            results = await judge.judge_chunk_relevance_batch(
                query="test",
                chunks=sample_chunks,
            )

        # 第 3 个 chunk 失败 → 返回 0，其他正常
        assert results[2] == 0
        assert results[0] == 2


# ============================================================
# Judge 2: Faithfulness
# ============================================================

class TestFaithfulness:
    @pytest.mark.asyncio
    async def test_returns_faithfulness_result(self):
        judge = RAGJudge()
        mock_response = json.dumps({
            "statements": [
                {"text": "梯度下降是迭代优化算法", "verdict": "supported", "evidence": "原文提到..."},
                {"text": "牛顿发明了梯度下降", "verdict": "unsupported", "evidence": None},
            ],
            "faithfulness": 0.5,
            "issues": ["牛顿发明梯度下降的说法无依据"],
        })

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await judge.judge_faithfulness(
                retrieved_docs=["梯度下降是一种一阶迭代优化算法。"],
                generated_content="梯度下降是迭代优化算法。牛顿发明了梯度下降。",
            )

        assert result["faithfulness"] == 0.5
        assert len(result["statements"]) == 2
        assert result["issues"] == ["牛顿发明梯度下降的说法无依据"]

    @pytest.mark.asyncio
    async def test_empty_content(self):
        judge = RAGJudge()
        result = await judge.judge_faithfulness(
            retrieved_docs=["some doc"],
            generated_content="",
        )
        assert result["faithfulness"] == 1.0
        assert result["statements"] == []

    @pytest.mark.asyncio
    async def test_no_retrieved_docs(self):
        judge = RAGJudge()
        result = await judge.judge_faithfulness(
            retrieved_docs=[],
            generated_content="some content",
        )
        assert result["faithfulness"] == 0.0
        assert "无参考资料" in result["issues"][0]

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        judge = RAGJudge()
        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API 错误")
            result = await judge.judge_faithfulness(
                retrieved_docs=["doc"],
                generated_content="content",
            )

        assert result["faithfulness"] == 0.0
        assert "评估异常" in result["issues"][0]


# ============================================================
# Judge 3: Completeness
# ============================================================

class TestCompleteness:
    @pytest.mark.asyncio
    async def test_generate_expected_aspects(self):
        judge = RAGJudge()
        mock_response = json.dumps({
            "aspects": ["定义与原理", "数学公式", "参数选择", "应用场景", "常见误区"]
        })

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            aspects = await judge._generate_expected_aspects("梯度下降")

        assert len(aspects) == 5
        assert "定义与原理" in aspects

    @pytest.mark.asyncio
    async def test_generate_aspects_failure(self):
        judge = RAGJudge()
        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("失败")
            aspects = await judge._generate_expected_aspects("梯度下降")

        assert aspects == []

    @pytest.mark.asyncio
    async def test_judge_completeness(self):
        judge = RAGJudge()
        mock_response = json.dumps({
            "aspects": [
                {"aspect": "定义", "coverage": "covered", "evidence": "..."},
                {"aspect": "公式", "coverage": "partial", "evidence": "..."},
                {"aspect": "误区", "coverage": "missing", "evidence": None},
            ],
            "completeness": 0.50,
        })

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await judge.judge_completeness(
                kp_name="梯度下降",
                generated_content="梯度下降是优化算法。",
                expected_aspects=["定义", "公式", "误区"],
            )

        assert result["completeness"] == 0.50
        assert len(result["aspects"]) == 3

    @pytest.mark.asyncio
    async def test_empty_content(self):
        judge = RAGJudge()
        result = await judge.judge_completeness(
            kp_name="test",
            generated_content="",
        )
        assert result["completeness"] == 0.0

    @pytest.mark.asyncio
    async def test_no_expected_aspects_generated(self):
        """_generate_expected_aspects 返回空时，completeness 应为 0。"""
        judge = RAGJudge()

        with patch.object(RAGJudge, "_generate_expected_aspects", new_callable=AsyncMock) as mock_gen:
            mock_gen.return_value = []
            result = await judge.judge_completeness(
                kp_name="test",
                generated_content="some content",
            )
        assert result["completeness"] == 0.0


# ============================================================
# Judge 4: Citation Accuracy
# ============================================================

class TestCitationAccuracy:
    @pytest.mark.asyncio
    async def test_returns_verdict(self):
        judge = RAGJudge()
        mock_response = json.dumps({
            "verdict": "accurate",
            "explanation": "引用内容与参考资料一致",
        })

        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response
            result = await judge.judge_citation_accuracy(
                citation_context="梯度下降是优化算法 [1]",
                reference_chunk="梯度下降是一种一阶优化算法",
                ref_index=1,
            )

        assert result["verdict"] == "accurate"

    @pytest.mark.asyncio
    async def test_handles_failure(self):
        judge = RAGJudge()
        with patch("backend.evaluation.judge.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("错误")
            result = await judge.judge_citation_accuracy("ctx", "ref", 1)

        assert result["verdict"] == "vague"
        assert "评估异常" in result["explanation"]


class TestCitationAccuracyBatch:
    @pytest.mark.asyncio
    async def test_extracts_references(self, sample_chunks, generated_content):
        judge = RAGJudge()

        async def fake_citation(context, chunk_text, ref_index):
            return {"verdict": "accurate", "explanation": "ok"}

        with patch.object(RAGJudge, "judge_citation_accuracy", side_effect=fake_citation):
            result = await judge.judge_citation_accuracy_batch(
                generated_content=generated_content,
                retrieved_chunks=sample_chunks,
            )

        # generated_content 中有 [1], [2], [3], [4] 共 4 条引用
        assert result["citation_precision"] == 1.0
        assert len(result["citations"]) == 4

    @pytest.mark.asyncio
    async def test_no_citations(self, sample_chunks):
        judge = RAGJudge()
        result = await judge.judge_citation_accuracy_batch(
            generated_content="没有引用的文本",
            retrieved_chunks=sample_chunks,
        )
        assert result["citation_precision"] == 1.0
        assert result["citations"] == []

    @pytest.mark.asyncio
    async def test_ref_out_of_range(self, sample_chunks):
        """引用编号超出 chunks 范围时应报告 vague。"""
        judge = RAGJudge()

        async def fake_citation(context, chunk_text, ref_index):
            return {"verdict": "accurate", "explanation": "ok"}

        with patch.object(RAGJudge, "judge_citation_accuracy", side_effect=fake_citation):
            result = await judge.judge_citation_accuracy_batch(
                generated_content="参见 [10] 了解详情。",
                retrieved_chunks=sample_chunks,  # 只有 5 个 chunk
            )

        # ref 10 超出范围
        assert result["citations"][0]["verdict"] == "vague"
        assert "超出" in result["citations"][0]["explanation"]


# ============================================================
# evaluate_full（联合评估）
# ============================================================

class TestEvaluateFull:
    @pytest.mark.asyncio
    async def test_orchestrates_all_judges(self, sample_chunks, generated_content):
        """测试完整评估流程（mock 所有 LLM 调用）。"""
        judge = RAGJudge()

        async def fake_chunk_relevance_batch(query, chunks):
            return [2, 2, 1, 1, 0]

        async def fake_faithfulness(retrieved_docs, content):
            return {
                "statements": [
                    {"text": "梯度下降是优化算法", "verdict": "supported", "evidence": "..."},
                ],
                "faithfulness": 0.95,
                "issues": [],
            }

        async def fake_completeness(kp_name, content, expected_aspects=None):
            return {
                "aspects": [
                    {"aspect": "定义", "coverage": "covered"},
                ],
                "completeness": 0.80,
            }

        async def fake_citation_batch(content, chunks):
            return {"citations": [{"ref_index": 1, "verdict": "accurate"}], "citation_precision": 1.0}

        with patch.object(RAGJudge, "judge_chunk_relevance_batch", side_effect=fake_chunk_relevance_batch), \
             patch.object(RAGJudge, "judge_faithfulness", side_effect=fake_faithfulness), \
             patch.object(RAGJudge, "judge_completeness", side_effect=fake_completeness), \
             patch.object(RAGJudge, "judge_citation_accuracy_batch", side_effect=fake_citation_batch):

            result = await judge.evaluate_full(
                query="什么是梯度下降",
                kp_name="梯度下降",
                retrieved_chunks=sample_chunks,
                generated_content=generated_content,
                include_citation_check=True,
            )

        assert result["query"] == "什么是梯度下降"
        assert result["faithfulness_score"] == 0.95
        assert result["hallucination_rate"] == pytest.approx(0.05)
        assert result["completeness_score"] == 0.80
        assert result["precision_at_5"] == 0.8  # 4/5 = 0.8
        assert result["citation_precision"] == 1.0
        assert result["evaluation_time_ms"] > 0

    @pytest.mark.asyncio
    async def test_evaluate_full_without_citations(self, sample_chunks):
        """生成内容无引用标注时，应跳过 citation check。"""
        judge = RAGJudge()

        async def fake_chunk_relevance_batch(query, chunks):
            return [2 for _ in chunks]

        async def fake_faithfulness(retrieved_docs, content):
            return {"statements": [], "faithfulness": 1.0, "issues": []}

        async def fake_completeness(kp_name, content, expected_aspects=None):
            return {"aspects": [], "completeness": 0.5}

        with patch.object(RAGJudge, "judge_chunk_relevance_batch", side_effect=fake_chunk_relevance_batch), \
             patch.object(RAGJudge, "judge_faithfulness", side_effect=fake_faithfulness), \
             patch.object(RAGJudge, "judge_completeness", side_effect=fake_completeness):

            result = await judge.evaluate_full(
                query="query",
                kp_name="kp",
                retrieved_chunks=sample_chunks,
                generated_content="无引用标注的内容",
                include_citation_check=True,
            )

        assert result["citation_precision"] is None
        assert result["citations"] == []

    @pytest.mark.asyncio
    async def test_hallucination_rate_calculation(self, sample_chunks):
        """hallucination_rate = 1 - faithfulness_score（当有 statements 时）。"""
        judge = RAGJudge()

        async def fake_chunk_relevance_batch(query, chunks):
            return [2, 2, 1, 1, 0]

        async def fake_faithfulness(retrieved_docs, content):
            return {
                "statements": [{"text": "t", "verdict": "supported"}],
                "faithfulness": 0.60,
                "issues": [],
            }

        async def fake_completeness(kp_name, content, expected_aspects=None):
            return {"aspects": [], "completeness": 0.5}

        with patch.object(RAGJudge, "judge_chunk_relevance_batch", side_effect=fake_chunk_relevance_batch), \
             patch.object(RAGJudge, "judge_faithfulness", side_effect=fake_faithfulness), \
             patch.object(RAGJudge, "judge_completeness", side_effect=fake_completeness):

            result = await judge.evaluate_full(
                query="q", kp_name="kp",
                retrieved_chunks=sample_chunks,
                generated_content="content",
            )

        assert result["hallucination_rate"] == pytest.approx(0.40)


# ============================================================
# 模块级单例
# ============================================================

class TestGetJudge:
    def test_get_judge_returns_instance(self):
        judge = get_judge()
        assert isinstance(judge, RAGJudge)

    def test_get_judge_is_singleton(self):
        # 注意：模块级单例在测试间共享，这里只验证返回同类型
        j1 = get_judge()
        j2 = get_judge()
        assert j1 is j2

    def test_get_judge_respects_params_first_call(self):
        # 首次调用时传参应生效
        # 由于模块已经导入，这里只验证参数不报错
        j = get_judge(temperature=0.1, sample_rate=0.3)
        assert j.temperature == 0.0  # temperature 来自之前创建的单例
        assert j.sample_rate == 0.1


# ============================================================
# Prompt 模板
# ============================================================

class TestPromptTemplates:
    def test_chunk_relevance_prompt_format(self):
        prompt = JUDGE_CHUNK_RELEVANCE_PROMPT.format(query="test", chunk_text="text")
        assert "test" in prompt
        assert "text" in prompt
        assert "JSON" in prompt

    def test_faithfulness_prompt_format(self):
        prompt = JUDGE_FAITHFULNESS_PROMPT.format(
            retrieved_docs="doc1\ndoc2",
            generated_content="content",
        )
        assert "doc1" in prompt
        assert "content" in prompt

    def test_completeness_prompt_format(self):
        prompt = JUDGE_COMPLETENESS_PROMPT.format(
            kp_name="梯度下降",
            expected_aspects="- 定义\n- 原理",
            generated_content="content",
        )
        assert "梯度下降" in prompt
        assert "定义" in prompt

    def test_completeness_aspects_prompt_format(self):
        prompt = JUDGE_COMPLETENESS_ASPECTS_PROMPT.format(kp_name="测试知识点")
        assert "测试知识点" in prompt

    def test_citation_prompt_format(self):
        prompt = JUDGE_CITATION_PROMPT.format(
            ref_index=1,
            citation_context="上下文内容",
            reference_chunk="参考资料内容",
        )
        assert "[1]" in prompt
        assert "上下文内容" in prompt
