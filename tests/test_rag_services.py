"""
tests/test_rag_services.py
backend/services/llm.py, backend/rag/indexer.py, backend/rag/retriever.py 单元测试。
所有外部依赖使用 mock。
"""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

from backend.rag.retriever import (
    RetrievedChunk,
    _parse_results,
    retrieve,
    retrieve_by_kp,
    format_context,
)


# ===========================================================
# retriever.py — _parse_results
# ===========================================================

class TestParseResults:
    """_parse_results 将 ChromaDB 原始结果转换为 RetrievedChunk 列表。"""

    def test_basic(self):
        """正常输入应正确解析并按 score 降序排列。"""
        raw = {
            "ids": [["c1", "c2"]],
            "documents": [["text1", "text2"]],
            "distances": [[0.1, 0.3]],
            "metadatas": [[
                {"doc_id": "d1", "source": "a.txt", "page": "1", "section": "S1"},
                {"doc_id": "d2", "source": "b.txt"},
            ]],
        }
        chunks = _parse_results(raw, score_threshold=0.5)
        assert len(chunks) == 2
        assert chunks[0].score >= chunks[1].score

    def test_threshold_filter(self):
        """低于 score_threshold 的结果应被过滤掉。"""        
        raw = {
            "ids": [["c1", "c2"]],
            "documents": [["t1", "t2"]],
            "distances": [[0.1, 0.8]],  # score = 0.9, 0.2
            "metadatas": [[{"doc_id": "d1", "source": "a"}, {"doc_id": "d2", "source": "b"}]],
        }
        chunks = _parse_results(raw, score_threshold=0.5)
        assert len(chunks) == 1
        assert chunks[0].chunk_id == "c1"

    def test_empty(self):
        """空结果集应返回空列表。"""
        raw = {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}
        assert _parse_results(raw, 0.5) == []

    def test_missing_fields(self):
        """原始字典缺少字段时应安全返回空列表。"""
        raw = {}
        assert _parse_results(raw, 0.5) == []

    def test_sorted_by_score_desc(self):
        """结果应按相似度得分降序排列。"""
        raw = {
            "ids": [["a", "b", "c"]],
            "documents": [["ta", "tb", "tc"]],
            "distances": [[0.4, 0.1, 0.3]],
            "metadatas": [[{"doc_id": "", "source": ""}] * 3],
        }
        chunks = _parse_results(raw, 0.0)
        scores = [c.score for c in chunks]
        assert scores == sorted(scores, reverse=True)

# ===========================================================
# retriever.py — retrieve / retrieve_by_kp
# ===========================================================

class TestRetrieve:
    """retrieve 语义检索完整调用链测试。"""

    @patch("backend.rag.retriever.query_documents")
    @patch("backend.rag.retriever.get_embedding", new_callable=AsyncMock)
    async def test_basic(self, mock_embed, mock_query):
        """应先调用 get_embedding 再调用 query_documents，返回解析后的 chunks。"""
        mock_embed.return_value = [0.1] * 768
        mock_query.return_value = {
            "ids": [["c1"]],
            "documents": [["hello"]],
            "distances": [[0.2]],
            "metadatas": [[{"doc_id": "d1", "source": "f.txt"}]],
        }
        chunks = await retrieve("test query", n_results=5)
        mock_embed.assert_awaited_once_with("test query")
        mock_query.assert_called_once()
        assert len(chunks) == 1

    @patch("backend.rag.retriever.query_documents")
    @patch("backend.rag.retriever.get_embedding", new_callable=AsyncMock)
    async def test_params_passed(self, mock_embed, mock_query):
        """n_results、where、collection_name 参数应正确传递给 query_documents。"""        
        mock_embed.return_value = [0.0]
        mock_query.return_value = {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}
        await retrieve("q", n_results=10, where={"doc_id": "x"}, collection_name="col")
        _, kwargs = mock_query.call_args
        assert kwargs["n_results"] == 10
        assert kwargs["where"] == {"doc_id": "x"}
        assert kwargs["collection_name"] == "col"


class TestRetrieveByKp:
    """retrieve_by_kp 按知识点名称检索测试。"""

    @patch("backend.rag.retriever.retrieve", new_callable=AsyncMock)
    async def test_prefix(self, mock_retrieve):
        """应在 query 中自动添加"知识点："前缀。"""
        mock_retrieve.return_value = []
        await retrieve_by_kp("梯度下降", n_results=8)
        args, kwargs = mock_retrieve.call_args
        assert "知识点：梯度下降" in args or kwargs.get("query") == "知识点：梯度下降"


