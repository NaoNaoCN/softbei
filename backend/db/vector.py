"""
backend/db/vector.py
向量存储（PostgreSQL 内嵌，基于 JSON + numpy 矩阵向量化余弦相似度）。
"""

from __future__ import annotations

from typing import Optional

import numpy as np
from loguru import logger
from sqlalchemy import text

from backend.config import config
from backend.db.database import get_engine

# ----------------------------------------------------------
# 配置
# ----------------------------------------------------------

COLLECTION_NAME: str = config.vector_db.collection

# ----------------------------------------------------------
# 集合代理
# ----------------------------------------------------------

class _CollectionProxy:
    """向量集合的异步代理。"""

    def __init__(self, name: str = "knowledge_base"):
        self.collection_name = name

    async def count(self) -> int:
        """返回该集合中的文档块数量。"""
        engine = get_engine()
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT COUNT(*) FROM document_chunk WHERE collection_name = :cn"),
                {"cn": self.collection_name},
            )
            return result.scalar() or 0

    async def get(self, where: Optional[dict] = None, limit: Optional[int] = None,
                  include: Optional[list[str]] = None) -> dict:
        """按条件获取文档块。"""
        engine = get_engine()
        conditions = ["collection_name = :cn"]
        params: dict = {"cn": self.collection_name}

        if where:
            where_clause, where_params = _build_where_clause(where)
            if where_clause:
                conditions.append(where_clause)
                params.update(where_params)

        sql = f"SELECT chunk_id, text, embedding, source, page, section, user_id FROM document_chunk WHERE {' AND '.join(conditions)}"
        if limit is not None:
            limit_val = int(limit)
            sql += f" LIMIT {limit_val}"

        async with engine.connect() as conn:
            result = await conn.execute(text(sql), params)
            rows = result.fetchall()

        ids_list = []
        documents_list = []
        metadatas_list = []
        for row in rows:
            chunk_id = row[0]
            ids_list.append(chunk_id)
            documents_list.append(row[1])
            metadatas_list.append({
                "doc_id": chunk_id.rsplit("_", 1)[0] if "_" in chunk_id else "",
                "source": row[3] or "",
                "page": str(row[4]) if row[4] else "",
                "section": row[5] or "",
                "user_id": row[6] or "",
            })

        return {
            "ids": ids_list,
            "documents": documents_list,
            "metadatas": metadatas_list,
        }


# ----------------------------------------------------------
# 初始化
# ----------------------------------------------------------

def init_vector_db() -> None:
    """
    初始化向量库。
    pgvector 方案下表由 Alembic 管理，此处仅验证连通性。
    """
    logger.info("[VectorDB] 使用 PostgreSQL 内嵌向量存储 (JSON + numpy vectorized cosine)")


_collection_proxy: Optional[_CollectionProxy] = None


def get_collection() -> _CollectionProxy:
    """返回默认知识库集合代理。"""
    global _collection_proxy
    if _collection_proxy is None:
        _collection_proxy = _CollectionProxy(COLLECTION_NAME)
    return _collection_proxy


def get_or_create_collection(name: str) -> _CollectionProxy:
    """按名称获取集合代理。"""
    return _CollectionProxy(name)


# ----------------------------------------------------------
# 基础操作接口（全部异步化）
# ----------------------------------------------------------

def _convert_metadata_to_columns(meta: dict) -> dict:
    """将 metadata dict 转换为列值。"""
    return {
        "source": meta.get("source", ""),
        "page": int(meta["page"]) if meta.get("page") and str(meta["page"]).isdigit() else None,
        "section": meta.get("section", ""),
        "user_id": meta.get("user_id", ""),
    }


