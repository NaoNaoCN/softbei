"""
backend/agents/utils.py
Agent 公共工具函数：RAG 检索 + Query Rewrite（策略A+B+C）。
"""

from __future__ import annotations

from loguru import logger  # noqa: F401

from backend.config import config
from backend.models.schemas import AgentState


async def resolve_kp_name(state: AgentState, config_dict: dict | None = None) -> str:
    """
    从 state.kp_id 解析出知识点名称。

    优先从 DB 查 KGNode.name，查不到则直接用 kp_id 原值
    （对话式生成时 kp_id 本身就是用户输入的名称）。
    """
    kp_id = state.kp_id
    if not kp_id:
        return "未知知识点"
    logger.debug(f"[resolve_kp_name] Resolving kp_name for kp_id = {kp_id}")

    # 如果 kp_id 不像是哈希 ID（不以 kp_ 开头），说明本身就是名称
    if not kp_id.startswith("kp_"):
        return kp_id

    # 尝试从 DB 查名称
    db = None
    if config_dict and "configurable" in config_dict:
        db = config_dict["configurable"].get("db")

    if db:
        try:
            from backend.db.crud import select_one
            from backend.db.models import KGNode
            node = await select_one(db, KGNode, filters={"id": kp_id})
            if node:
                logger.debug(f"[resolve_kp_name] Found kp_name in DB: {node.name}")
                return node.name
            logger.debug(f"[resolve_kp_name] No DB record found for kp_id {kp_id}, using kp_id as name")
        except Exception:
            logger.warning(f"[resolve_kp_name] Error querying DB for kp_id {kp_id}, using kp_id as name")
            pass
    else:
        logger.debug(f"[resolve_kp_name] No DB available in config, using kp_id as name")

    return kp_id


def parse_json_llm_response(raw: str) -> str:
    """
    清洗 LLM 返回的 JSON 字符串：去除 Markdown 代码块包裹（```json ... ```）。

    几乎所有 Agent 在调用 LLM 后都需要这一步才能在 json.loads() 之前
    去掉模型可能添加的代码块标记。
    """
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return cleaned


# ----------------------------------------------------------
# 请求级缓存
# ----------------------------------------------------------

# RAG 检索缓存：同一请求内多个 Agent 检索相同知识点时复用结果
_retrieval_cache: dict[tuple[str, str], tuple[str, list[str]]] = {}


def clear_retrieval_cache() -> None:
    """清除 RAG 检索缓存（每次生成请求开始时调用）。"""
    _retrieval_cache.clear()


# Query Rewrite 改写结果缓存
_rewrite_cache: dict[tuple[str, str], str] = {}


# ----------------------------------------------------------
# Query Rewrite：策略 A（对话去上下文）+ 策略 B（画像感知）
# ----------------------------------------------------------

_REWRITE_PROMPT = """你是一个检索查询优化助手。将学生消息改写为适合向量检索的独立查询。

{decontext_section}
{profile_section}

学生消息：{user_message}
目标知识点：{kp_name}

改写规则：
1. 将"这个"、"上面那个"等指代词替换为具体概念
2. 补全省略的主语和背景信息
3. 保留原始问题中的具体细节（如"怎么推导"、"有什么例子"）
4. 输出 20-80 字的自然语言中文查询
5. 不要输出关键词列表，输出自然语言句子

只返回改写后的查询文本。"""


