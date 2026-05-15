"""
backend/services/chat_history.py
多轮对话历史管理：加载、截断、token 估算。
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# 默认参数
DEFAULT_MAX_TURNS = 10  # 最多保留最近 N 轮（1轮 = 1 user + 1 assistant）
DEFAULT_MAX_TOKENS = 4000  # 历史部分的 token 预算


def estimate_tokens(text: str) -> int:
    """
    粗略估算 token 数。
    中文约 1.5 字/token，英文约 4 字符/token，取混合估算。
    """
    cn_chars = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
    other_chars = len(text) - cn_chars
    return int(cn_chars / 1.5 + other_chars / 4)


def truncate_history(
    history: list[dict[str, str]],
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, str]]:
    """
    截断对话历史，确保不超过 token 预算。

    策略：
    1. 先按 max_turns 截取最近 N 轮
    2. 从最近往前累加 token，超出预算时截断
    3. 保证返回的历史从 user 消息开始（不会出现孤立的 assistant 消息）
    """
    if not history:
        return []

    # Step 1: 按轮数截断（保留最近 max_turns 轮）
    truncated = history[-(max_turns * 2):]

    # Step 2: 按 token 预算从后往前保留
    total_tokens = 0
    keep_from = 0
    for i in range(len(truncated) - 1, -1, -1):
        msg_tokens = estimate_tokens(truncated[i].get("content", ""))
        if total_tokens + msg_tokens > max_tokens:
            keep_from = i + 1
            break
        total_tokens += msg_tokens

    result = truncated[keep_from:]

    # Step 3: 确保从 user 消息开始
    if result and result[0].get("role") == "assistant":
        result = result[1:]

    return result


async def load_chat_history(
    session_id: str,
    db: AsyncSession,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> list[dict[str, str]]:
    """
    从 ChatMessage 表加载历史消息并截断。

    :param session_id: 会话 UUID 字符串
    :param db: 数据库会话
    :param max_turns: 最大保留轮数
    :param max_tokens: 历史 token 预算
    :return: 截断后的历史消息列表
    """
    from backend.db.crud import select as db_select
    from backend.db.models import ChatMessage
    import uuid as uuid_mod

    try:
        sid = uuid_mod.UUID(session_id) if isinstance(session_id, str) else session_id
        messages = await db_select(
            db, ChatMessage,
            filters={"session_id": sid},
            order_by=ChatMessage.created_at.asc(),
        )
        if not messages:
            return []

        history = [{"role": m.role, "content": m.content} for m in messages]
        return truncate_history(history, max_turns, max_tokens)

    except Exception as e:
        logger.warning(f"加载对话历史失败: {e}")
        return []
