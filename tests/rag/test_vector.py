"""
tests/rag/test_vector.py
backend/db/vector.py 单元测试（pgvector 实现）。
使用 unittest.mock 模拟数据库引擎。
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.db import vector


# ===========================================================
# 配置常量测试
# ===========================================================

class TestConstants:
    """向量库配置常量测试。"""

    def test_collection_name_from_config(self):
        """COLLECTION_NAME 应来自 config.vector_db.collection。"""
        assert vector.COLLECTION_NAME == vector.config.vector_db.collection


# ===========================================================
# init_vector_db tests
# ===========================================================

class TestInitVectorDb:
    """init_vector_db 函数测试。"""

    def test_init_vector_db_sets_proxy(self):
        """init_vector_db 应正常执行（no-op，仅日志）。"""
        vector._collection_proxy = None
        vector.init_vector_db()
        # init_vector_db 是 no-op，仅记录日志
        # 验证不会抛出异常

    def test_get_collection_creates_proxy(self):
        """get_collection 应返回 _CollectionProxy 实例。"""
        vector._collection_proxy = None
        col = vector.get_collection()
        assert isinstance(col, vector._CollectionProxy)
        assert col.collection_name == vector.COLLECTION_NAME


# ===========================================================
# get_or_create_collection tests
# ===========================================================

class TestGetOrCreateCollection:
    """get_or_create_collection 函数测试。"""

    def test_returns_named_proxy(self):
        """get_or_create_collection 应返回指定名称的代理。"""
        col = vector.get_or_create_collection("test_coll")
        assert isinstance(col, vector._CollectionProxy)
        assert col.collection_name == "test_coll"


# ===========================================================
# _read_where_clause tests
# ===========================================================

class TestBuildWhereClause:
    """_build_where_clause 函数测试。"""

    def test_empty_where_returns_empty(self):
        clause, params = vector._build_where_clause(None)
        assert clause == ""
        assert params == {}

    def test_simple_equality(self):
        clause, params = vector._build_where_clause({"user_id": "abc"})
        assert "user_id =" in clause
        assert list(params.values()) == ["abc"]

    def test_or_clause(self):
        clause, params = vector._build_where_clause(
            {"$or": [{"user_id": "a"}, {"user_id": ""}]}
        )
        assert "OR" in clause
        assert len(params) == 2

    def test_and_clause(self):
        clause, params = vector._build_where_clause(
            {"$and": [{"doc_id": "doc1"}, {"user_id": "u1"}]}
        )
        assert "AND" in clause
        assert len(params) == 2


# ===========================================================
# _convert_metadata_to_columns tests
# ===========================================================

class TestConvertMetadata:
    """_convert_metadata_to_columns 函数测试。"""

    def test_full_metadata(self):
        result = vector._convert_metadata_to_columns({
            "source": "test.pdf",
            "page": "3",
            "section": "Intro",
            "user_id": "user1",
        })
        assert result["source"] == "test.pdf"
        assert result["page"] == 3
        assert result["section"] == "Intro"
        assert result["user_id"] == "user1"

    def test_empty_metadata(self):
        result = vector._convert_metadata_to_columns({})
        assert result["source"] == ""
        assert result["page"] is None
        assert result["section"] == ""
        assert result["user_id"] == ""


# ===========================================================
# _compute_cosine_similarity tests
# ===========================================================

class TestCosineSimilarity:
    """_compute_cosine_similarity 函数测试。"""

    def test_identical_vectors(self):
        emb = [1.0, 0.0, 0.0]
        candidates = [("id1", "doc1", emb, {"k": "v"})]
        result = vector._compute_cosine_similarity(emb, candidates)
        assert len(result) == 1
        assert result[0][2] == pytest.approx(1.0, rel=0.01)

    def test_orthogonal_vectors(self):
        query = [1.0, 0.0]
        candidates = [("id1", "doc1", [0.0, 1.0], {})]
        result = vector._compute_cosine_similarity(query, candidates)
        assert result[0][2] == pytest.approx(0.0, abs=0.01)

    def test_sorted_by_score(self):
        query = [1.0, 0.0]
        candidates = [
            ("id1", "doc1", [0.0, 1.0], {}),
            ("id2", "doc2", [1.0, 0.0], {}),
            ("id3", "doc3", [0.7, 0.7], {}),
        ]
        result = vector._compute_cosine_similarity(query, candidates)
        scores = [r[2] for r in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_candidates(self):
        result = vector._compute_cosine_similarity([1.0], [])
        assert result == []


# ===========================================================
# health_check tests
# ===========================================================

class TestVectorHealthCheck:
    """health_check 函数测试。"""

    @pytest.mark.asyncio
    async def test_health_check_returns_true(self):
        """数据库可用时返回 True。"""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock()
        mock_engine = MagicMock()
        mock_engine.connect.return_value.__aenter__.return_value = mock_conn

        with patch("backend.db.vector.get_engine", return_value=mock_engine):
            result = await vector.health_check()
        assert result is True

    @pytest.mark.asyncio
    async def test_health_check_returns_false_on_error(self):
        """数据库不可用时返回 False。"""
        with patch("backend.db.vector.get_engine", side_effect=RuntimeError("no conn")):
            result = await vector.health_check()
        assert result is False
