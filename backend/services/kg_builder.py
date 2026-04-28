"""
backend/services/kg_builder.py
知识图谱自动构建服务：从 ChromaDB 文本块中提取知识点和关系，写入 KGNode + KGEdge。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
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
- type 必须是以下之一：Chapter, KnowledgePoint, SubPoint, Concept（不要使用 Course）
- 节点命名规则：
  - 必须去除章节编号（如"第7章"、"7.1"、"10.1.2"等前缀），只保留纯粹的知识点名称
  - 示例："10.1 注意力机制" → "注意力机制"，"第3章 线性回归" → "线性回归"，"7.1.2 小批量随机梯度下降" → "小批量随机梯度下降"
- 每个节点包含 name（简短名称，无编号）、type、description（一句话描述）
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

# ---------- TOC 路径专用 Prompt ----------

# TOC level → 节点类型映射（完整）
_LEVEL_TYPE_MAP = {1: "Chapter", 2: "KnowledgePoint", 3: "SubPoint", 4: "Concept"}
# 所有可用类型（按层级从高到低）
_ALL_TYPES = ["Chapter", "KnowledgePoint", "SubPoint", "Concept"]


def _get_llm_types(toc_max_level: int) -> list[str]:
    """根据 TOC 已覆盖的最大 level，返回 LLM 需要提取的类型列表。"""
    # TOC 覆盖了 level 1..toc_max_level，LLM 负责剩余的
    covered = set(_LEVEL_TYPE_MAP.get(l, "") for l in range(1, toc_max_level + 1))
    return [t for t in _ALL_TYPES if t not in covered]


def _build_toc_node_prompt(section_name: str, text: str, llm_types: list[str]) -> str:
    """动态生成 TOC 路径的节点提取 prompt。"""
    covered = [t for t in _ALL_TYPES if t not in llm_types]
    covered_str = " / ".join(covered)
    types_desc = {
        "Chapter": "Chapter：章级别的知识主题",
        "KnowledgePoint": "KnowledgePoint：节级别的知识点",
        "SubPoint": "SubPoint：小节级别的知识点",
        "Concept": "Concept：具体概念、术语、公式、算法等",
    }
    type_lines = "\n".join(f"- {types_desc[t]}" for t in llm_types)
    return f"""你是一位知识图谱构建专家。以下文本来自教材章节「{section_name}」。
层级结构（{covered_str}）已从目录自动提取，无需你再提取。

请提取该章节内的知识点，type 只能是以下类型：
{type_lines}
- 节点命名去除编号前缀，只保留纯粹名称

文本内容：
{text}

请返回 JSON 数组（只返回 JSON，不要其他内容）：
[{{"name": "...", "type": "...", "description": "..."}}]"""

EDGE_EXTRACT_CROSS_PROMPT = """你是一位知识图谱构建专家。以下知识点来自不同章节，层级关系（IS_PART_OF / CONTAINS）已自动生成。

请只推断以下两种跨章节关系：
- REQUIRES: A 的学习需要先掌握 B（前置依赖）
- RELATED_TO: A 和 B 有关联但无层级或依赖关系

知识点列表：
{nodes_text}

要求：
- source 和 target 必须是上面列表中的知识点名称（精确匹配）
- relation 只能是 REQUIRES 或 RELATED_TO
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


def _clean_node_name(name: str) -> str:
    """去除章节编号前缀，只保留纯粹的知识点名称。"""
    name = re.sub(r'^第[一二三四五六七八九十百\d]+[章节篇]\s*', '', name)
    name = re.sub(r'^[\d.]+\s*', '', name)
    return name.strip()


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
        try:
            page = int(meta.get("page", 0))
        except (ValueError, TypeError):
            page = 0
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


_TOC_MAX_ITEMS = 100  # 目录项数量阈值，超过则裁剪深层级


