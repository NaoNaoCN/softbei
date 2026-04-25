"""
tests/test_vector.py
backend/db/vector.py 单元测试。
使用 unittest.mock 模拟 ChromaDB 客户端。
"""

import pytest
from unittest.mock import MagicMock, patch

from backend.db import vector


# ===========================================================
# 配置常量测试
# ===========================================================

class TestConstants:
    """向量库配置常量测试。"""

    def test_collection_name_from_config(self):
        """COLLECTION_NAME 应来自 config.vector_db.collection。"""
        assert vector.COLLECTION_NAME == vector.config.vector_db.collection

    def test_persist_dir_from_config(self):
        """CHROMA_PERSIST_DIR 应来自 config.vector_db.persist_dir。"""
        assert vector.CHROMA_PERSIST_DIR == vector.config.vector_db.persist_dir


# ===========================================================
# init_vector_db tests
# ===========================================================

class TestInitVectorDb:
    """init_vector_db 函数测试。"""

    def test_init_vector_db_creates_client(self):
        """init_vector_db 应创建 ChromaDB 客户端。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        assert vector._client is mock_client
        assert vector._collection is mock_collection
        mock_client.get_or_create_collection.assert_called_once()

    def test_init_vector_db_telemetry_disabled(self):
        """init_vector_db 应禁用匿名遥测。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client) as mock_pc:
            vector.init_vector_db()
            _, kwargs = mock_pc.call_args
            assert kwargs["settings"].anonymized_telemetry is False

    def test_init_vector_db_uses_cosine_metadata(self):
        """默认集合应使用 cosine 距离度量。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        _, kwargs = mock_client.get_or_create_collection.call_args
        assert kwargs["metadata"]["hnsw:space"] == "cosine"


# ===========================================================
# get_collection tests
# ===========================================================

class TestGetCollection:
    """get_collection 函数测试。"""

    def test_get_collection_before_init_raises(self):
        """集合未初始化时应抛出 RuntimeError。"""
        vector._collection = None
        with pytest.raises(RuntimeError, match="not initialized"):
            vector.get_collection()

    def test_get_collection_returns_collection(self):
        """初始化后应返回集合对象。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        result = vector.get_collection()
        assert result is mock_collection


# ===========================================================
# get_or_create_collection tests
# ===========================================================

class TestGetOrCreateCollection:
    """get_or_create_collection 函数测试。"""

    def test_get_or_create_collection_before_init_raises(self):
        """客户端未初始化时应抛出 RuntimeError。"""
        vector._client = None
        with pytest.raises(RuntimeError, match="not initialized"):
            vector.get_or_create_collection("test_collection")

    def test_get_or_create_collection_creates_named_collection(self):
        """按名称创建/获取集合，传入 name 参数。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        result = vector.get_or_create_collection("custom_collection")
        mock_client.get_or_create_collection.assert_called_with(
            name="custom_collection",
            metadata={"hnsw:space": "cosine"},
        )
        assert result is mock_collection


# ===========================================================
# upsert_documents tests
# ===========================================================

class TestUpsertDocuments:
    """upsert_documents 函数测试。"""

    def test_upsert_uses_default_collection(self):
        """不指定 collection_name 时使用默认集合。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.upsert_documents(
            ids=["1"],
            documents=["doc text"],
            embeddings=[[0.1, 0.2]],
        )
        mock_collection.upsert.assert_called_once()

    def test_upsert_uses_named_collection(self):
        """指定 collection_name 时使用命名集合。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.upsert_documents(
            ids=["1"],
            documents=["doc text"],
            embeddings=[[0.1, 0.2]],
            collection_name="custom",
        )
        mock_client.get_or_create_collection.assert_called_with(
            name="custom",
            metadata={"hnsw:space": "cosine"},
        )

    def test_upsert_fills_empty_metadata(self):
        """metadatas 为 None 时应填充空字典列表。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.upsert_documents(
            ids=["1", "2"],
            documents=["doc1", "doc2"],
            embeddings=[[0.1], [0.2]],
            metadatas=None,
        )
        _, kwargs = mock_collection.upsert.call_args
        assert kwargs["metadatas"] == [{}, {}]


# ===========================================================
# query_documents tests
# ===========================================================

class TestQueryDocuments:
    """query_documents 函数测试。"""

    def test_query_uses_default_collection(self):
        """不指定 collection_name 时使用默认集合。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [], "documents": []}
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.query_documents(query_embedding=[0.1, 0.2], n_results=3)
        mock_collection.query.assert_called_once()

    def test_query_passes_n_results(self):
        """query_documents 应传递 n_results 参数。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [], "documents": []}
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.query_documents(query_embedding=[0.1], n_results=7)
        _, kwargs = mock_collection.query.call_args
        assert kwargs["n_results"] == 7

    def test_query_passes_where_filter(self):
        """query_documents 应传递 where 过滤条件。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.query.return_value = {"ids": [], "documents": []}
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        filter_where = {"kp_id": "kp_01"}
        vector.query_documents(query_embedding=[0.1], n_results=5, where=filter_where)
        _, kwargs = mock_collection.query.call_args
        assert kwargs["where"] == filter_where


# ===========================================================
# delete_documents tests
# ===========================================================

class TestDeleteDocuments:
    """delete_documents 函数测试。"""

    def test_delete_uses_default_collection(self):
        """不指定 collection_name 时使用默认集合。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.delete_documents(ids=["id1", "id2"])
        mock_collection.delete.assert_called_once_with(ids=["id1", "id2"])

    def test_delete_with_named_collection(self):
        """指定 collection_name 时使用命名集合。"""
        vector._client = None
        vector._collection = None

        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        vector.delete_documents(ids=["id1"], collection_name="custom")
        mock_client.get_or_create_collection.assert_called_with(
            name="custom",
            metadata={"hnsw:space": "cosine"},
        )


# ===========================================================
# health_check tests
# ===========================================================

class TestVectorHealthCheck:
    """health_check 函数测试。"""

    def test_health_check_returns_true_on_success(self):
        """集合 count() 成功时返回 True。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.return_value = 10
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        result = vector.health_check()
        assert result is True

    def test_health_check_returns_false_on_exception(self):
        """集合 count() 抛出异常时返回 False。"""
        vector._collection = None
        mock_client = MagicMock()
        mock_collection = MagicMock()
        mock_collection.count.side_effect = RuntimeError("connection failed")
        mock_client.get_or_create_collection.return_value = mock_collection

        with patch("backend.db.vector.chromadb.PersistentClient", return_value=mock_client):
            vector.init_vector_db()

        result = vector.health_check()
        assert result is False