# ===========================================================
# retriever.py — format_context
# ===========================================================

class TestFormatContext:
    """format_context 将检索结果格式化为 LLM prompt 上下文测试。"""

    def test_basic(self):
        """应生成带编号和来源信息的上下文字符串。"""
        chunks = [
            RetrievedChunk("c1", "text1", 0.9, "d1", "a.txt", page=1, section="S1"),
            RetrievedChunk("c2", "text2", 0.8, "d2", "b.txt"),
        ]
        ctx = format_context(chunks)
        assert "[1]" in ctx
        assert "[2]" in ctx
        assert "text1" in ctx
        assert "第 1 页" in ctx
        assert "S1" in ctx

    def test_empty(self):
        """空 chunks 列表应返回空字符串。"""
        assert format_context([]) == ""

    def test_truncation(self):
        """超过 max_tokens 估算时应截断，不包含所有 chunks。"""
        chunks = [
            RetrievedChunk(f"c{i}", "A" * 5000, 0.9, "d", "f.txt")
            for i in range(10)
        ]
        ctx = format_context(chunks, max_tokens=100)
        # 应该被截断，不会包含所有 10 个
        assert ctx.count("[") < 10

    def test_page_and_section_display(self):
        """page 和 section 信息应正确显示在来源引用中。"""        
        c = RetrievedChunk("c1", "t", 0.9, "d", "f.txt", page=3, section="第二章")
        ctx = format_context([c])
        assert "第 3 页" in ctx
        assert "第二章" in ctx


# ===========================================================
# indexer.py
# ===========================================================

from backend.rag.loader import TextChunk


class TestIndexChunks:
    """index_chunks 批量嵌入并写入向量库测试。"""

    @patch("backend.rag.indexer.upsert_documents")
    @patch("backend.rag.indexer.get_embedding", new_callable=AsyncMock)
    async def test_single_batch(self, mock_embed, mock_upsert):
        """chunk 数量小于 batch_size 时应只调用一次 upsert。"""
        mock_embed.return_value = [0.1] * 768
        chunks = [
            TextChunk("c1", "text1", "d1", "/a.txt", None, None),
            TextChunk("c2", "text2", "d1", "/a.txt", None, None),
        ]
        from backend.rag.indexer import index_chunks
        total = await index_chunks(chunks, batch_size=32)
        assert total == 2
        mock_upsert.assert_called_once()

    @patch("backend.rag.indexer.upsert_documents")
    @patch("backend.rag.indexer.get_embedding", new_callable=AsyncMock)
    async def test_multi_batch(self, mock_embed, mock_upsert):
        """chunk 数量超过 batch_size 时应分多批调用 upsert（5 个 chunk / batch=2 → 3 次）。"""        
        mock_embed.return_value = [0.1]
        chunks = [TextChunk(f"c{i}", f"t{i}", "d", "/f", None, None) for i in range(5)]
        from backend.rag.indexer import index_chunks
        total = await index_chunks(chunks, batch_size=2)
        assert total == 5
        assert mock_upsert.call_count == 3  # 2+2+1

    @patch("backend.rag.indexer.upsert_documents")
    @patch("backend.rag.indexer.get_embedding", new_callable=AsyncMock)
    async def test_empty(self, mock_embed, mock_upsert):
        """空 chunks 列表应返回 0 且不调用 upsert。"""        
        from backend.rag.indexer import index_chunks
        total = await index_chunks([])
        assert total == 0
        mock_upsert.assert_not_called()


class TestIndexFile:
    """index_file 一键加载并索引单个文件测试。"""

    @patch("backend.rag.indexer.index_chunks", new_callable=AsyncMock)
    @patch("backend.rag.loader.load_file")
    async def test_delegates(self, mock_load, mock_index):
        """应先调用 load_file 再调用 index_chunks。"""
        mock_load.return_value = [TextChunk("c1", "t", "d", "/f", None, None)]
        mock_index.return_value = 1
        from backend.rag.indexer import index_file
        result = await index_file("/some/file.txt", collection_name="col")
        mock_load.assert_called_once_with("/some/file.txt")
        mock_index.assert_awaited_once()


