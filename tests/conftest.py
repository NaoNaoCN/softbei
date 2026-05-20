"""
tests/conftest.py
共享夹具和 mock 工具。
"""

from __future__ import annotations

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch


# ============================================================
# 样本数据夹具
# ============================================================

@pytest.fixture
def sample_scores():
    """模拟检索分数（3 条高度相关 + 1 条部分相关 + 1 条无关）。"""
    return [0.95, 0.88, 0.82, 0.55, 0.21]


@pytest.fixture
def sample_relevance_labels():
    """模拟 Judge 1 相关度标签。"""
    return [2, 2, 1, 0, 2]  # 4/5 相关


@pytest.fixture
def sample_relevance_labels_all():
    """多条查询的标签列表。"""
    return [
        [2, 2, 1, 0, 2],
        [1, 0, 0, 2, 0],
        [2, 2, 2, 1, 0],
    ]


@pytest.fixture
def sample_statements():
    """模拟 Judge 2 Faithfulness 逐句分析结果。"""
    return [
        {"text": "梯度下降是一种迭代优化算法", "verdict": "supported", "evidence": "梯度下降是..."},
        {"text": "学习率通常设为0.01", "verdict": "supported", "evidence": "学习率..."},
        {"text": "梯度下降由牛顿在1687年发明", "verdict": "unsupported", "evidence": None},
        {"text": "Adam是最常用的优化器", "verdict": "supported", "evidence": "Adam优化器..."},
    ]


@pytest.fixture
def sample_faithfulness_result(sample_statements):
    """模拟完整 Faithfulness 结果。"""
    return {
        "statements": sample_statements,
        "faithfulness": 0.75,
        "issues": ["关于牛顿的陈述在参考资料中无依据"],
    }


@pytest.fixture
def sample_completeness_result():
    """模拟 Judge 3 Completeness 结果。"""
    return {
        "aspects": [
            {"aspect": "定义", "coverage": "covered", "evidence": "梯度下降是一种..."},
            {"aspect": "数学原理", "coverage": "covered", "evidence": "更新公式为..."},
            {"aspect": "学习率选择", "coverage": "partial", "evidence": "学习率..."},
            {"aspect": "应用场景", "coverage": "covered", "evidence": "在深度学习中..."},
            {"aspect": "常见误区", "coverage": "missing", "evidence": None},
        ],
        "completeness": 0.70,
    }


@pytest.fixture
def sample_retrieval_record(sample_scores):
    """构建一个完整的 RetrievalEvalRecord。"""
    from backend.evaluation.models import RetrievalEvalRecord

    return RetrievalEvalRecord(
        query="什么是梯度下降",
        kp_name="梯度下降",
        user_id="1001",
        session_id="5001",
        embedding_latency_ms=120.0,
        db_query_latency_ms=45.0,
        n_candidates=10,
        n_results=5,
        scores=sample_scores,
        chunk_ids=["doc_a_0", "doc_a_1", "doc_b_0", "doc_b_1", "doc_c_0"],
        doc_ids=["doc_a", "doc_a", "doc_b", "doc_b", "doc_c"],
        chunk_texts=[
            "梯度下降是一种一阶迭代优化算法...",
            "梯度下降的变体包括SGD、Adam...",
            "学习率是梯度下降的关键超参数...",
            "在深度学习中，梯度下降用于...",
            "牛顿法与梯度下降的区别在于...",
        ],
    )


@pytest.fixture
def sample_generation_record(sample_retrieval_record, sample_faithfulness_result, sample_completeness_result, sample_relevance_labels):
    """构建一个完整的 GenerationEvalRecord（含 Judge 评估结果）。"""
    from backend.evaluation.models import GenerationEvalRecord

    return GenerationEvalRecord(
        session_id="5001",
        user_id="1001",
        agent_type="doc_agent",
        kp_name="梯度下降",
        query="什么是梯度下降",
        draft_length=2500,
        generation_latency_ms=3200.0,
        has_rag_context=True,
        n_retrieved=5,
        safety_passed=True,
        safety_issues_count=0,
        retrieval_record=sample_retrieval_record,
        faithfulness_score=0.85,
        hallucination_rate=0.15,
        concept_coverage=0.70,
        completeness_score=0.70,
        relevance_labels=sample_relevance_labels,
        faithfulness_statements=sample_faithfulness_result["statements"],
        completeness_aspects=sample_completeness_result["aspects"],
    )


@pytest.fixture
def sample_generation_records(sample_generation_record):
    """3 条 GenerationEvalRecord 列表。"""
    r1 = sample_generation_record
    r2 = r1.model_copy(deep=True)
    r2.timestamp = datetime.utcnow() - timedelta(hours=12)
    r2.faithfulness_score = 0.70
    r2.hallucination_rate_val = 0.30
    r3 = r1.model_copy(deep=True)
    r3.timestamp = datetime.utcnow() - timedelta(hours=6)
    r3.faithfulness_score = 0.92
    r3.hallucination_rate_val = 0.08
    return [r1, r2, r3]


# ============================================================
# Mock LLM 夹具
# ============================================================

class MockLLMResponse:
    """可配置的 mock LLM 响应，模拟 chat_completion 返回值。"""

    def __init__(self, responses: list[str] | None = None, default: str = ""):
        """
        :param responses: 按调用顺序返回的响应列表
        :param default:   当 responses 耗尽时的兜底响应
        """
        self.responses = responses or []
        self.default = default
        self._call_count = 0
        self.calls: list[dict] = []  # 记录每次调用的参数

    def respond(self):
        """返回下一份响应。"""
        idx = self._call_count
        self._call_count += 1
        if idx < len(self.responses):
            return self.responses[idx]
        return self.default

    def __call__(self, *args, **kwargs):
        """使实例本身可当作函数调用。"""
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.respond()


@pytest.fixture
def mock_chat_completion():
    """返回一个 AsyncMock，模拟 backend.services.llm.chat_completion。"""
    return AsyncMock()


@pytest.fixture
def patch_chat_completion(mock_chat_completion):
    """对 chat_completion 打补丁，测试结束后自动还原。"""
    with patch(
        "backend.services.llm.chat_completion",
        mock_chat_completion,
    ):
        yield mock_chat_completion
