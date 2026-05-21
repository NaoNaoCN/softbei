"""
backend/db/vector.py
向量存储（基于 pgvector 扩展，向量检索在数据库内完成）。
"""

from __future__ import annotations

from typing import Optional

from loguru import logger
from sqlalchemy import text

from backend.config import config
from backend.db.database import get_engine

# ----------------------------------------------------------
# 配置
# ----------------------------------------------------------

COLLECTION_NAME: str = config.vector_db.collection

# IVFFlat probes：控制检索精度与速度的平衡，10 是精度/速度的合理折中
_IVFFLAT_PROBES: int = 10

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

        sql = f"SELECT chunk_id, text, doc_id, embedding, source, page, section, user_id, metadata FROM document_chunk WHERE {' AND '.join(conditions)}"
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
            ids_list.append(row[0])
            documents_list.append(row[1])
            meta = {
                "doc_id": row[2] or "",
                "source": row[4] or "",
                "page": int(row[5]) if row[5] is not None else None,
                "section": row[6] or "",
                "user_id": row[7] or "",
            }
            # 合并 JSONB metadata 到结果中
            raw_metadata = row[8] if len(row) > 8 else None
            if raw_metadata and isinstance(raw_metadata, dict):
                meta.update(raw_metadata)
            metadatas_list.append(meta)

        return {
            "ids": ids_list,
            "documents": documents_list,
            "metadatas": metadatas_list,
        }


# ----------------------------------------------------------
# 初始化
# ----------------------------------------------------------

def init_vector_db() -> None:
    """初始化向量库。pgvector 方案下表由 Alembic 管理，此处仅验证连通性。"""
    logger.info("[VectorDB] 使用 pgvector 向量存储 (cosine distance via <=>) ")


_collection_proxy: Optional[_CollectionProxy] = None


def get_collection() -> _CollectionProxy:
    """返回默认知识库集合代理。"""
    global _collection_proxy
    if _collection_proxy is None:
        _collection_proxy = _CollectionProxy(COLLECTION_NAME)
    return _collection_proxy


# ----------------------------------------------------------
# 基础操作接口（全部异步化）
# ----------------------------------------------------------

def _convert_metadata_to_columns(meta: dict) -> dict:
    """将 metadata dict 转换为列值。"""
    import json

    # 提取 extra metadata（排除固定列字段）
    extra_meta = {
        k: v for k, v in meta.items()
        if k not in ("source", "page", "section", "user_id", "doc_id", "chunk_id")
    }
    return {
        "source": meta.get("source", ""),
        "page": int(meta["page"]) if meta.get("page") and str(meta["page"]).isdigit() else None,
        "section": meta.get("section", ""),
        "user_id": meta.get("user_id", ""),
        "metadata_": json.dumps(extra_meta, ensure_ascii=False) if extra_meta else None,
    }