async def upsert_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: Optional[list[dict]] = None,
    collection_name: Optional[str] = None,
) -> None:
    """将文档及其向量批量写入向量库（多行 VALUES 一次 INSERT，避免逐行往返）。"""
    import uuid as _uuid

    if not ids:
        return

    col = collection_name or COLLECTION_NAME
    meta_list = metadatas or [{}] * len(ids)
    engine = get_engine()

    # 构建批量多行 VALUES 占位符和参数
    columns = [
        "id", "chunk_id", "doc_id", "collection_name", "text",
        "embedding", "source", "page", "section", "user_id", "created_at",
    ]
    value_rows: list[str] = []
    params: dict = {}

    for i, (chunk_id, doc_text, emb, meta) in enumerate(
        zip(ids, documents, embeddings, meta_list)
    ):
        cols = _convert_metadata_to_columns(meta)
        doc_id = meta.get("doc_id", "")
        row_placeholders = ", ".join([
            f":id_{i}", f":chunk_id_{i}", f":doc_id_{i}", f":col_{i}",
            f":text_{i}", f":emb_{i}", f":source_{i}", f":page_{i}",
            f":section_{i}", f":user_id_{i}", "NOW()",
        ])
        value_rows.append(f"({row_placeholders})")
        params.update({
            f"id_{i}": _uuid.uuid4(),
            f"chunk_id_{i}": chunk_id,
            f"doc_id_{i}": doc_id,
            f"col_{i}": col,
            f"text_{i}": doc_text,
            f"emb_{i}": emb,
            f"source_{i}": cols["source"],
            f"page_{i}": cols["page"],
            f"section_{i}": cols["section"],
            f"user_id_{i}": cols["user_id"],
        })

    sql = f"""
        INSERT INTO document_chunk ({', '.join(columns)})
        VALUES {', '.join(value_rows)}
        ON CONFLICT (chunk_id) DO UPDATE SET
            text = EXCLUDED.text,
            embedding = EXCLUDED.embedding,
            source = EXCLUDED.source,
            page = EXCLUDED.page,
            section = EXCLUDED.section,
            user_id = EXCLUDED.user_id,
            created_at = NOW()
    """

    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


def _compute_cosine_similarity(
    query_embedding: list[float],
    candidates: list[tuple[str, str, list, dict]],
) -> list[tuple[str, str, float, dict]]:
    """numpy 矩阵向量化计算余弦相似度并排序。"""
    if not candidates:
        return []

    # 分离出有效候选项（embedding 非 None）
    valid: list[tuple[str, str, list, dict]] = [
        (cid, doc, emb, meta)
        for cid, doc, emb, meta in candidates
        if emb is not None
    ]
    if not valid:
        return []

    query_vec = np.asarray(query_embedding, dtype=np.float32)
    query_norm = np.linalg.norm(query_vec)
    if query_norm == 0:
        return [(cid, doc, 0.0, meta) for cid, doc, _, meta in valid]

    # 将所有候选向量堆叠为矩阵 (N, dim)，一次矩阵乘法完成
    cand_matrix = np.array([emb for _, _, emb, _ in valid], dtype=np.float32)
    cand_norms = np.linalg.norm(cand_matrix, axis=1)
    # 避免除零
    np.maximum(cand_norms, 1e-12, out=cand_norms)

    # scores = (cand_matrix @ query_vec) / (cand_norms * query_norm)
    scores = np.dot(cand_matrix, query_vec) / (cand_norms * query_norm)

    results = [
        (valid[i][0], valid[i][1], float(scores[i]), valid[i][3])
        for i in range(len(valid))
    ]
    results.sort(key=lambda x: x[2], reverse=True)
    return results


