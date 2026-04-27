"""
backend/services/kg_builder.py
知识图谱自动构建服务：从 ChromaDB 文本块中提取知识点和关系，写入 KGNode + KGEdge。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import defaultdict
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete as sa_delete

from backend.db.models import KGEdge, KGNode
from backend.db.vector import get_documents_by_doc_id
from backend.models.schemas import KGNodeType, KGRelation
from backend.services.llm import chat_completion

logger = logging.getLogger(__name__)

# ----------------------------------------------------------
# Prompts
# ----------------------------------------------------------

NODE_EXTRACT_PROMPT = """你是一位知识图谱构建专家。请从以下教材文本中提取知识点节点。

要求：
- 提取所有出现的知识概念，按层级分类
- type 必须是以下之一：Course, Chapter, KnowledgePoint, SubPoint, Concept
- 每个节点包含 name（简短名称）、type、description（一句话描述）
- 返回 JSON 数组格式

文本内容：
{text}

请返回 JSON 数组，格式如下（只返回 JSON，不要其他内容）：
[{{"name": "...", "type": "...", "description": "..."}}]"""

EDGE_EXTRACT_PROMPT = """你是一位知识图谱构建专家。请根据以下知识点列表，推断它们之间的关系。

知识点列表：
{nodes_text}

关系类型说明：
- IS_PART_OF: A 是 B 的组成部分（章节属于课程，知识点属于章节）
- REQUIRES: A 的学习需要先掌握 B（前置依赖）
- RELATED_TO: A 和 B 有关联但无层级或依赖关系
- CONTAINS: A 包含 B（与 IS_PART_OF 方向相反）

要求：
- source 和 target 必须是上面列表中的知识点名称（精确匹配）
- relation 必须是 IS_PART_OF / REQUIRES / RELATED_TO / CONTAINS 之一
- 只返回 JSON 数组

