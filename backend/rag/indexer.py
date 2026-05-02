"""
backend/rag/indexer.py
向量索引构建器：将 TextChunk 列表嵌入并写入向量库。
"""

from __future__ import annotations

import asyncio
from typing import Callable, Optional

from backend.db.vector import upsert_documents
from backend.rag.loader import TextChunk
from backend.services.llm import get_embedding


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def index_chunks(
    chunks: list[TextChunk],
    collection_name: Optional[str] = None,
    batch_size: int = 32,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> int:
    """
    将文本块批量嵌入并写入向量库。

    :param chunks:             TextChunk 列表（来自 loader）
    :param collection_name:    目标集合名，None 使用默认集合
    :param batch_size:         每批嵌入请求的大小
    :param progress_callback:  可选回调 (batch_num, total_batches)，每批完成后调用
    :return:                   成功写入的 chunk 数量
    """
    total = 0
    import logging
    _log = logging.getLogger(__name__)
    _log.info(f"[Indexer] 开始索引 {len(chunks)} 个文本块，batch_size={batch_size}")
    batches = list(range(0, len(chunks), batch_size))
    total_batches = len(batches)
    for batch_num, i in enumerate(batches, start=1):
        batch = chunks[i : i + batch_size]
        _log.info(f"[Indexer] 正在 embedding 第 {i+1}-{i+len(batch)}/{len(chunks)} 块...")
        embeddings = await _embed_batch([c.text for c in batch])
        upsert_documents(
            ids=[c.chunk_id for c in batch],
            documents=[c.text for c in batch],
            embeddings=embeddings,
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "source": c.source_path,
                    "page": str(c.page or ""),
                    "section": c.section or "",
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
    """并发嵌入一批文本（最多 8 个并发调用）。"""
    semaphore = asyncio.Semaphore(8)

    async def _embed_one(text: str) -> list[float]:
        async with semaphore:
            return await get_embedding(text)

    return await asyncio.gather(*[_embed_one(t) for t in texts])
