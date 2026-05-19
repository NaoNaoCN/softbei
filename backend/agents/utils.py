"""
backend/agents/utils.py
Agent 公共工具函数。
"""

from __future__ import annotations

from loguru import logger  # noqa: F401

from backend.config import config
from backend.models.schemas import AgentState


async def resolve_kp_name(state: AgentState, config: dict | None = None) -> str:
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
    if config and "configurable" in config:
        db = config["configurable"].get("db")

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


async def retrieve_context(
    kp_name: str,
    user_id: int,
    agent_label: str = "Agent",
) -> tuple[str, list[str]]:
    """
    RAG 检索并格式化上下文，供各生成 Agent 复用。

    :param kp_name:      知识点名称
    :param user_id:      用户 ID（用于账户隔离）
    :param agent_label:  Agent 名称标签（用于日志输出，如 "DocAgent"）
    :return:             (context_str, retrieved_texts)
    """
    from backend.rag.retriever import retrieve_by_kp, format_context

    try:
        chunks = await retrieve_by_kp(kp_name, n_results=config.rag.n_results, user_id=str(user_id))
        context = format_context(chunks, max_tokens=config.rag.context_max_tokens)
        retrieved_texts = [c.text for c in chunks]
        if chunks:
            logger.info("[%s] RAG 检索到 %d 条参考资料", agent_label, len(chunks))
        else:
            logger.warning("[%s] RAG 未检索到参考资料，降级为纯 LLM 生成", agent_label)
    except Exception as e:
        logger.warning("[%s] RAG 检索异常: %s，降级为纯 LLM 生成", agent_label, e)
        context = "（暂无参考资料）"
        retrieved_texts = []

    return context, retrieved_texts
