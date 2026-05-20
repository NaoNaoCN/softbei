"""
backend/db/database.py
PostgreSQL 数据库连接池与基础 CRUD 助手（异步 SQLAlchemy 2.x）。
Schema 管理由 Alembic 负责，此处不再调用 create_all。
"""

from __future__ import annotations

from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from backend.config import config

# ----------------------------------------------------------
# ORM Base
# ----------------------------------------------------------

class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# ----------------------------------------------------------
# Engine & Session factory（模块级单例，应用启动时初始化）
# ----------------------------------------------------------

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """返回当前引擎实例，未初始化则抛出 RuntimeError。"""
    if _engine is None:
        raise RuntimeError("Database engine not initialized. Call init_db() first.")
    return _engine


async def init_db() -> None:
    """
    创建 PostgreSQL 异步引擎、建立连接池。
    应在 FastAPI lifespan 的 startup 阶段调用。

    Schema 管理由 Alembic 负责，此处不调用 create_all。
    """
    global _engine, _session_factory
    db_cfg = config.database

    connect_args = {
        "timeout": db_cfg.pool_timeout,
        "command_timeout": db_cfg.command_timeout,
    }

    _engine = create_async_engine(
        db_cfg.url,
        echo=db_cfg.echo,
        pool_size=db_cfg.pool_size,
        max_overflow=db_cfg.max_overflow,
        pool_timeout=db_cfg.pool_timeout,
        pool_recycle=db_cfg.pool_recycle,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def close_db() -> None:
    """释放连接池，在 FastAPI lifespan 的 shutdown 阶段调用。"""
    global _engine
    if _engine:
        await _engine.dispose()
        _engine = None


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI Depends 依赖项，提供请求作用域的数据库会话。"""
    if _session_factory is None:
        raise RuntimeError("Database not initialized.")
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def health_check() -> bool:
    """简单的数据库连通性检查，返回 True 表示正常。"""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
