"""
backend/rag/retriever.py
RAG 检索器：给定用户问题，返回相关文本块及其来源引用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from loguru import logger  # noqa: F401

from backend.db.vector import query_documents
from backend.services.llm import get_embedding

# ----------------------------------------------------------
# 数据结构
# ----------------------------------------------------------

@dataclass
class RetrievedChunk:
    """检索到的单个文本块及相关信息。"""
    chunk_id: str
    text: str
    score: float        # 相似度得分（越高越相关）
    doc_id: str
    source: str         # 原始文件路径
    page: Optional[int] = None
    section: Optional[str] = None
    metadata: dict = field(default_factory=dict)  # 扩展元数据（JSONB，如 language、chunk_type 等）


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def retrieve(
    query: str,
    n_results: int | None = None,
    score_threshold: float | None = None,
    where: Optional[dict] = None,
    collection_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    语义检索：将 query 嵌入后查询向量库，过滤低相似度结果。
    向量库未初始化或为空时返回空列表（优雅降级）。
    """
    try:
        from backend.db.vector import get_collection
        col = get_collection()
        doc_count = await col.count()
        if doc_count == 0:
            logger.warning("[RAG] 向量库为空（0 条文档），RAG 降级为纯 LLM 生成。请运行 python -m backend.rag.indexer 导入文档。")
            return []
        logger.info(f"[RAG] 向量库就绪，共 {doc_count} 条文档，开始检索: query={query[:60]!r}")
    except Exception as e:
        logger.warning(f"[RAG] 向量库未初始化或不可用: {e}，RAG 降级为纯 LLM 生成。")
        return []

    from backend.config import config as _cfg
    _n_results = n_results if n_results is not None else _cfg.rag.n_results
    _score_threshold = score_threshold if score_threshold is not None else _cfg.rag.score_threshold

    embedding = await get_embedding(query)
    if not embedding:
        logger.warning("[RAG] Embedding 返回空向量，无法执行语义检索。请检查 embedding 模型/API 配置。")
        return []

    # 构建用户隔离过滤条件
    effective_where = where
    if user_id:
        user_filter = {"$or": [
            {"user_id": user_id},
            {"user_id": ""},
        ]}
        if effective_where:
            effective_where = {"$and": [effective_where, user_filter]}
        else:
            effective_where = user_filter

    # 预取更多候选（3x），用于后续 re-rank 精排
    prefetch_count = max(_n_results * 3, 15)
    raw = await query_documents(
        query_embedding=embedding,
        n_results=prefetch_count,
        where=effective_where,
        collection_name=collection_name,
    )
    chunks = _parse_results(raw, _score_threshold)

    # Re-rank: 对 cosine 结果做关键词重叠加权重排
    if chunks:
        chunks = _rerank_by_keyword_overlap(query, chunks)

        # 父块回填：子块 → 父块映射 + 去重（parent_chunking 启用时生效）
        chunks = await _resolve_parent_chunks(chunks)
        chunks = chunks[:_n_results]

    if not chunks:
        logger.info(f"[RAG] 检索无结果（threshold={_score_threshold}），query={query[:60]!r}，将由 LLM 纯生成")
    else:
        logger.info(f"[RAG] 检索到 {len(chunks)} 条相关文档，最高分={chunks[0].score:.3f}，最低分={chunks[-1].score:.3f}")
    return chunks