async def _rewrite_query(
    user_message: str,
    kp_name: str,
    chat_history: list[dict] | None = None,
    profile: object | None = None,
) -> str:
    """
    策略 A+B 合并：利用对话历史和画像改写查询。

    :return: 改写后的检索查询字符串
    """
    cfg = config.rag

    # 对话去上下文化（策略 A）
    decontext_section = ""
    if cfg.query_rewrite_decontextualize and chat_history:
        recent = chat_history[-6:]  # 最近 6 轮
        formatted = "\n".join(
            f"- {m['role']}: {m['content'][:120]}" for m in recent
        )
        decontext_section = f"对话历史（用于指代消解）：\n{formatted}"

    # 画像感知（策略 B）
    profile_section = ""
    if cfg.query_rewrite_profile_aware and profile:
        profile_parts = []
        if getattr(profile, "knowledge_weak", None):
            profile_parts.append(f"薄弱知识点：{', '.join(profile.knowledge_weak[:5])}")
        if getattr(profile, "learning_goal", None):
            profile_parts.append(f"学习目标：{profile.learning_goal}")
        if getattr(profile, "cognitive_style", None):
            profile_parts.append(f"认知风格：{profile.cognitive_style}")
        if profile_parts:
            profile_section = "学生画像（偏向薄弱领域）：\n" + "\n".join(profile_parts)

    # 如果不需要改写，直接返回简单拼接
    if not decontext_section and not profile_section:
        return _build_fallback_query(user_message, kp_name)

    prompt = _REWRITE_PROMPT.format(
        decontext_section=decontext_section,
        profile_section=profile_section,
        user_message=user_message,
        kp_name=kp_name,
    )

    try:
        from backend.services.llm import chat_completion
        rewritten = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=cfg.query_rewrite_temperature,
            max_tokens=cfg.query_rewrite_max_tokens,
        )
        result = rewritten.strip()
        if result:
            logger.info(f"[QueryRewrite] 改写完成: {user_message[:40]!r} → {result[:60]!r}")
            return result
    except Exception as e:
        logger.warning(f"[QueryRewrite] LLM 改写失败: {e}，回退到固定模板")

    return _build_fallback_query(user_message, kp_name)


def _build_fallback_query(user_message: str, kp_name: str) -> str:
    """当 Query Rewrite 不可用或失败时的回退查询。"""
    # 如果用户消息本身已经很精确（短消息 + 包含知识点），直接用消息
    if len(user_message) <= 80 and kp_name in user_message:
        return f"{user_message} 核心概念 原理 示例"
    # 否则拼接消息和知识点
    return f"{kp_name}：{user_message[:120]}"


# ----------------------------------------------------------
# 策略 C：多角度查询扩展
# ----------------------------------------------------------

_EXPAND_PROMPT = """将以下检索查询扩展为 {n} 个不同角度的子查询，用于从知识库中检索学习资料。

原始查询：{query}

生成 {n} 条子查询，每条从不同角度覆盖该知识点：
- 概念定义角度
- 原理/推导角度
- 实际应用/示例角度
- 常见误区角度
- 与其他概念的关联角度

以 JSON 数组返回：["子查询1", "子查询2", "子查询3"]
只返回 JSON 数组，不要包含其他内容。"""


async def _expand_queries(query: str, n: int = 3) -> list[str]:
    """
    策略 C：将改写后的查询扩展为多个不同角度的子查询。

    :return: 子查询字符串列表
    """
    prompt = _EXPAND_PROMPT.format(query=query, n=n)
    try:
        from backend.services.llm import chat_completion
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )
        cleaned = parse_json_llm_response(raw)
        import json
        sub_queries = json.loads(cleaned)
        if isinstance(sub_queries, list) and len(sub_queries) > 0:
            # 将原始查询放在第一位，保证基础覆盖
            all_queries = [query] + [q for q in sub_queries if q != query]
            logger.info(f"[QueryRewrite] 扩展为 {len(all_queries)} 条子查询")
            return all_queries[:n + 1]
    except Exception as e:
        logger.warning(f"[QueryRewrite] 查询扩展失败: {e}")

    return [query]


# ----------------------------------------------------------
# RRF 融合（Reciprocal Rank Fusion）
# ----------------------------------------------------------

def _rrf_fusion(
    query_results: list[list],
    k: int = 60,
) -> list:
    """
    将多条查询的检索结果按 RRF 分数合并去重。

    :param query_results: 每个元素是一条查询的 RetrievedChunk 列表
    :param k:             RRF 平滑参数
    :return:              合并去重后的 RetrievedChunk 列表（按 RRF 分降序）
    """
    from backend.rag.retriever import RetrievedChunk

    # chunk_id → (chunk, rrf_score)
    fused: dict[str, tuple[RetrievedChunk, float]] = {}

    for ranked_list in query_results:
        for rank, chunk in enumerate(ranked_list, 1):
            rrf_score = 1.0 / (k + rank)
            if chunk.chunk_id in fused:
                existing_chunk, existing_score = fused[chunk.chunk_id]
                # 保留更高 cosine 分的 chunk，累加 RRF 分
                if chunk.score > existing_chunk.score:
                    fused[chunk.chunk_id] = (chunk, existing_score + rrf_score)
                else:
                    fused[chunk.chunk_id] = (existing_chunk, existing_score + rrf_score)
            else:
                fused[chunk.chunk_id] = (chunk, rrf_score)

    # 按 RRF 分降序排列
    sorted_results = sorted(fused.values(), key=lambda x: x[1], reverse=True)
    return [chunk for chunk, _ in sorted_results]


