"""
backend/rag/retriever.py
RAG 检索器：给定用户问题，返回相关文本块及其来源引用。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

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


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def retrieve(
    query: str,
    n_results: int = 5,
    score_threshold: float = 0.5,
    where: Optional[dict] = None,
    collection_name: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    语义检索：将 query 嵌入后查询向量库，过滤低相似度结果。
    向量库未初始化或为空时返回空列表（优雅降级）。
    """
    try:
        from backend.db.vector import get_collection
        col = get_collection()
        if col.count() == 0:
            return []
    except Exception:
        return []

    embedding = await get_embedding(query)
    if not embedding:
        return []
    raw = query_documents(
        query_embedding=embedding,
        n_results=n_results,
        where=where,
        collection_name=collection_name,
    )
    return _parse_results(raw, score_threshold)


async def retrieve_by_kp(
    kp_name: str,
    n_results: int = 8,
    collection_name: Optional[str] = None,
) -> list[RetrievedChunk]:
    """
    按知识点名称检索相关文档片段。
    在 query 中加入 "知识点：" 前缀以提升检索精度。
    """
    return await retrieve(
        query=f"知识点：{kp_name}",
        n_results=n_results,
        collection_name=collection_name,
    )


def format_context(chunks: list[RetrievedChunk], max_tokens: int = 3000) -> str:
    """
    将检索结果格式化为 LLM prompt 上下文字符串，附带来源引用编号。
    超过 max_tokens 估算时截断。

    格式示例：
    [1] （来源：chapter_01.pdf, 第2页）
    梯度下降是一种...

    [2] （来源：notes.md, 第一章）
    反向传播算法...
    """
    parts: list[str] = []
    total_chars = 0
    for i, chunk in enumerate(chunks, 1):
        source_info = f"来源：{chunk.source}"
        if chunk.page:
            source_info += f"，第 {chunk.page} 页"
        if chunk.section:
            source_info += f"，{chunk.section}"
        entry = f"[{i}] （{source_info}）\n{chunk.text}"
        if total_chars + len(entry) > max_tokens * 2:  # 粗略字符估算
            break
        parts.append(entry)
        total_chars += len(entry)
    return "\n\n".join(parts)


# ----------------------------------------------------------
# 内部辅助
# ----------------------------------------------------------

def _parse_results(raw: dict, score_threshold: float) -> list[RetrievedChunk]:
    """将 ChromaDB QueryResult 转换为 RetrievedChunk 列表并过滤。"""
    chunks: list[RetrievedChunk] = []
    ids = (raw.get("ids") or [[]])[0]
    documents = (raw.get("documents") or [[]])[0]
    distances = (raw.get("distances") or [[]])[0]
    metadatas = (raw.get("metadatas") or [[]])[0]
    for cid, doc, dist, meta in zip(ids, documents, distances, metadatas):
        # ChromaDB cosine distance → similarity: score = 1 - distance
        score = 1.0 - float(dist)
        if score < score_threshold:
            continue
        chunks.append(
            RetrievedChunk(
                chunk_id=cid,
                text=doc,
                score=score,
                doc_id=meta.get("doc_id", ""),
                source=meta.get("source", ""),
                page=int(meta["page"]) if meta.get("page") else None,
                section=meta.get("section") or None,
            )
        )
    return sorted(chunks, key=lambda c: c.score, reverse=True)
