"""
backend/db/vector.py
向量数据库（ChromaDB 本地模式）连接与集合管理。
后续如切换至 Qdrant，仅需替换本文件的实现，接口保持不变。
"""

from __future__ import annotations

from typing import Optional

import chromadb
from chromadb import Collection
from chromadb.config import Settings

from backend.config import config

# ----------------------------------------------------------
# 配置
# ----------------------------------------------------------

CHROMA_PERSIST_DIR: str = config.vector_db.persist_dir
COLLECTION_NAME: str = config.vector_db.collection

_client: chromadb.ClientAPI | None = None
_collection: Collection | None = None


# ----------------------------------------------------------
# 初始化
# ----------------------------------------------------------

def init_vector_db() -> None:
    """
    初始化 ChromaDB 客户端与默认集合。
    应在 FastAPI lifespan startup 阶段调用。
    """
    global _client, _collection
    _client = chromadb.PersistentClient(
        path=CHROMA_PERSIST_DIR,
        settings=Settings(anonymized_telemetry=False),
    )
    _collection = _client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"},
    )


def get_collection() -> Collection:
    """返回默认知识库集合。"""
    if _collection is None:
        raise RuntimeError("Vector DB not initialized. Call init_vector_db() first.")
    return _collection


def get_or_create_collection(name: str) -> Collection:
    """按名称获取或创建一个命名集合（用于多课程场景）。"""
    if _client is None:
        raise RuntimeError("Vector DB not initialized.")
    return _client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
    )


# ----------------------------------------------------------
# 基础操作接口（所有实现均为 stub，具体逻辑在 rag/ 层）
# ----------------------------------------------------------

def upsert_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: Optional[list[dict]] = None,
    collection_name: Optional[str] = None,
) -> None:
    """将文档及其向量批量写入向量库。"""
    col = get_or_create_collection(collection_name) if collection_name else get_collection()
    col.upsert(
        ids=ids,
        documents=documents,
        embeddings=embeddings,
        metadatas=metadatas or [{}] * len(ids),
    )


def query_documents(
    query_embedding: list[float],
    n_results: int = 5,
    where: Optional[dict] = None,
    collection_name: Optional[str] = None,
) -> dict:
    """
    按向量相似度检索文档。
    返回 chromadb QueryResult 字典，包含 ids / documents / distances / metadatas。
    """
    col = get_or_create_collection(collection_name) if collection_name else get_collection()
    return col.query(
        query_embeddings=[query_embedding],
        n_results=n_results,
        where=where,
    )


def delete_documents(ids: list[str], collection_name: Optional[str] = None) -> None:
    """按 ID 删除向量库中的文档。"""
    col = get_or_create_collection(collection_name) if collection_name else get_collection()
    col.delete(ids=ids)


def delete_by_doc_id(doc_id: str, collection_name: Optional[str] = None) -> None:
    """删除指定 doc_id 的所有向量（根据 metadata 中的 doc_id 过滤）。"""
    col = get_or_create_collection(collection_name) if collection_name else get_collection()
    col.delete(where={"doc_id": doc_id})


def health_check() -> bool:
    """检查向量库是否可用。"""
    try:
        get_collection().count()
        return True
    except Exception:
        return False