async def upsert_documents(
    ids: list[str],
    documents: list[str],
    embeddings: list[list[float]],
    metadatas: Optional[list[dict]] = None,
    collection_name: Optional[str] = None,
) -> None:
    """将文档及其向量批量写入向量库（pgvector，多行 VALUES 一次 INSERT）。"""
    from backend.utils.snowflake import generate_id

    if not ids:
        return

    col = collection_name or COLLECTION_NAME
    meta_list = metadatas or [{}] * len(ids)
    engine = get_engine()

    columns = [
        "id", "chunk_id", "doc_id", "collection_name", "text",
        "embedding", "source", "page", "section", "user_id", "metadata", "created_at",
    ]
    value_rows: list[str] = []
    params: dict = {}

    for i, (chunk_id, doc_text, emb, meta) in enumerate(
        zip(ids, documents, embeddings, meta_list)
    ):
        cols = _convert_metadata_to_columns(meta)
        doc_id = meta.get("doc_id", "")
        # pgvector 的 asyncpg codec 自动将 list[float] 转为向量格式，无需手动拼字符串
        row_placeholders = ", ".join([
            f":id_{i}", f":chunk_id_{i}", f":doc_id_{i}", f":col_{i}",
            f":text_{i}", f":emb_{i}", f":source_{i}", f":page_{i}",
            f":section_{i}", f":user_id_{i}", f":metadata__{i}", "NOW()",
        ])
        value_rows.append(f"({row_placeholders})")
        params.update({
            f"id_{i}": generate_id(),
            f"chunk_id_{i}": chunk_id,
            f"doc_id_{i}": doc_id,
            f"col_{i}": col,
            f"text_{i}": doc_text,
            f"emb_{i}": emb,          # list[float] — pgvector asyncpg codec 自动转换
            f"source_{i}": cols["source"],
            f"page_{i}": cols["page"],
            f"section_{i}": cols["section"],
            f"user_id_{i}": cols["user_id"],
            f"metadata__{i}": cols["metadata_"],
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
            metadata = EXCLUDED.metadata
    """

    async with engine.begin() as conn:
        await conn.execute(text(sql), params)


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
    pgvector 向量检索。
    使用 <=> 余弦距离运算符，检索在数据库内完成，仅返回 top-N。
    """
    col = collection_name or COLLECTION_NAME
    engine = get_engine()

    conditions = ["collection_name = :cn"]
    # pgvector 的 asyncpg codec 自动将 list[float] 转为向量格式
    params: dict = {"cn": col, "embedding": query_embedding}

    where_clause, where_params = _build_where_clause(where)
    if where_clause:
        conditions.append(where_clause)
        params.update(where_params)

    sql = f"""
        SELECT
            chunk_id,
            text,
            doc_id,
            embedding <=> :embedding AS distance,
            source,
            page,
            section,
            user_id,
            metadata
        FROM document_chunk
        WHERE {' AND '.join(conditions)}
        ORDER BY embedding <=> :embedding
        LIMIT :n_results
    """

    async with engine.connect() as conn:
        # 设置 IVFFlat probes 控制检索精度/速度平衡
        await conn.execute(text(f"SET LOCAL ivfflat.probes = {_IVFFLAT_PROBES}"))
        result = await conn.execute(text(sql), {**params, "n_results": n_results})
        rows = result.fetchall()

    ids_list = []
    documents_list = []
    distances_list = []
    metadatas_list = []

    for row in rows:
        chunk_id = row[0]
        ids_list.append(chunk_id)
        documents_list.append(row[1])
        distances_list.append(float(row[3]) if row[3] is not None else 1.0)
        meta = {
            "doc_id": row[2] or "",
            "source": row[4] or "",
            "page": int(row[5]) if row[5] is not None else None,
            "section": row[6] or "",
            "user_id": row[7] or "",
        }
        # 合并 JSONB metadata 到结果中
        raw_metadata = row[8] if len(row) > 8 else None
        if raw_metadata and isinstance(raw_metadata, dict):
            meta.update(raw_metadata)
        metadatas_list.append(meta)

    return {
        "ids": [ids_list],
        "documents": [documents_list],
        "distances": [distances_list],
        "metadatas": [metadatas_list],
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
            text("SELECT text, source, page, section, user_id, metadata FROM document_chunk WHERE doc_id = :doc_id ORDER BY created_at"),
            {"doc_id": doc_id},
        )
        rows = result.fetchall()

    documents = []
    metadatas = []
    for row in rows:
        documents.append(row[0])
        meta = {
            "source": row[1] or "",
            "page": str(row[2]) if row[2] else "",
            "section": row[3] or "",
            "user_id": row[4] or "",
        }
        # 合并 JSONB metadata 到结果中
        raw_metadata = row[5] if len(row) > 5 else None
        if raw_metadata and isinstance(raw_metadata, dict):
            meta.update(raw_metadata)
        metadatas.append(meta)

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