def _trim_toc_by_level(toc: list[dict]) -> list[dict]:
    """
    逐级审查目录项数量，找到不超过阈值的最大 level 截止。
    例如 level<=3 有 90 项，level<=4 有 800+ 项，则截止到 level 3。
    """
    if len(toc) <= _TOC_MAX_ITEMS:
        return toc

    max_level = max(item["level"] for item in toc)
    for cutoff in range(1, max_level + 1):
        count = sum(1 for item in toc if item["level"] <= cutoff)
        if count > _TOC_MAX_ITEMS:
            # 回退到上一级
            final_level = max(cutoff - 1, 1)
            trimmed = [item for item in toc if item["level"] <= final_level]
            print(f"[KG-TOC] 目录项 {len(toc)} 个超过阈值 {_TOC_MAX_ITEMS}，截止到 level {final_level}（{len(trimmed)} 项）")
            return trimmed

    return toc


def _build_toc_skeleton(toc: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    从目录构建骨架节点和层级边。

    - level 1 → Chapter
    - level 2 → KnowledgePoint
    - level 3+ → SubPoint
    - 自动创建父子 IS_PART_OF 边

    返回 (nodes, edges)
    """
    TYPE_MAP = {1: "Chapter", 2: "KnowledgePoint"}
    nodes: list[dict] = []
    edges: list[dict] = []
    # 栈：[(level, node_name)]，追踪父节点
    stack: list[tuple[int, str]] = []

    for item in toc:
        name = _clean_node_name(item["title"])
        if not name:
            continue
        level = item["level"]
        node_type = TYPE_MAP.get(level, "SubPoint")
        nodes.append({"name": name, "type": node_type, "description": ""})

        # 弹出栈中 level >= 当前的项，找到父节点
        while stack and stack[-1][0] >= level:
            stack.pop()
        if stack:
            parent_name = stack[-1][1]
            edges.append({"source": name, "target": parent_name, "relation": "IS_PART_OF"})
        stack.append((level, name))

    print(f"[KG-TOC] 骨架：{len(nodes)} 节点, {len(edges)} 条层级边")
    return nodes, edges


def _group_by_toc(
    documents: list[str],
    metadatas: list[dict],
    toc: list[dict],
) -> list[dict]:
    """
    按目录章节的页码范围聚合 chunk。
    返回 [{"section": "注意力机制", "text": "...", "type": "KnowledgePoint"}, ...]
    """
    TYPE_MAP = {1: "Chapter", 2: "KnowledgePoint"}
    # 按 page 排序 toc 项，计算每项的页码范围
    sorted_toc = sorted(toc, key=lambda x: x["page"])
    sections: list[dict] = []

    for i, item in enumerate(sorted_toc):
        start_page = item["page"]
        end_page = sorted_toc[i + 1]["page"] if i + 1 < len(sorted_toc) else 999999
        name = _clean_node_name(item["title"])
        if not name:
            continue
        node_type = TYPE_MAP.get(item["level"], "SubPoint")
        # 收集属于该页码范围的 chunk
        texts = []
        for doc, meta in zip(documents, metadatas):
            try:
                page = int(meta.get("page", 0))
            except (ValueError, TypeError):
                page = 0
            if start_page <= page < end_page:
                texts.append(doc)
        if texts:
            combined = "\n".join(texts)
            sections.append({"section": name, "text": combined, "type": node_type})

    # 合并过短的 section（< 200 字符）到前一个
    merged: list[dict] = []
    for sec in sections:
        if merged and len(sec["text"]) < 200:
            merged[-1]["text"] += "\n" + sec["text"]
        else:
            merged.append(sec)

    print(f"[KG-TOC] 按目录聚合为 {len(merged)} 个章节批次")
    return merged


def _attach_details_to_sections(
    detail_nodes: list[dict],
    section_map: dict[str, str],
) -> list[dict]:
    """
    将细粒度节点自动挂到所属章节（IS_PART_OF 边）。
    section_map: {node_name: section_name}
    """
    edges = []
    for node in detail_nodes:
        parent = section_map.get(node["name"])
        if parent:
            edges.append({"source": node["name"], "target": parent, "relation": "IS_PART_OF"})
    return edges


# ----------------------------------------------------------
# 核心提取逻辑
# ----------------------------------------------------------

# 并发控制：最多同时 10 个 LLM 请求
_LLM_SEMAPHORE = asyncio.Semaphore(10)


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
                name = _clean_node_name(node.get("name", "").strip())
                if not name:
                    continue
                node_type = node.get("type", "Concept")
                # Course 类型由系统自动创建，LLM 不应提取
                if node_type == "Course":
                    node_type = "Chapter"
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
# TOC 路径：带章节上下文的节点提取 & 跨章节关系推断
# ----------------------------------------------------------

async def _extract_toc_batch(
    i: int, section: dict, total: int, llm_types: list[str],
) -> tuple[list[dict], str]:
    """单个章节的细粒度节点提取，返回 (nodes, section_name)。"""
    prompt = _build_toc_node_prompt(
        section_name=section["section"],
        text=section["text"][:6000],
        llm_types=llm_types,
    )
    allowed = set(llm_types)
    async with _LLM_SEMAPHORE:
        print(f"[KG-TOC] 提取细粒度节点 {i+1}/{total}「{section['section']}」")
        try:
            raw = await chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
            nodes = _parse_json_response(raw)
            valid = []
            for n in nodes:
                name = _clean_node_name(n.get("name", "").strip())
                if not name:
                    continue
                ntype = n.get("type", "Concept")
                if ntype not in allowed:
                    ntype = llm_types[-1]  # 默认归到最细粒度
                valid.append({"name": name, "type": ntype, "description": n.get("description", "")})
            print(f"[KG-TOC] 章节「{section['section']}」得到 {len(valid)} 个节点")
            return valid, section["section"]
        except Exception as e:
            print(f"[KG-TOC] 章节「{section['section']}」提取失败: {e}")
            return [], section["section"]


async def _extract_nodes_with_context(
    grouped: list[dict], llm_types: list[str],
) -> tuple[list[dict], dict[str, str]]:
    """
    并发提取各章节的细粒度节点。
    返回 (去重后的节点列表, {node_name: section_name} 映射)
    """
    total = len(grouped)
    tasks = [_extract_toc_batch(i, sec, total, llm_types) for i, sec in enumerate(grouped)]
    results = await asyncio.gather(*tasks)

    all_nodes: dict[str, dict] = {}
    section_map: dict[str, str] = {}  # node_name → section_name
    for batch_nodes, sec_name in results:
        for node in batch_nodes:
            if node["name"] not in all_nodes:
                all_nodes[node["name"]] = node
                section_map[node["name"]] = sec_name

    print(f"[KG-TOC] 细粒度节点去重后共 {len(all_nodes)} 个")
    return list(all_nodes.values()), section_map


async def _extract_cross_edges(all_nodes: list[dict]) -> list[dict]:
    """只推断 REQUIRES / RELATED_TO 跨章节关系。"""
    if len(all_nodes) < 2:
        return []

    all_node_names = {n["name"] for n in all_nodes}
    BATCH_SIZE = 40
    OVERLAP = 10
    batches = []
    i = 0
    while i < len(all_nodes):
        batches.append(all_nodes[i:i + BATCH_SIZE])
        i += BATCH_SIZE - OVERLAP
    total = len(batches)
    print(f"[KG-TOC] 跨章节关系推断分为 {total} 批")

    async def _batch(batch_nodes, idx):
        nodes_text = "\n".join(
            f"- {n['name']}（{n['type']}）: {n.get('description', '')}"
            for n in batch_nodes
        )
        prompt = EDGE_EXTRACT_CROSS_PROMPT.format(nodes_text=nodes_text)
        async with _LLM_SEMAPHORE:
            print(f"[KG-TOC] 跨章节关系 batch {idx+1}/{total}")
            try:
                raw = await chat_completion(
                    [{"role": "user", "content": prompt}],
                    temperature=0.1,
                    max_tokens=4000,
                )
                edges = _parse_json_response(raw)
                valid = []
                for e in edges:
                    src, tgt, rel = e.get("source", "").strip(), e.get("target", "").strip(), e.get("relation", "").strip()
                    if src in all_node_names and tgt in all_node_names and rel in ("REQUIRES", "RELATED_TO") and src != tgt:
                        valid.append({"source": src, "target": tgt, "relation": rel})
                return valid
            except Exception as exc:
                print(f"[KG-TOC] 跨章节关系 batch {idx+1} 失败: {exc}")
                return []

    results = await asyncio.gather(*[_batch(b, i) for i, b in enumerate(batches)])
    seen: set[tuple[str, str, str]] = set()
    unique = []
    for batch_edges in results:
        for e in batch_edges:
            key = (e["source"], e["target"], e["relation"])
            if key not in seen:
                seen.add(key)
                unique.append(e)
    print(f"[KG-TOC] 跨章节关系去重后共 {len(unique)} 条")
    return unique


# ----------------------------------------------------------
# 主入口
# ----------------------------------------------------------

async def build_kg(doc_id: str, db: AsyncSession, on_progress=None) -> dict[str, Any]:
    """
    从已导入文档构建知识图谱。

    流程：ChromaDB 取文本 → 聚合 → 提取节点 → 推断关系 → 写 DB
    :param on_progress: 可选回调 async def(progress: int, stage: str)
    返回 {"nodes_count": int, "edges_count": int, "doc_id": str}
    """
    # 1. 从 ChromaDB 获取文本块
    print(f"[KG] 开始构建知识图谱，doc_id={doc_id}")
    if on_progress:
        await on_progress(5, "文本处理中")
    result = get_documents_by_doc_id(doc_id)
    documents = result.get("documents", [])
    metadatas = result.get("metadatas", [])

    if not documents:
        raise ValueError(f"文档 {doc_id} 在向量库中未找到文本块")

    print(f"[KG] doc_id={doc_id}, 共 {len(documents)} 个文本块")

    # 2. 尝试提取 PDF 目录
    toc = None
    try:
        from backend.db.crud import select_one
        from backend.db.models import ResourceMeta as _RM
        from pathlib import Path as _Path
        doc_resource = await select_one(db, _RM, filters={"kp_id": doc_id})
        if doc_resource and doc_resource.content:
            # content 格式："已导入 PDF：filename.pdf，共 N 个文本块"
            import re as _re
            m = _re.search(r'已导入 PDF：(.+?)，', doc_resource.content)
            if m:
                fname = m.group(1)
                pdf_path = _Path(__file__).parent.parent.parent / "uploaded_docs" / fname
                if pdf_path.exists():
                    from backend.rag.loader import extract_toc
                    toc = extract_toc(str(pdf_path))
                    if toc:
                        toc = _trim_toc_by_level(toc)
    except Exception as e:
        print(f"[KG] 目录提取失败，将使用 fallback: {e}")
        toc = None

    if toc and len(toc) >= 3:
        # ===== TOC 路径 =====
        toc_max_level = max(item["level"] for item in toc)
        llm_types = _get_llm_types(toc_max_level)
        print(f"[KG-TOC] 检测到 {len(toc)} 个目录项（max level={toc_max_level}），LLM 提取类型：{llm_types}")
        if on_progress:
            await on_progress(10, "目录结构解析中")

        skeleton_nodes, skeleton_edges = _build_toc_skeleton(toc)

        if on_progress:
            await on_progress(15, "按章节聚合文本")
        grouped_sections = _group_by_toc(documents, metadatas, toc)

        if on_progress:
            await on_progress(20, "知识点提取中")
        detail_nodes, section_map = await _extract_nodes_with_context(grouped_sections, llm_types)

        # 合并节点（骨架 + 细粒度），骨架优先
        skeleton_names = {n["name"] for n in skeleton_nodes}
        nodes = skeleton_nodes + [dn for dn in detail_nodes if dn["name"] not in skeleton_names]

        # 细粒度节点自动挂到所属章节
        auto_edges = _attach_details_to_sections(detail_nodes, section_map)

        if on_progress:
            await on_progress(55, "跨章节关系推断中")
        cross_edges = await _extract_cross_edges(nodes)

        edges = skeleton_edges + auto_edges + cross_edges
        print(f"[KG-TOC] 总计 {len(nodes)} 节点, {len(edges)} 边（骨架 {len(skeleton_edges)} + 归属 {len(auto_edges)} + 跨章节 {len(cross_edges)}）")
    else:
        # ===== Fallback：原有逻辑 =====
        if toc is not None:
            print(f"[KG] 目录项不足({len(toc)}个)，使用 fallback 逻辑")
        grouped = _group_by_page(documents, metadatas)
        print(f"[KG] 聚合为 {len(grouped)} 批")
        if on_progress:
            await on_progress(10, "文本处理中")

        if on_progress:
            await on_progress(15, "知识点提取中")
        nodes = await _extract_nodes(grouped)
        print(f"[KG] 提取到 {len(nodes)} 个节点")

        if not nodes:
            return {"nodes_count": 0, "edges_count": 0, "doc_id": doc_id}

        if on_progress:
            await on_progress(55, "关系推断中")
        edges = await _extract_edges(nodes)
        print(f"[KG] 推断出 {len(edges)} 条关系")

    if not nodes:
        return {"nodes_count": 0, "edges_count": 0, "doc_id": doc_id}

    # 5. 清除该 doc 关联的旧数据
    if on_progress:
        await on_progress(85, "写入数据库")
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
    edge_count = 0
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

    # 7. 自动创建 Course 根节点 + Chapter → Course 边
    from backend.db.crud import select_one
    from backend.db.models import ResourceMeta
    doc_resource = await select_one(db, ResourceMeta, filters={"kp_id": doc_id})
    course_title = doc_resource.title if doc_resource else doc_id
    course_node_id = f"kp_course_{hashlib.md5(doc_id.encode()).hexdigest()[:8]}"
    db.add(KGNode(
        id=course_node_id,
        name=course_title,
        node_type="Course",
        description=f"课程文档：{course_title}",
        course_id=doc_id,
    ))
    name_to_id[course_title] = course_node_id
    await db.flush()

    # 所有 Chapter 节点 → IS_PART_OF → Course
    for node in nodes:
        if node["type"] == "Chapter":
            node_id = _make_node_id(node["name"])
            db.add(KGEdge(
                source_id=node_id,
                target_id=course_node_id,
                relation="IS_PART_OF",
            ))
            edge_count += 1

    # 8. 写入 LLM 推断的边
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


# ----------------------------------------------------------
# 异步后台任务入口
# ----------------------------------------------------------

async def run_kg_build(task_id, doc_id: str, db: AsyncSession) -> None:
    """后台执行 KG 构建，通过 KGBuildTask 记录进度。"""
    from backend.db.crud import update_by_id
    from backend.db.models import KGBuildTask

    async def on_progress(progress: int, stage: str):
        await update_by_id(db, KGBuildTask, task_id, {
            "status": "running", "progress": progress, "stage": stage,
        })

    try:
        result = await build_kg(doc_id, db, on_progress=on_progress)
        await update_by_id(db, KGBuildTask, task_id, {
            "status": "done",
            "progress": 100,
            "stage": "构建完成",
            "nodes_count": result["nodes_count"],
            "edges_count": result["edges_count"],
        })
    except Exception as e:
        print(f"[KG] 后台构建失败: {e}")
        await update_by_id(db, KGBuildTask, task_id, {
            "status": "failed",
            "progress": 0,
            "stage": "构建失败",
            "error_message": str(e),
        })