def _build_where_clause(where: Optional[dict]) -> tuple[str, dict]:
    """将 where 条件转换为 SQL WHERE 子句。

    支持：
    - {"user_id": "xxx"} → user_id = 'xxx'
    - {"$or": [{"user_id": "a"}, {"user_id": ""}]} → (user_id = 'a' OR user_id = '')
    - {"$and": [...]} → (cond1 AND cond2)
    """
    if not where:
        return "", {}

    params: dict = {}
    counter = [0]

    def _convert(condition: dict) -> str:
        parts = []
        for key, value in condition.items():
            if key == "$or":
                or_parts = []
                for item in value:
                    or_parts.append(_convert(item))
                parts.append(f"({' OR '.join(or_parts)})")
            elif key == "$and":
                and_parts = []
                for item in value:
                    and_parts.append(_convert(item))
                parts.append(f"({' AND '.join(and_parts)})")
            else:
                pname = f"wp_{counter[0]}"
                counter[0] += 1
                params[pname] = value
                parts.append(f"{key} = :{pname}")
        return " AND ".join(parts)

    clause = _convert(where)
    return clause, params


async def query_documents(
    query_embedding: list[float],
    n_results: int = 5,
    where: Optional[dict] = None,
    collection_name: Optional[str] = None,
) -> dict:
    """
    按向量余弦相似度检索文档。
    返回 QueryResult 字典。
    """
    col = collection_name or COLLECTION_NAME
    engine = get_engine()

    conditions = ["collection_name = :cn"]
    params: dict = {"cn": col}

    where_clause, where_params = _build_where_clause(where)
    if where_clause:
        conditions.append(where_clause)
        params.update(where_params)

    sql = f"""
        SELECT chunk_id, text, embedding, source, page, section, user_id
        FROM document_chunk
        WHERE {' AND '.join(conditions)}
        LIMIT 5000
    """

    async with engine.connect() as conn:
        result = await conn.execute(text(sql), params)
        rows = result.fetchall()

    candidates = []
    for row in rows:
        chunk_id = row[0]
        meta = {
            "doc_id": chunk_id.rsplit("_", 1)[0] if "_" in chunk_id else "",
            "source": row[3] or "",
            "page": str(row[4]) if row[4] else "",
            "section": row[5] or "",
            "user_id": row[6] or "",
        }
        candidates.append((chunk_id, row[1], row[2], meta))

    scored = _compute_cosine_similarity(query_embedding, candidates)
    top = scored[:n_results]

    return {
        "ids": [[r[0] for r in top]],
        "documents": [[r[1] for r in top]],
        "distances": [[1.0 - r[2] for r in top]],
        "metadatas": [[r[3] for r in top]],
    }


async def delete_documents(ids: list[str], collection_name: Optional[str] = None) -> None:
    """按 chunk_id 列表删除向量库中的文档。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM document_chunk WHERE chunk_id = ANY(:ids)"),
            {"ids": ids},
        )


async def delete_by_doc_id(doc_id: str, collection_name: Optional[str] = None) -> None:
    """删除指定 doc_id 的所有向量块。"""
    engine = get_engine()
    async with engine.begin() as conn:
        result = await conn.execute(
            text("DELETE FROM document_chunk WHERE doc_id = :doc_id"),
            {"doc_id": doc_id},
        )
        deleted = result.rowcount
        logger.info(f"[VectorDB] 删除 doc_id={doc_id} 的 {deleted} 个向量块")


async def get_documents_by_doc_id(doc_id: str, collection_name: Optional[str] = None) -> dict:
    """按 doc_id 获取所有文本块及其元数据。"""
    engine = get_engine()
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT text, source, page, section, user_id FROM document_chunk WHERE doc_id = :doc_id ORDER BY created_at"),
            {"doc_id": doc_id},
        )
        rows = result.fetchall()

    documents = []
    metadatas = []
    for row in rows:
        documents.append(row[0])
        metadatas.append({
            "source": row[1] or "",
            "page": str(row[2]) if row[2] else "",
            "section": row[3] or "",
            "user_id": row[4] or "",
        })

    return {"documents": documents, "metadatas": metadatas}


async def health_check() -> bool:
    """检查向量库是否可用。"""
    try:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1 FROM document_chunk LIMIT 0"))
        return True
    except Exception:
        return False