async def retrieve_by_kp(
    kp_name: str,
    n_results: int | None = None,
    collection_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    按知识点名称检索相关文档片段。
    使用多角度查询扩展以提升检索覆盖率和精度（固定模板方案，Query Rewrite 未启用时使用）。
    """
    query = f"知识点：{kp_name}；定义：{kp_name}；{kp_name}的核心概念与原理"
    return await retrieve(
        query=query,
        n_results=n_results,
        collection_name=collection_name,
        user_id=user_id,
    )


async def retrieve_with_queries(
    queries: list[str],
    n_results: int | None = None,
    score_threshold: float | None = None,
    collection_name: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[list[RetrievedChunk]]:
    """
    使用多条查询分别检索，返回各查询的结果列表（供 RRF 融合使用）。

    :param queries:        查询字符串列表
    :param n_results:      每条查询的返回条数
    :param score_threshold: 最低相似度阈值
    :param collection_name: 集合名
    :param user_id:        用户 ID（用于隔离）
    :return:               每条查询的 RetrievedChunk 列表
    """
    import asyncio

    async def _fetch_one(query: str) -> list[RetrievedChunk]:
        try:
            return await retrieve(
                query=query,
                n_results=n_results,
                score_threshold=score_threshold,
                collection_name=collection_name,
                user_id=user_id,
            )
        except Exception as e:
            logger.warning(f"[RAG] 子查询检索失败: {query[:40]!r}: {e}")
            return []

    # 并发执行所有子查询的检索
    tasks = [_fetch_one(q) for q in queries]
    results = await asyncio.gather(*tasks)
    return list(results)


def format_context(chunks: list[RetrievedChunk], max_tokens: int | None = None) -> str:
    """
    将检索结果格式化为 LLM prompt 上下文字符串，附带来源引用编号。
    超过 max_tokens 估算时截断。

    格式示例：
    [1] （来源：chapter_01.pdf, 第2页）
    梯度下降是一种...

    [2] （来源：notes.md, 第一章）
    反向传播算法...
    """
    from backend.config import config as _cfg
    _max_tokens = max_tokens if max_tokens is not None else _cfg.rag.context_max_tokens

    if not chunks:
        logger.warning("[RAG] format_context 收到空 chunks，LLM 将在无参考资料的情况下生成内容。")
        return "（暂无参考资料）"
    parts: list[str] = []
    estimated_tokens = 0
    for i, chunk in enumerate(chunks, 1):
        source_info = f"来源：{chunk.source}"
        if chunk.page:
            source_info += f"，第 {chunk.page} 页"
        if chunk.section:
            source_info += f"，{chunk.section}"
        # 附加扩展元数据（若有）
        extra_info_parts = []
        if chunk.metadata.get("chunk_type"):
            type_labels = {"definition": "定义", "theorem": "定理", "example": "示例",
                          "exercise": "习题", "summary": "总结"}
            ct = chunk.metadata["chunk_type"]
            extra_info_parts.append(type_labels.get(ct, ct))
        if chunk.metadata.get("language"):
            lang_labels = {"zh": "中文", "en": "英文", "mixed": "中英混合"}
            lang = chunk.metadata["language"]
            extra_info_parts.append(lang_labels.get(lang, lang))
        if chunk.metadata.get("difficulty"):
            diff_labels = {"beginner": "入门", "intermediate": "进阶", "advanced": "高级"}
            diff = chunk.metadata["difficulty"]
            extra_info_parts.append(diff_labels.get(diff, diff))
        if extra_info_parts:
            source_info += " [" + ", ".join(extra_info_parts) + "]"
        entry = f"[{i}] （{source_info}）\n{chunk.text}"
        entry_tokens = _estimate_tokens(entry)
        if estimated_tokens + entry_tokens > _max_tokens:
            break
        parts.append(entry)
        estimated_tokens += entry_tokens
    return "\n\n".join(parts)


# ----------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------

def _estimate_tokens(text: str) -> int:
    """按语言比例估算 token 数。中文 ~1.5 chars/token，英文 ~4 chars/token。"""
    import re
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    en_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + en_chars / 4.0)


async def _resolve_parent_chunks(
    chunks: list[RetrievedChunk],
) -> list[RetrievedChunk]:
    """
    将子块检索结果映射到父块文本，按父块去重。

    对于有 parent_chunk_id 的子块，查询父块文本并以父块文本替代子块文本，
    同时保留子块的检索分数。同一父块的多个子块只返回分数最高的那一个。

    对于无 parent_chunk_id 的子块（旧数据或 parent_chunking 未启用），
    直接保留原始子块。

    :param chunks: re-rank 后的子块列表（已按分数降序）
    :return:       父块回填 + 去重后的列表
    """
    # 收集需要查询的 parent_chunk_id（去重）
    parent_ids: list[str] = []
    child_to_parent: dict[str, str] = {}  # child_chunk_id → parent_chunk_id
    seen_parents: set[str] = set()

    for c in chunks:
        pid = c.metadata.get("parent_chunk_id", "")
        if pid:
            child_to_parent[c.chunk_id] = pid

    if not child_to_parent:
        return chunks  # 无父子关系，直接返回

    # 批量查询父块文本
    parent_ids = list(set(child_to_parent.values()))
    parent_texts = await _get_parent_texts_batch(parent_ids)

    # 去重 + 回填
    resolved: list[RetrievedChunk] = []
    for c in chunks:
        pid = child_to_parent.get(c.chunk_id, "")
        if pid:
            if pid in seen_parents:
                continue  # 去重：同一父块只保留第一个（分数最高）
            seen_parents.add(pid)

            parent_text = parent_texts.get(pid)
            if parent_text:
                # 用父块文本替代子块文本，保留子块的分数和来源信息
                resolved.append(RetrievedChunk(
                    chunk_id=pid,
                    text=parent_text,
                    score=c.score,
                    doc_id=c.doc_id,
                    source=c.source,
                    page=c.page,
                    section=c.section,
                    metadata={
                        **c.metadata,
                        "from_child_chunk": c.chunk_id,
                    },
                ))
                continue

        # 无父块或父块未找到 → 保留原始子块
        resolved.append(c)

    # 按分数降序
    resolved.sort(key=lambda c: c.score, reverse=True)
    return resolved


async def _get_parent_texts_batch(parent_ids: list[str]) -> dict[str, str]:
    """批量查询父块文本。"""
    try:
        from backend.db.vector import get_parent_texts
        return await get_parent_texts(parent_ids)
    except Exception:
        return {}


def _rerank_by_keyword_overlap(query: str, chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    轻量级 re-rank：基于查询关键词与文档文本的重叠度对 cosine 分加权。
    不引入额外模型依赖，计算成本极低。
    """
    # 提取查询关键词（2字及以上中文字 + 3字及以上英文词）
    import re
    keywords = set(re.findall(r'[\u4e00-\u9fff]{2,}', query))
    keywords |= set(w.lower() for w in re.findall(r'[a-zA-Z]{2,}', query))

    if not keywords:
        return sorted(chunks, key=lambda c: c.score, reverse=True)

    for chunk in chunks:
        text_lower = chunk.text.lower()
        overlap = sum(1 for kw in keywords if kw in text_lower)
        # 关键词重叠加分：最高 +0.15
        boost = min(overlap / max(len(keywords), 1), 1.0) * 0.15
        chunk.score = round(chunk.score + boost, 4)

    return sorted(chunks, key=lambda c: c.score, reverse=True)


def _parse_results(raw: dict, score_threshold: float) -> list[RetrievedChunk]:
    """将 QueryResult 转换为 RetrievedChunk 列表并过滤。"""
    chunks: list[RetrievedChunk] = []
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    for cid, doc, dist, meta in zip(ids, documents, distances, metadatas):
        # cosine distance → similarity: score = 1 - distance
        score = 1.0 - float(dist)
        if score < score_threshold:
            continue
        # 提取固定字段以外的扩展元数据
        fixed_keys = {"doc_id", "source", "page", "section", "user_id"}
        extra_meta = {k: v for k, v in meta.items() if k not in fixed_keys}
        chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                text=doc,
                score=score,
                doc_id=meta.get("doc_id", ""),
                source=meta.get("source", ""),
                page=int(meta["page"]) if meta.get("page") else None,
                section=meta.get("section") or None,
                metadata=extra_meta,
            )
        )
    return sorted(chunks, key=lambda c: c.score, reverse=True)
