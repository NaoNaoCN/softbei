"""
backend/rag/indexer.py
向量索引构建器：将 TextChunk 列表嵌入并写入向量库。
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from loguru import logger  # noqa: F401

from backend.config import config
from backend.db.vector import upsert_documents, delete_by_doc_id
from backend.rag.loader import TextChunk
from backend.services.llm import get_embeddings_batch


# DashScope text-embedding-v4 单次 API 最多 25 条
_API_MAX_BATCH = 25


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def index_chunks(
    chunks: list[TextChunk],
    collection_name: Optional[str] = None,
    batch_size: int = None,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    user_id: Optional[str] = None,
) -> int:
    """
    将文本块批量嵌入并写入向量库。

    :param chunks:             TextChunk 列表（来自 loader）
    :param collection_name:    目标集合名，None 使用默认集合
    :param batch_size:         每批嵌入请求的大小（上限受 API 限制）
    :param progress_callback:  可选回调 (batch_num, total_batches)，每批完成后调用
    :param user_id:            上传用户 ID，写入 metadata 用于账户隔离
    :return:                   成功写入的 chunk 数量
    """
    if not chunks:
        return 0

    if batch_size is None:
        batch_size = config.embedding.index_batch_size
    # 不超过 API 单次最大 batch 数
    effective_batch_size = min(batch_size, _API_MAX_BATCH)

    total = 0
    logger.info(
        f"[Indexer] 开始索引 {len(chunks)} 个文本块，"
        f"batch_size={effective_batch_size}（API上限={_API_MAX_BATCH}）, user_id={user_id}"
    )

    # 预清理：按 doc_id 去重后删除旧 chunk，防止增量索引产生 orphan
    affected_doc_ids = set(c.doc_id for c in chunks if c.doc_id)
    for doc_id in affected_doc_ids:
        try:
            await delete_by_doc_id(doc_id, collection_name=collection_name)
        except Exception as e:
            logger.warning(f"[Indexer] 清理旧 chunk 失败 doc_id={doc_id}: {e}")

    batches = list(range(0, len(chunks), effective_batch_size))
    total_batches = len(batches)
    for batch_num, i in enumerate(batches, start=1):
        batch = chunks[i : i + effective_batch_size]
        logger.info(
            f"[Indexer] 正在 embedding 第 {i+1}-{i+len(batch)}/{len(chunks)} 块..."
        )
        embeddings = await _embed_batch([c.text for c in batch])
        await upsert_documents(
            ids=[c.chunk_id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeddings,
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "source": c.source_path,
                    "page": str(c.page or ""),
                    "section": c.section or "",
                    "user_id": user_id or "",
                    **c.metadata,
                }
                for c in batch
            ],
            collection_name=collection_name,
        )
        total += len(batch)
        if progress_callback is not None:
            progress_callback(batch_num, total_batches)
    return total


async def index_file(
    file_path: str,
    collection_name: Optional[str] = None,
) -> int:
    """
    一键加载并索引单个文件。
    内部调用 loader.load_file + index_chunks。
    """
    from backend.rag.loader import load_file
    chunks = load_file(file_path)
    return await index_chunks(chunks, collection_name=collection_name)


async def index_directory(
    dir_path: str,
    collection_name: Optional[str] = None,
) -> int:
    """递归扫描目录并全量索引。"""
    from backend.rag.loader import load_directory
    chunks = load_directory(dir_path)
    return await index_chunks(chunks, collection_name=collection_name)


# ----------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------

async def _embed_batch(texts: list[str]) -> list[list[float]]:
    """批量嵌入文本，使用 API 批量接口一次发送多条。"""
    if not texts:
        return []
    return await get_embeddings_batch(texts)
