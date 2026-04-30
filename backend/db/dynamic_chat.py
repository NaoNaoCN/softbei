"""
backend/db/dynamic_chat.py
动态会话消息表管理：
- 每个 chat_session 在数据库中拥有一张独立的消息表（与 chat_session 同级）
- 表名规则: chat_msg_{username}_{YYYYMMDDHHMMSS}_{sid8}
- 后台定时任务定期清理 last_used_at 超过 TTL 的过期表
"""

from __future__ import annotations

import asyncio
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.crud import select as db_select
from backend.db.database import get_engine
from backend.db.models import ChatSession

# ----------------------------------------------------------
# 默认配置
# ----------------------------------------------------------

# 表名前缀
TABLE_PREFIX = "chat_msg_"
# 默认未使用过期天数
DEFAULT_TTL_DAYS = 30
# 后台清理任务执行周期（小时）
CLEANUP_INTERVAL_HOURS = 24


# ----------------------------------------------------------
# 工具函数
# ----------------------------------------------------------

def _sanitize(name: str) -> str:
    """将任意字符串转换为合法 SQL 标识符片段（仅保留 [a-zA-Z0-9_]）。"""
    return re.sub(r"[^a-zA-Z0-9_]", "_", str(name))[:32] or "x"


def build_table_name(
    username: str,
    session_id: str,
    created_at: datetime | None = None,
) -> str:
    """
    构造动态消息表名：chat_msg_{username}_{YYYYMMDDHHMMSS}_{sid8}

    Args:
        username:    用户名
        session_id:  会话 UUID 字符串
        created_at:  创建时间，默认为 utcnow()
    Returns:
        合法的 SQL 表名
    """
    ts = (created_at or datetime.utcnow()).strftime("%Y%m%d%H%M%S")
    safe_user = _sanitize(username)
    sid8 = _sanitize(session_id.replace("-", ""))[:8]
    return f"{TABLE_PREFIX}{safe_user}_{ts}_{sid8}"


def _is_sqlite() -> bool:
    return "sqlite" in str(get_engine().url)


def _quote(name: str) -> str:
    """根据数据库方言加引号包裹标识符。"""
    return f'"{name}"' if _is_sqlite() else f"`{name}`"


# ----------------------------------------------------------
# 建表 / 删表
# ----------------------------------------------------------

async def create_session_table(table_name: str) -> None:
    """
    创建一个会话独立的消息表，字段：id / role / content / created_at。
    若表已存在则不重复创建。
    """
    engine = get_engine()
    qname = _quote(table_name)
    if _is_sqlite():
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {qname} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    else:
        # MySQL
        ddl = f"""
        CREATE TABLE IF NOT EXISTS {qname} (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            role VARCHAR(16) NOT NULL,
            content TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        ) DEFAULT CHARSET=utf8mb4
        """
    async with engine.begin() as conn:
        await conn.execute(text(ddl))


async def drop_session_table(table_name: str) -> None:
    """删除指定的会话消息表（若存在）。"""
    engine = get_engine()
    qname = _quote(table_name)
    async with engine.begin() as conn:
        await conn.execute(text(f"DROP TABLE IF EXISTS {qname}"))


# ----------------------------------------------------------
# 消息读写
# ----------------------------------------------------------

async def insert_message(table_name: str, role: str, content: str) -> None:
    """向动态会话表插入一条消息。"""
    engine = get_engine()
    qname = _quote(table_name)
    sql = text(
        f"INSERT INTO {qname} (role, content, created_at) "
        f"VALUES (:role, :content, :created_at)"
    )
    async with engine.begin() as conn:
        await conn.execute(
            sql,
            {"role": role, "content": content, "created_at": datetime.utcnow()},
        )


async def fetch_messages(table_name: str, limit: int | None = None) -> list[dict[str, Any]]:
    """按时间正序读取动态会话表中的消息列表。"""
    engine = get_engine()
    qname = _quote(table_name)
    sql = f"SELECT id, role, content, created_at FROM {qname} ORDER BY id ASC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    async with engine.connect() as conn:
        result = await conn.execute(text(sql))
        rows = result.mappings().all()
        return [dict(r) for r in rows]


# ----------------------------------------------------------
# 过期清理
# ----------------------------------------------------------

async def cleanup_idle_tables(
    session: AsyncSession,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> int:
    """
    清理 last_used_at 距今超过 ttl_days 的会话：
    - 删除其动态消息表
    - 删除 chat_session 行

    Returns:
        被清理的会话数量
    """
    threshold = datetime.utcnow() - timedelta(days=ttl_days)
    sessions = await db_select(session, ChatSession)
    deleted = 0
    for s in sessions:
        last_used = s.last_used_at or s.created_at
        if last_used is None or last_used >= threshold:
            continue
        if s.messages_table:
            try:
                await drop_session_table(s.messages_table)
            except Exception:
                # 单表失败不影响其他清理
                pass
        await session.delete(s)
        deleted += 1
    if deleted:
        await session.commit()
    return deleted


async def start_cleanup_task(
    interval_hours: int = CLEANUP_INTERVAL_HOURS,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> None:
    """
    后台定期清理任务（在 FastAPI lifespan 中以 asyncio.create_task 启动）。
    每 interval_hours 小时执行一次清理。
    """
    # 延迟导入避免循环依赖
    from backend.db import database as db_module

    while True:
        try:
            await asyncio.sleep(interval_hours * 3600)
        except asyncio.CancelledError:
            break
        try:
            factory = getattr(db_module, "_session_factory", None)
            if factory is None:
                continue
            async with factory() as session:
                await cleanup_idle_tables(session, ttl_days)
        except Exception:
            # 后台任务不应抛出异常导致循环中断
            continue
