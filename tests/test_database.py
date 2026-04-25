"""
tests/test_database.py
backend/db/database.py 单元测试。
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import database


# ===========================================================
# Base tests
# ===========================================================

class TestBase:
    """Base ORM 基类测试。"""

    def test_base_is_declarative(self):
        """Base 应继承自 DeclarativeBase。"""
        from sqlalchemy.orm import DeclarativeBase
        assert issubclass(database.Base, DeclarativeBase)


# ===========================================================
# Engine / get_engine tests
# ===========================================================

class TestGetEngine:
    """get_engine 函数测试。"""

    def test_get_engine_before_init_raises(self):
        """引擎未初始化时应抛出 RuntimeError。"""
        # 重置模块级状态
        database._engine = None
        database._session_factory = None
        with pytest.raises(RuntimeError, match="not initialized"):
            database.get_engine()


# ===========================================================
# init_db / close_db tests
# ===========================================================

def _make_mock_engine():
    """创建模拟引擎和会话工厂。"""
    mock_engine = MagicMock()
    mock_engine.begin = MagicMock(return_value=AsyncMock().__aenter__)
    mock_session_maker = MagicMock()
    return mock_engine, mock_session_maker


class TestInitDb:
    """init_db / close_db 函数测试。"""

    @pytest.mark.asyncio
    async def test_init_db_creates_engine(self):
        """init_db 应创建引擎和会话工厂。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_session_factory = MagicMock()
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=mock_session_factory):
                        await database.init_db()

        assert database._engine is mock_engine
        assert database._session_factory is mock_session_factory
        await database.close_db()

    @pytest.mark.asyncio
    async def test_init_db_sets_singleton(self):
        """init_db 应设置模块级单例。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_session_factory = MagicMock()
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=mock_session_factory):
                        await database.init_db()

        engine1 = database.get_engine()
        engine2 = database.get_engine()
        assert engine1 is engine2
        await database.close_db()


class TestCloseDb:
    """close_db 函数测试。"""

    @pytest.mark.asyncio
    async def test_close_db_disposes_engine(self):
        """close_db 应释放引擎。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=MagicMock()):
                        await database.init_db()

        await database.close_db()

        assert database._engine is None

    @pytest.mark.asyncio
    async def test_close_db_when_not_initialized(self):
        """引擎未初始化时调用 close_db 不应抛出异常。"""
        database._engine = None
        database._session_factory = None
        # 不应抛出
        await database.close_db()


# ===========================================================
# get_session tests
# ===========================================================

class TestGetSession:
    """get_session 依赖项测试。"""

    @pytest.mark.asyncio
    async def test_get_session_before_init_raises(self):
        """会话工厂未初始化时应抛出 RuntimeError。"""
        database._engine = None
        database._session_factory = None

        with pytest.raises(RuntimeError, match="not initialized"):
            # get_session 是生成器函数，需迭代
            list(database.get_session().__anext__())

    @pytest.mark.asyncio
    async def test_get_session_yields_session(self):
        """初始化后 get_session 应正常 yield 会话。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_session_factory = MagicMock()
        mock_session = AsyncMock(spec=AsyncSession)
        mock_session_factory.return_value.__aenter__.return_value = mock_session
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=mock_session_factory):
                        await database.init_db()

        sessions = []
        async for session in database.get_session():
            sessions.append(session)
            assert isinstance(session, AsyncSession)
        await database.close_db()


# ===========================================================
# health_check tests
# ===========================================================

class TestHealthCheck:
    """health_check 函数测试。"""

    @pytest.mark.asyncio
    async def test_health_check_before_init_returns_false(self):
        """引擎未初始化时 health_check 应返回 False。"""
        database._engine = None
        result = await database.health_check()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """引擎正常时应返回 True。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_conn = MagicMock()
        mock_conn.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_conn.__aexit__ = AsyncMock(return_value=None)
        mock_conn.execute = AsyncMock()
        mock_engine.connect.return_value = mock_conn
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=MagicMock()):
                        await database.init_db()

        result = await database.health_check()
        assert result is True
        await database.close_db()

    @pytest.mark.asyncio
    async def test_health_check_on_closed_engine_returns_false(self):
        """引擎已关闭时 health_check 应返回 False。"""
        database._engine = None
        database._session_factory = None

        mock_engine = MagicMock()
        mock_engine.dispose = AsyncMock()
        mock_config = MagicMock()
        mock_config.url = "sqlite+aiosqlite:///:memory:"

        with patch.object(database, "_import_models"):
            with patch.object(database, "config", mock_config):
                with patch.object(database, "create_async_engine", return_value=mock_engine):
                    with patch.object(database, "async_sessionmaker", return_value=MagicMock()):
                        await database.init_db()
        await database.close_db()

        result = await database.health_check()
        assert result is False
