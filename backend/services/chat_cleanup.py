"""
backend/services/chat_cleanup.py
聊天会话过期清理服务：定期清理过期的 ChatSession 及关联 ChatMessage。
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

from loguru import logger
from sqlalchemy import text

from backend.db.database import get_engine

# 会话表过期时间（天）
SESSION_EXPIRY_DAYS = 30


async def cleanup_expired_sessions() -> None:
    """
    清理过期的聊天会话及关联消息。
    ChatMessage 通过外键 CASCADE 自动删除，此处主要清理 ChatSession。
    """
    engine = get_engine()
    expiry_date = datetime.now() - timedelta(days=SESSION_EXPIRY_DAYS)

    async with engine.begin() as conn:
        # 先统计将被删除的消息数
        result = await conn.execute(
            text("""
            SELECT COUNT(*) FROM chat_message
            WHERE session_id IN (
                SELECT id FROM chat_session WHERE created_at < :expiry_date
            )
            """),
            {"expiry_date": expiry_date},
        )
        msg_count = result.scalar() or 0

        # 删除过期会话（CASCADE 自动删除关联消息）
        result = await conn.execute(
            text("DELETE FROM chat_session WHERE created_at < :expiry_date"),
            {"expiry_date": expiry_date},
        )
        session_count = result.rowcount or 0

        if session_count > 0:
            logger.info(
                f"[ChatCleanup] 清理完成: 删除 {session_count} 个过期会话, "
                f"{msg_count} 条关联消息"
            )
        else:
            logger.debug("[ChatCleanup] 无过期会话需要清理")


async def start_cleanup_task() -> None:
    """
    启动后台清理任务，每 24 小时执行一次。
    """
    logger.info("[ChatCleanup] 启动聊天会话清理后台任务（每24小时执行一次）")

    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)
            await cleanup_expired_sessions()
        except asyncio.CancelledError:
            logger.info("[ChatCleanup] 会话清理任务已取消")
            break
        except Exception as e:
            logger.error(f"[ChatCleanup] 会话清理任务出错: {e}")