请返回 JSON 数组：
[{{"source": "...", "target": "...", "relation": "..."}}]"""


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def _make_node_id(name: str) -> str:
    """生成节点 ID：kp_{hash(name)[:8]}"""
    h = hashlib.md5(name.encode()).hexdigest()[:8]
    return f"kp_{h}"


def _parse_json_response(raw: str) -> list[dict]:
    """解析 LLM 返回的 JSON（处理 markdown 代码块包裹）。"""
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return json.loads(cleaned)


def _group_by_page(documents: list[str], metadatas: list[dict]) -> list[str]:
    """按 page 元数据聚合文本块，返回聚合后的文本列表。"""
    page_groups: dict[int, list[str]] = defaultdict(list)
    for doc, meta in zip(documents, metadatas):
        page = meta.get("page", 0)
        page_groups[page].append(doc)

    grouped = []
    sorted_pages = sorted(page_groups.keys())
    batch: list[str] = []
    batch_len = 0
    for page in sorted_pages:
        page_text = "\n".join(page_groups[page])
        batch.append(page_text)
        batch_len += len(page_text)
        if batch_len > 12000:  # ~12000 字符一批（约 8-10 页）
            grouped.append("\n\n".join(batch))
            batch = []
            batch_len = 0
    if batch:
        grouped.append("\n\n".join(batch))

    # 如果批次仍然过多，均匀采样控制在 30 批以内
    MAX_BATCHES = 30
    if len(grouped) > MAX_BATCHES:
        step = len(grouped) / MAX_BATCHES
        sampled = [grouped[int(i * step)] for i in range(MAX_BATCHES)]
        print(f"[KG] 批次过多({len(grouped)})，采样为 {len(sampled)} 批")
        grouped = sampled

    return grouped


# ----------------------------------------------------------
# 核心提取逻辑
# ----------------------------------------------------------

# 并发控制：最多同时 5 个 LLM 请求，避免 API 限流
_LLM_SEMAPHORE = asyncio.Semaphore(5)


async def _extract_single_batch(i: int, text: str, total: int) -> list[dict]:
    """单个 batch 的节点提取（供并发调用）。"""
    prompt = NODE_EXTRACT_PROMPT.format(text=text[:6000])
    async with _LLM_SEMAPHORE:
        print(f"[KG] 提取节点 batch {i+1}/{total} (开始)")
        try:
            raw = await chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
            nodes = _parse_json_response(raw)
            valid_nodes = []
            for node in nodes:
                name = node.get("name", "").strip()
                if not name:
                    continue
                node_type = node.get("type", "Concept")
                if node_type not in [e.value for e in KGNodeType]:
                    node_type = "Concept"
                valid_nodes.append({
                    "name": name,
                    "type": node_type,
                    "description": node.get("description", ""),
                })
            print(f"[KG] 提取节点 batch {i+1}/{total} 完成，得到 {len(valid_nodes)} 个节点")
            return valid_nodes
        except Exception as e:
            print(f"[KG] 节点提取 batch {i+1} 失败: {e}")
            return []


async def _extract_nodes(grouped_texts: list[str]) -> list[dict]:
    """并发调用 LLM 提取知识点节点，完成后统一去重。"""
    total = len(grouped_texts)
    tasks = [
        _extract_single_batch(i, text, total)
        for i, text in enumerate(grouped_texts)
    ]

    # 并发执行所有 batch
    results = await asyncio.gather(*tasks)

    # 统一去重：同名节点保留第一个出现的
    all_nodes: dict[str, dict] = {}
    for batch_nodes in results:
        for node in batch_nodes:
            if node["name"] not in all_nodes:
                all_nodes[node["name"]] = node

    print(f"[KG] 全部 batch 完成，去重后共 {len(all_nodes)} 个节点")
    return list(all_nodes.values())


async def _extract_edges_batch(
    batch_nodes: list[dict],
    all_node_names: set[str],
    batch_idx: int,
    total: int,
) -> list[dict]:
    """单批关系推断（供并发调用）。"""
    nodes_text = "\n".join(
        f"- {n['name']}（{n['type']}）: {n.get('description', '')}"
        for n in batch_nodes
    )
    prompt = EDGE_EXTRACT_PROMPT.format(nodes_text=nodes_text)
    async with _LLM_SEMAPHORE:
        print(f"[KG] 推断关系 batch {batch_idx+1}/{total} (开始，{len(batch_nodes)} 个节点)")
        try:
            raw = await chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
            edges = _parse_json_response(raw)
            valid_relations = {e.value for e in KGRelation}
            valid_edges = []
            for edge in edges:
                src = edge.get("source", "").strip()
                tgt = edge.get("target", "").strip()
                rel = edge.get("relation", "").strip()
                if src in all_node_names and tgt in all_node_names and rel in valid_relations and src != tgt:
                    valid_edges.append({"source": src, "target": tgt, "relation": rel})
            print(f"[KG] 推断关系 batch {batch_idx+1}/{total} 完成，得到 {len(valid_edges)} 条")
            return valid_edges
        except Exception as e:
            print(f"[KG] 关系推断 batch {batch_idx+1} 失败: {e}")
            return []


async def _extract_edges(all_nodes: list[dict]) -> list[dict]:
    """将节点分批并发调用 LLM 推断关系，完成后统一去重。"""
    if len(all_nodes) < 2:
        return []

    all_node_names = {n["name"] for n in all_nodes}

    # 每批 ~40 个节点，相邻 batch 重叠 10 个，捕获边界处的关系
    BATCH_SIZE = 40
    OVERLAP = 10
    batches = []
    i = 0
    while i < len(all_nodes):
        batches.append(all_nodes[i:i + BATCH_SIZE])
        i += BATCH_SIZE - OVERLAP  # 步长 = BATCH_SIZE - OVERLAP
    total = len(batches)
    print(f"[KG] 关系推断分为 {total} 批（每批 ~{BATCH_SIZE} 节点，重叠 {OVERLAP}）")

    tasks = [
        _extract_edges_batch(batch, all_node_names, i, total)
        for i, batch in enumerate(batches)
    ]
    results = await asyncio.gather(*tasks)

    # 合并去重：(source, target, relation) 三元组去重
    seen: set[tuple[str, str, str]] = set()
    unique_edges = []
    for batch_edges in results:
        for edge in batch_edges:
            key = (edge["source"], edge["target"], edge["relation"])
            if key not in seen:
                seen.add(key)
                unique_edges.append(edge)

    print(f"[KG] 全部关系推断完成，去重后共 {len(unique_edges)} 条")
    return unique_edges


# ----------------------------------------------------------
# 主入口
# ----------------------------------------------------------

async def build_kg(doc_id: str, db: AsyncSession) -> dict[str, Any]:
    """
    从已导入文档构建知识图谱。

    流程：ChromaDB 取文本 → 聚合 → 提取节点 → 推断关系 → 写 DB
    返回 {"nodes_count": int, "edges_count": int, "doc_id": str}
    """
    # 1. 从 ChromaDB 获取文本块
    print(f"[KG] 开始构建知识图谱，doc_id={doc_id}")
    result = get_documents_by_doc_id(doc_id)
    documents = result.get("documents", [])
    metadatas = result.get("metadatas", [])

    if not documents:
        raise ValueError(f"文档 {doc_id} 在向量库中未找到文本块")

    print(f"[KG] doc_id={doc_id}, 共 {len(documents)} 个文本块")

    # 2. 按页聚合
    grouped = _group_by_page(documents, metadatas)
    print(f"[KG] 聚合为 {len(grouped)} 批")

    # 3. 提取节点
    nodes = await _extract_nodes(grouped)
    print(f"[KG] 提取到 {len(nodes)} 个节点")

    if not nodes:
        return {"nodes_count": 0, "edges_count": 0, "doc_id": doc_id}

    # 4. 推断关系
    edges = await _extract_edges(nodes)
    print(f"[KG] 推断出 {len(edges)} 条关系")

    # 5. 清除该 doc 关联的旧数据
    #    先查出该 course_id 下所有旧节点 ID，再删相关边和节点
    from sqlalchemy import select as sa_select
    old_node_ids_result = await db.execute(
        sa_select(KGNode.id).where(KGNode.course_id == doc_id)
    )
    old_node_ids = [row[0] for row in old_node_ids_result.fetchall()]
    if old_node_ids:
        await db.execute(
            sa_delete(KGEdge).where(
                KGEdge.source_id.in_(old_node_ids) | KGEdge.target_id.in_(old_node_ids)
            )
        )
        await db.execute(
            sa_delete(KGNode).where(KGNode.course_id == doc_id)
        )
    await db.flush()

    # 6. 写入节点
    name_to_id: dict[str, str] = {}
    for node in nodes:
        node_id = _make_node_id(node["name"])
        name_to_id[node["name"]] = node_id
        db.add(KGNode(
            id=node_id,
            name=node["name"],
            node_type=node["type"],
            description=node.get("description"),
            course_id=doc_id,
        ))
    await db.flush()

    # 7. 写入边
    edge_count = 0
    for edge in edges:
        src_id = name_to_id.get(edge["source"])
        tgt_id = name_to_id.get(edge["target"])
        if src_id and tgt_id:
            db.add(KGEdge(
                source_id=src_id,
                target_id=tgt_id,
                relation=edge["relation"],
            ))
            edge_count += 1
    await db.commit()

    logger.info(f"[KG] 构建完成: {len(nodes)} 节点, {edge_count} 边")
    return {
        "nodes_count": len(nodes),
        "edges_count": edge_count,
        "doc_id": doc_id,
    }
