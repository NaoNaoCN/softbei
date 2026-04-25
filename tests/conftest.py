"""
tests/conftest.py
全局 pytest fixtures。
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def patch_llm_layer():
    """
    Mock get_embedding 和 query_documents，防止在测试时
    加载真实的 sentence-transformers 模型或连接向量数据库。
    仅在使用时启用，不自动应用于所有测试（如 vector 单元测试需要真实 query_documents）。
    """
    embedding_patcher = patch(
        "backend.services.llm.get_embedding",
        new_callable=AsyncMock,
        return_value=[0.0] * 384,
    )
    query_patcher = patch(
        "backend.db.vector.query_documents",
        return_value={
            "ids": [[]],
            "documents": [[]],
            "distances": [[]],
            "metadatas": [[]],
        },
    )
    emb_mock = embedding_patcher.start()
    query_mock = query_patcher.start()
    yield
    embedding_patcher.stop()
    query_patcher.stop()
