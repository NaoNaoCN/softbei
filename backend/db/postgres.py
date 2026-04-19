"""
backend/db/postgres.py
PostgreSQL / SQLite 数据库连接池与基础 CRUD 助手（异步 SQLAlchemy 2.x）。
"""

from __future__ import annotations

import os
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

# ----------------------------------------------------------
# 配置：优先读取环境变量，回退到 SQLite（开发模式）
# ----------------------------------------------------------
DATABASE_URL: str = os.getenv(
    "DATABASE_URL",
    "sqlite+aiosqlite:///./dev.db",
)

# ----------------------------------------------------------
# ORM Base
# ----------------------------------------------------------

class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""
    pass


# 导入所有模型，确保 Base.metadata 在 create_all 前已注册全部表
# 注意：必须在 Base 定义之后、init_db() 调用之前完成导入
def _import_models() -> None:
    from backend.db import models  # noqa: F401


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
    创建引擎、建立连接池，并在开发模式下自动建表。
    应在 FastAPI lifespan 的 startup 阶段调用。
    """
    global _engine, _session_factory
    _engine = create_async_engine(
        DATABASE_URL,
        echo=bool(os.getenv("DB_ECHO", False)),
        pool_pre_ping=True,
    )
    _session_factory = async_sessionmaker(
        _engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    # 开发/测试时自动建表
    if "sqlite" in DATABASE_URL:
        _import_models()
        async with _engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)


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