# ----------------------------------------------------------
# 核心检索接口（含 Query Rewrite）
# ----------------------------------------------------------

async def retrieve_context(
    state: AgentState,
    agent_label: str = "Agent",
) -> tuple[str, list[str]]:
    """
    RAG 检索并格式化上下文，供各生成 Agent 复用。

    支持 Query Rewrite：
    - 策略 A：利用 chat_history 进行对话去上下文化
    - 策略 B：利用 profile 进行画像感知改写
    - 策略 C：多角度查询扩展 + RRF 融合（可选）

    同一请求内相同 (kp_name, user_id) 只检索一次，后续命中缓存。

    :param state:        AgentState（含 user_message, kp_id, chat_history, profile 等）
    :param agent_label:  Agent 名称标签（用于日志）
    :return:             (context_str, retrieved_texts)
    """
    import time
    from backend.rag.retriever import retrieve, retrieve_by_kp, retrieve_with_queries, format_context

    kp_name = state.kp_id or "未知知识点"
    user_id = str(state.user_id)
    cache_key = (kp_name, user_id)

    # 优先命中缓存
    if cache_key in _retrieval_cache:
        logger.info("[%s] RAG 命中缓存，跳过检索", agent_label)
        return _retrieval_cache[cache_key]

    cfg = config.rag
    t_start = time.perf_counter()

    # ---- Query Rewrite 主逻辑 ----
    if cfg.query_rewrite_enabled:
        # 策略 A+B：改写查询
        rewrite_cache_key = (state.user_message, kp_name)
        if rewrite_cache_key in _rewrite_cache:
            rewritten_query = _rewrite_cache[rewrite_cache_key]
            logger.info("[%s] QueryRewrite 命中缓存", agent_label)
        else:
            rewritten_query = await _rewrite_query(
                user_message=state.user_message,
                kp_name=kp_name,
                chat_history=state.chat_history if cfg.query_rewrite_decontextualize else None,
                profile=state.profile if cfg.query_rewrite_profile_aware else None,
            )
            _rewrite_cache[rewrite_cache_key] = rewritten_query

        # 策略 C：多角度扩展（可选）
        if cfg.query_rewrite_multi_query:
            sub_queries = await _expand_queries(
                rewritten_query,
                n=cfg.query_rewrite_multi_query_count,
            )
            all_chunks = await retrieve_with_queries(
                queries=sub_queries,
                n_results=cfg.n_results,
                user_id=user_id,
            )
            chunks = _rrf_fusion(all_chunks)[:cfg.n_results]
        else:
            # 单查询模式：直接用改写后的 query 检索
            chunks = await retrieve(
                query=rewritten_query,
                n_results=cfg.n_results,
                user_id=user_id,
            )
    else:
        # 未启用 Query Rewrite：使用原始固定模板
        chunks = await retrieve_by_kp(
            kp_name,
            n_results=cfg.n_results,
            user_id=user_id,
        )
    # ------------------------------------------

    # 格式化上下文
    context = format_context(chunks, max_tokens=cfg.context_max_tokens)
    retrieved_texts = [c.text for c in chunks]

    retrieval_ms = (time.perf_counter() - t_start) * 1000
    if chunks:
        logger.info("[%s] RAG 检索到 %d 条参考资料 (%.0fms)", agent_label, len(chunks), retrieval_ms)
    else:
        logger.warning("[%s] RAG 未检索到参考资料，降级为纯 LLM 生成 (%.0fms)", agent_label, retrieval_ms)

    # 评估采集
    try:
        from backend.evaluation.collector import collector
        collector.start_query(
            query=rewritten_query,
            kp_name=kp_name,
            user_id=user_id,
            session_id="",
        )
        collector.record_retrieval(
            scores=[c.score for c in chunks],
            chunk_ids=[c.chunk_id for c in chunks],
            chunk_texts=[c.text for c in chunks],
            doc_ids=[c.doc_id for c in chunks],
            embedding_latency_ms=retrieval_ms * 0.6,
            db_query_latency_ms=retrieval_ms * 0.4,
        )
    except Exception:
        pass

    _retrieval_cache[cache_key] = (context, retrieved_texts)
    return context, retrieved_texts
