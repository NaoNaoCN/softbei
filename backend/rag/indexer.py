"""
backend/rag/indexer.py
向量索引构建器：将 TextChunk 列表嵌入并写入向量库。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Callable, Optional

from loguru import logger  # noqa: F401

from backend.config import config
from backend.db.vector import (
    upsert_documents, delete_documents,
    get_chunk_hashes_by_doc_id,
)
from backend.rag.loader import TextChunk
from backend.services.llm import get_embeddings_batch


# DashScope text-embedding-v4 单次 API 最多 10 条
_API_MAX_BATCH = 10


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
    增量索引文本块到向量库。

    对比新旧 chunk（按 doc_id 分组，基于 content_hash MD5 去重）：
    - 新 chunk 或内容变更的 chunk → 重新嵌入并 upsert
    - 内容未变的 chunk → 跳过，节省 Embedding API 费用
    - 旧集合中存在但新集合中不存在的 chunk → 删除

    :param chunks:             TextChunk 列表（来自 loader）
    :param collection_name:    目标集合名，None 使用默认集合
    :param batch_size:         每批嵌入请求的大小（上限受 API 限制）
    :param progress_callback:  可选回调 (batch_num, total_batches)，每批完成后调用
    :param user_id:            上传用户 ID，写入 metadata 用于账户隔离
    :return:                   成功 upsert 的 chunk 数量（不含 skip 数）
    """
    if not chunks:
        return 0

    if batch_size is None:
        batch_size = config.embedding.index_batch_size
    effective_batch_size = min(batch_size, _API_MAX_BATCH)

    # ---- Phase 1: 按 doc_id 分组，基于 content_hash 做 diff ----
    by_doc: dict[str, list[TextChunk]] = {}
    for c in chunks:
        if c.doc_id:
            by_doc.setdefault(c.doc_id, []).append(c)

    to_embed: list[TextChunk] = []          # INSERT + UPDATE（需嵌入）
    to_delete: dict[str, list[str]] = {}     # doc_id → 需删除的 chunk_id 列表
    skipped_count = 0

    for doc_id, doc_chunks in by_doc.items():
        old_hashes = await get_chunk_hashes_by_doc_id(doc_id, collection_name=collection_name)

        # 计算新 chunk 的 MD5
        new_hashes: dict[str, str] = {}
        for c in doc_chunks:
            new_hashes[c.chunk_id] = hashlib.md5(c.text.encode("utf-8")).hexdigest()

        new_ids = set(new_hashes.keys())
        old_ids = set(old_hashes.keys())

        for c in doc_chunks:
            if c.chunk_id not in old_ids:
                to_embed.append(c)                                    # 新 chunk → INSERT
            elif old_hashes[c.chunk_id] != new_hashes[c.chunk_id]:
                to_embed.append(c)                                    # 内容变更 → UPDATE
            else:
                skipped_count += 1                                    # 未变化 → SKIP

        # 旧集合有但新集合没有 → DELETE
        removed_ids = old_ids - new_ids
        if removed_ids:
            to_delete[doc_id] = list(removed_ids)

    logger.info(
        f"[Indexer] 增量索引：{len(chunks)} 个 chunk → "
        f"嵌入 {len(to_embed)} (新增/变更), "
        f"跳过 {skipped_count} (无变化), "
        f"删除 {sum(len(v) for v in to_delete.values())} (已移除)"
    )

    # ---- Phase 2a: 父块写入（无嵌入，仅存储文本） ----
    parents_to_embed = [c for c in to_embed if c.is_parent]
    children_to_embed = [c for c in to_embed if not c.is_parent]

    if parents_to_embed:
        logger.info(f"[Indexer] 写入 {len(parents_to_embed)} 个父块（无嵌入）...")
        parent_batches = list(range(0, len(parents_to_embed), effective_batch_size))
        for batch_num, i in enumerate(parent_batches, start=1):
            batch = parents_to_embed[i : i + effective_batch_size]
            batch_hashes = [
                hashlib.md5(c.text.encode("utf-8")).hexdigest()
                for c in batch
            ]
            await upsert_documents(
                ids=[c.chunk_id for c in batch],
                documents=[c.text for c in batch],
                embeddings=[None] * len(batch),  # 父块不嵌入
                metadatas=[
                    {
                        "doc_id": c.doc_id,
                        "source": c.source_path,
                        "page": str(c.page or ""),
                        "section": c.section or "",
                        "user_id": user_id or "",
                        "content_hash": batch_hashes[idx],
                        "parent_chunk_id": c.parent_chunk_id or "",
                        "is_parent": True,
                        **c.metadata,
                    }
                    for idx, c in enumerate(batch)
                ],
                collection_name=collection_name,
            )

    # ---- Phase 2b: 子块嵌入 + upsert ----
    total = 0
    batches = list(range(0, len(children_to_embed), effective_batch_size))
    total_batches = len(batches)

    for batch_num, i in enumerate(batches, start=1):
        batch = children_to_embed[i : i + effective_batch_size]
        if not batch:
            continue
        logger.info(
            f"[Indexer] 正在 embedding 第 {i+1}-{i+len(batch)}/{len(children_to_embed)} 块..."
        )
        embeddings = await _embed_batch([c.text for c in batch])

        # 校验嵌入结果：跳过空向量（Embedding API 失败时不应继续写入）
        valid_pairs = [(c, emb) for c, emb in zip(batch, embeddings) if emb and len(emb) > 0]
        if not valid_pairs:
            logger.error(
                f"[Indexer] Embedding API 返回空向量，跳过批次 "
                f"({i + 1}-{i + len(batch)}/{len(children_to_embed)})"
            )
            continue
        if len(valid_pairs) < len(batch):
            logger.warning(
                f"[Indexer] {len(batch) - len(valid_pairs)}/{len(batch)} 个 chunk 嵌入为空，已过滤"
            )
        valid_batch = [c for c, _ in valid_pairs]
        valid_embeddings = [emb for _, emb in valid_pairs]

        # 在嵌入阶段计算 content_hash，随 metadata 写入
        batch_hashes = [
            hashlib.md5(c.text.encode("utf-8")).hexdigest()
            for c in valid_batch
        ]

        await upsert_documents(
            ids=[c.chunk_id for c in valid_batch],
            documents=[c.text for c in valid_batch],
            embeddings=valid_embeddings,
            metadatas=[
                {
                    "doc_id": c.doc_id,
                    "source": c.source_path,
                    "page": str(c.page or ""),
                    "section": c.section or "",
                    "user_id": user_id or "",
                    "content_hash": batch_hashes[idx],
                    "parent_chunk_id": c.parent_chunk_id or "",
                    "is_parent": False,
                    **c.metadata,
                }
                for idx, c in enumerate(valid_batch)
            ],
            collection_name=collection_name,
        )
        total += len(valid_batch)
        if progress_callback is not None:
            progress_callback(batch_num, total_batches)

    # ---- Phase 3: 删除已移除的 chunk ----
    for doc_id, delete_chunk_ids in to_delete.items():
        try:
            await delete_documents(delete_chunk_ids, collection_name=collection_name)
            logger.info(f"[Indexer] 已删除 doc_id={doc_id} 的 {len(delete_chunk_ids)} 个过期 chunk")
        except Exception as e:
            logger.warning(f"[Indexer] 删除过期 chunk 失败 doc_id={doc_id}: {e}")

    if total == 0 and not to_delete:
        logger.info(f"[Indexer] 增量索引完成：所有 {len(chunks)} 个 chunk 无变化，零 API 调用")
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
