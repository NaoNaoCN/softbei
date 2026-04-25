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
    def test_basic(self):
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
        raw = {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}
        assert _parse_results(raw, 0.5) == []

    def test_missing_fields(self):
        raw = {}
        assert _parse_results(raw, 0.5) == []

    def test_sorted_by_score_desc(self):
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
    @patch("backend.rag.retriever.query_documents")
    @patch("backend.rag.retriever.get_embedding", new_callable=AsyncMock)
    async def test_basic(self, mock_embed, mock_query):
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
        mock_embed.return_value = [0.0]
        mock_query.return_value = {"ids": [[]], "documents": [[]], "distances": [[]], "metadatas": [[]]}
        await retrieve("q", n_results=10, where={"doc_id": "x"}, collection_name="col")
        _, kwargs = mock_query.call_args
        assert kwargs["n_results"] == 10
        assert kwargs["where"] == {"doc_id": "x"}
        assert kwargs["collection_name"] == "col"


class TestRetrieveByKp:
    @patch("backend.rag.retriever.retrieve", new_callable=AsyncMock)
    async def test_prefix(self, mock_retrieve):
        mock_retrieve.return_value = []
        await retrieve_by_kp("梯度下降", n_results=8)
        args, kwargs = mock_retrieve.call_args
        assert "知识点：梯度下降" in args or kwargs.get("query") == "知识点：梯度下降"


# ===========================================================
# retriever.py — format_context
# ===========================================================

class TestFormatContext:
    def test_basic(self):
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
        assert format_context([]) == ""

    def test_truncation(self):
        chunks = [
            RetrievedChunk(f"c{i}", "A" * 5000, 0.9, "d", "f.txt")
            for i in range(10)
        ]
        ctx = format_context(chunks, max_tokens=100)
        # 应该被截断，不会包含所有 10 个
        assert ctx.count("[") < 10

    def test_page_and_section_display(self):
        c = RetrievedChunk("c1", "t", 0.9, "d", "f.txt", page=3, section="第二章")
        ctx = format_context([c])
        assert "第 3 页" in ctx
        assert "第二章" in ctx


# ===========================================================
# indexer.py
# ===========================================================

from backend.rag.loader import TextChunk


class TestIndexChunks:
    @patch("backend.rag.indexer.upsert_documents")
    @patch("backend.rag.indexer.get_embedding", new_callable=AsyncMock)
    async def test_single_batch(self, mock_embed, mock_upsert):
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
        mock_embed.return_value = [0.1]
        chunks = [TextChunk(f"c{i}", f"t{i}", "d", "/f", None, None) for i in range(5)]
        from backend.rag.indexer import index_chunks
        total = await index_chunks(chunks, batch_size=2)
        assert total == 5
        assert mock_upsert.call_count == 3  # 2+2+1

    @patch("backend.rag.indexer.upsert_documents")
    @patch("backend.rag.indexer.get_embedding", new_callable=AsyncMock)
    async def test_empty(self, mock_embed, mock_upsert):
        from backend.rag.indexer import index_chunks
        total = await index_chunks([])
        assert total == 0
        mock_upsert.assert_not_called()


class TestIndexFile:
    @patch("backend.rag.indexer.index_chunks", new_callable=AsyncMock)
    @patch("backend.rag.loader.load_file")
    async def test_delegates(self, mock_load, mock_index):
        mock_load.return_value = [TextChunk("c1", "t", "d", "/f", None, None)]
        mock_index.return_value = 1
        from backend.rag.indexer import index_file
        result = await index_file("/some/file.txt", collection_name="col")
        mock_load.assert_called_once_with("/some/file.txt")
        mock_index.assert_awaited_once()


class TestIndexDirectory:
    @patch("backend.rag.indexer.index_chunks", new_callable=AsyncMock)
    @patch("backend.rag.loader.load_directory")
    async def test_delegates(self, mock_load, mock_index):
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
    @patch("backend.services.llm.config")
    def test_spark(self, mock_config):
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("spark")
        assert model == "generalv3.5"

    @patch("backend.services.llm.config")
    def test_deepseek(self, mock_config):
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("deepseek")
        assert model == "deepseek-chat"

    @patch("backend.services.llm.config")
    def test_qwen(self, mock_config):
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("qwen")
        assert model == "qwen-plus"

    @patch("backend.services.llm.config")
    def test_openai(self, mock_config):
        mock_config.llm.api_key = "test_key"
        client, model = _make_client("openai")
        assert model == "gpt-4o-mini"


class TestIsQuotaError:
    def test_quota_keyword(self):
        from openai import RateLimitError
        # 构造一个 RateLimitError
        err = RateLimitError(
            message="insufficient_quota",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        assert _is_quota_error(err) is True

    def test_non_quota(self):
        from openai import RateLimitError
        err = RateLimitError(
            message="rate limit exceeded",
            response=MagicMock(status_code=429, headers={}),
            body=None,
        )
        assert _is_quota_error(err) is False


class TestChatCompletion:
    @patch("backend.services.llm.config")
    @patch("backend.services.llm._make_client")
    async def test_basic_call(self, mock_make, mock_config):
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