class TestIndexDirectory:
    """index_directory 递归扫描目录并全量索引测试。"""

    @patch("backend.rag.indexer.index_chunks", new_callable=AsyncMock)
    @patch("backend.rag.loader.load_directory")
    async def test_delegates(self, mock_load, mock_index):
        """应先调用 load_directory 再调用 index_chunks。"""
        mock_load.return_value = []
        mock_index.return_value = 0
        from backend.rag.indexer import index_directory
        await index_directory("/some/dir")
        mock_load.assert_called_once_with("/some/dir")

# ===========================================================
# llm.py
# ===========================================================

from backend.services.llm import _make_client, _is_quota_error


class TestMakeClient:
    """_make_client 根据 provider 返回正确的 client 和默认模型名。"""

    @patch("backend.services.llm.config")
    def test_spark(self, mock_config):
        """spark provider 应返回 generalv3.5 模型。"""
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("spark")
        assert model == "generalv3.5"

    @patch("backend.services.llm.config")
    def test_deepseek(self, mock_config):
        """deepseek provider 应返回 deepseek-chat 模型。"""        
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("deepseek")
        assert model == "deepseek-chat"

    @patch("backend.services.llm.config")
    def test_qwen(self, mock_config):
        """qwen provider 应返回 qwen-plus 模型。"""        
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("qwen")
        assert model == "qwen-plus"

    @patch("backend.services.llm.config")
    def test_openai(self, mock_config):
        """openai provider 应返回 gpt-4o-mini 模型。"""        
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("openai")
        assert model == "gpt-4o-mini"


class TestIsQuotaError:
    """_is_quota_error 判断 RateLimitError 是否为配额不足。"""

    def test_quota_keyword(self):
        """包含 insufficient_quota 关键词时应返回 True。"""
        from openai import RateLimitError
        # 构造一个 RateLimitError
        err = RateLimitError(
            message="insufficient_quota",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        assert _is_quota_error(err) is True

    def test_non_quota(self):
        """普通限流错误（不含配额关键词）应返回 False。"""        
        from openai import RateLimitError
        err = RateLimitError(
            message="rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        assert _is_quota_error(err) is False


class TestChatCompletion:
    """chat_completion 非流式对话调用测试。"""

    @patch("backend.services.llm.config")
    @patch("backend.services.llm._make_client")
    async def test_basic_call(self, mock_make, mock_config):
        """应正确调用 OpenAI client 并返回模型输出文本。"""
        mock_config.llm.provider = "spark"
        mock_client = AsyncMock()
        mock_choice = MagicMock()
        mock_choice.message.content = "Hello!"
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_make.return_value = (mock_client, "model-x")

        from backend.services.llm import chat_completion
        result = await chat_completion([{"role": "user", "content": "Hi"}])
        assert result == "Hello!"

    @patch("backend.services.llm.config")
    @patch("backend.services.llm._make_client")
    async def test_empty_content(self, mock_make, mock_config):
        mock_config.llm.provider = "spark"
        mock_choice = MagicMock()
        mock_choice.message.content = None
        mock_client = AsyncMock()
        mock_client.chat.completions.create.return_value = MagicMock(choices=[mock_choice])
        mock_make.return_value = (mock_client, "m")

        from backend.services.llm import chat_completion
        result = await chat_completion([{"role": "user", "content": "Hi"}])
        assert result == ""


class TestGetEmbedding:
    @patch("backend.services.llm.config")
    async def test_spark_not_implemented(self, mock_config):
        mock_config.embedding.use_spark = True
        from backend.services.llm import get_embedding
        with pytest.raises(NotImplementedError):
            await get_embedding("test")

    @patch("backend.services.llm._get_embedding_model")
    @patch("backend.services.llm.config")
    async def test_local_embedding(self, mock_config, mock_get_model):
        mock_config.embedding.use_spark = False
        mock_model = MagicMock()
        mock_model.encode.return_value = MagicMock(tolist=lambda: [0.1, 0.2, 0.3])
        mock_get_model.return_value = mock_model
        from backend.services.llm import get_embedding
        result = await get_embedding("test text")
        assert result == [0.1, 0.2, 0.3]
        mock_model.encode.assert_called_once_with("test text")
