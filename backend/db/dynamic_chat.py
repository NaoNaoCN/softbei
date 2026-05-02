"""
backend/db/dynamic_chat.py
动态聊天会话表管理：
- 为每个会话创建独立的消息表
- 插入消息记录
- 后台定时清理过期会话表
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.database import get_engine, Base
from backend.db.models import ChatSession  # 导入以注册到 Base.metadata

logger = logging.getLogger(__name__)

# 会话表过期时间（天）
SESSION_EXPIRY_DAYS = 30


def build_table_name(username: str, session_id: str, created_at) -> str:
    """
    根据用户名、session_id 和创建时间生成消息表名。
    格式: chat_msg_<username>_<session_id前8位>
    """
    # 替换可能不合法的字符
    safe_username = username.replace("-", "_").replace(" ", "_")[:20]
    safe_id = session_id.replace("-", "_")[:8]
    return f"chat_msg_{safe_username}_{safe_id}"


async def create_session_table(table_name: str) -> None:
    """
    动态创建会话消息表。
    表结构: id, session_id, role, content, resource_type, created_at
    """
    engine = get_engine()

    sql = f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id VARCHAR(32) PRIMARY KEY,
        session_id VARCHAR(32) NOT NULL,
        role VARCHAR(16) NOT NULL,
        content TEXT,
        resource_type VARCHAR(16) DEFAULT NULL,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )
    """

    async with engine.begin() as conn:
        await conn.execute(text(sql))
        logger.info(f"创建会话表: {table_name}")


async def insert_message(
    table_name: str,
    role: str,
    content: str,
    resource_type: Optional[str] = None,
    message_id: Optional[str] = None,
) -> str:
    """
    插入一条聊天消息到指定的会话表。

    :param table_name: 消息表名（由 build_table_name 生成）
    :param role: "user" 或 "assistant"
    :param content: 消息内容
    :param resource_type: 资源类型（如 "mindmap"、"quiz"），仅 assistant 消息有值
    :param message_id: 可选的消息 ID
    """
    import uuid
    from backend.db.database import get_engine

    msg_id = message_id or str(uuid.uuid4()).replace("-", "")[:32]
    engine = get_engine()

    # 确保表存在
    await create_session_table(table_name)

    # 插入消息
    sql = f"""
    INSERT INTO {table_name} (id, session_id, role, content, resource_type, created_at)
    VALUES (:id, :session_id, :role, :content, :resource_type, :created_at)
    """

    async with engine.begin() as conn:
        await conn.execute(
            text(sql),
            {
                "id": msg_id,
                "session_id": table_name,
                "role": role,
                "content": content,
                "resource_type": resource_type,
                "created_at": datetime.now(),
            }
        )

    return msg_id


async def read_messages(table_name: str) -> list[dict]:
    """
    读取指定会话表的所有消息，按时间升序排列。

    :return: [{"role", "content", "resource_type", "created_at"}]
    """
    engine = get_engine()
    sql = f"SELECT role, content, resource_type, created_at FROM {table_name} ORDER BY created_at ASC"
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(sql))
            rows = result.fetchall()
        return [
            {
                "role": row[0],
                "content": row[1],
                "resource_type": row[2],
                "created_at": row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3]),
            }
            for row in rows
        ]
    except Exception as e:
        logger.warning(f"读取会话表 {table_name} 失败: {e}")
        return []


async def drop_session_table(table_name: str) -> None:
    """删除指定的会话消息表。"""
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
        logger.info(f"删除会话表: {table_name}")


async def cleanup_expired_sessions() -> None:
    """
    清理过期的会话表。
    检查 chat_session 表，删除超过 SESSION_EXPIRY_DAYS 天的会话及其消息表。
    """
    engine = get_engine()
    
    # 查询过期会话
    expiry_date = datetime.now() - timedelta(days=SESSION_EXPIRY_DAYS)
    
    async with engine.begin() as conn:
        # 获取过期会话的 messages_table
        result = await conn.execute(
            text("""
            SELECT messages_table FROM chat_session
            WHERE created_at < :expiry_date
            """),
            {"expiry_date": expiry_date}
        )
        
        expired_tables = [row[0] for row in result if row[0]]
        
        # 删除过期的消息表
        for table_name in expired_tables:
            try:
                await conn.execute(text(f"DROP TABLE IF EXISTS {table_name}"))
                logger.info(f"删除过期会话表: {table_name}")
            except Exception as e:
                logger.warning(f"删除表 {table_name} 失败: {e}")
        
        # 删除过期的会话记录
        await conn.execute(
            text("DELETE FROM chat_session WHERE created_at < :expiry_date"),
            {"expiry_date": expiry_date}
        )
        
        logger.info(f"清理完成，共删除 {len(expired_tables)} 个过期会话表")


async def start_cleanup_task() -> None:
    """
    启动后台清理任务。
    每 24 小时执行一次清理。
    """
    logger.info("启动会话清理后台任务（每24小时执行一次）")
    
    while True:
        try:
            await asyncio.sleep(24 * 60 * 60)  # 24小时
            await cleanup_expired_sessions()
        except asyncio.CancelledError:
            logger.info("会话清理任务已取消")
            break
        except Exception as e:
            logger.error(f"会话清理任务出错: {e}")
