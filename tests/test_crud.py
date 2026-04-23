"""
tests/test_crud.py
backend/db/crud.py 单元测试。
使用 SQLite 内存数据库进行测试。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.db.database import Base
from backend.db import models  # noqa: F401 - 注册所有模型
from backend.db.crud import (
    insert,
    insert_many,
    select,
    select_one,
    select_by_id,
    count,
    update_,
    update_by_id,
    delete,
    delete_by_id,
)
from backend.db.models import User, StudentProfile, ChatSession, ChatMessage


# ===========================================================
# 测试 fixtures
# ===========================================================

@pytest_asyncio.fixture
async def db_session():
    """创建测试用 SQLite 内存数据库会话。"""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as session:
        yield session

    await engine.dispose()


# ===========================================================
# insert tests
# ===========================================================

class TestInsert:
    """insert 单条记录测试。"""

    async def test_insert_user(self, db_session: AsyncSession):
        """插入用户记录。"""
        user = await insert(
            db_session,
            User,
            data={"username": "testuser", "hashed_password": "hashed123"},
        )
        assert user.id is not None
        assert user.username == "testuser"
        assert user.hashed_password == "hashed123"

    async def test_insert_user_no_commit(self, db_session: AsyncSession):
        """commit=False 时不应提交事务，数据在同一会话中仍可见。"""
        user = await insert(
            db_session,
            User,
            data={"username": "testuser2", "hashed_password": "hashed456"},
            commit=False,
        )
        # commit=False 时，refresh 不会被调用，ID 可能未填充
        # 但对象已添加到会话，在同一会话中仍可查询到
        result = await select_one(db_session, User, filters={"username": "testuser2"})
        assert result is not None
        assert result.username == "testuser2"


# ===========================================================
# insert_many tests
# ===========================================================

class TestInsertMany:
    """insert_many 批量插入测试。"""

    async def test_insert_many_users(self, db_session: AsyncSession):
        """批量插入多条用户记录。"""
        users = await insert_many(
            db_session,
            User,
            data_list=[
                {"username": "user1", "hashed_password": "hash1"},
                {"username": "user2", "hashed_password": "hash2"},
                {"username": "user3", "hashed_password": "hash3"},
            ],
        )
        assert len(users) == 3
        assert all(u.id is not None for u in users)


# ===========================================================
# select tests
# ===========================================================

class TestSelect:
    """select 查询列表测试。"""

    async def test_select_all_users(self, db_session: AsyncSession):
        """查询所有用户。"""
        await insert_many(
            db_session, User,
            data_list=[
                {"username": "u1", "hashed_password": "h1"},
                {"username": "u2", "hashed_password": "h2"},
            ],
        )
        users = await select(db_session, User)
        assert len(users) == 2

    async def test_select_with_filters(self, db_session: AsyncSession):
        """带过滤条件查询。"""
        await insert_many(
            db_session, User,
            data_list=[
                {"username": "alice", "hashed_password": "h1"},
                {"username": "bob", "hashed_password": "h2"},
            ],
        )
        users = await select(db_session, User, filters={"username": "alice"})
        assert len(users) == 1
        assert users[0].username == "alice"

    async def test_select_with_limit_offset(self, db_session: AsyncSession):
        """分页查询。"""
        await insert_many(
            db_session, User,
            data_list=[
                {"username": f"user{i}", "hashed_password": "h"}
                for i in range(5)
            ],
        )
        users = await select(db_session, User, limit=2, offset=1)
        assert len(users) == 2
        assert users[0].username == "user1"

    async def test_select_none_result(self, db_session: AsyncSession):
        """查询无结果。"""
        users = await select(db_session, User, filters={"username": "nonexistent"})
        assert len(users) == 0


# ===========================================================
# select_one tests
# ===========================================================

class TestSelectOne:
    """select_one 查询单条测试。"""

    async def test_select_one_found(self, db_session: AsyncSession):
        """查询到结果。"""
        await insert(db_session, User, data={"username": "testuser", "hashed_password": "h"})
        user = await select_one(db_session, User, filters={"username": "testuser"})
        assert user is not None
        assert user.username == "testuser"

    async def test_select_one_not_found(self, db_session: AsyncSession):
        """查询不到结果返回 None。"""
        user = await select_one(db_session, User, filters={"username": "nonexistent"})
        assert user is None


# ===========================================================
# select_by_id tests
# ===========================================================

class TestSelectById:
    """select_by_id 按 ID 查询测试。"""

    async def test_select_by_id_found(self, db_session: AsyncSession):
        """按 ID 查询到结果。"""
        user = await insert(db_session, User, data={"username": "testuser", "hashed_password": "h"})
        found = await select_by_id(db_session, User, user.id)
        assert found is not None
        assert found.id == user.id

    async def test_select_by_id_not_found(self, db_session: AsyncSession):
        """按不存在的 ID 查询。"""
        found = await select_by_id(db_session, User, uuid.uuid4())
        assert found is None


# ===========================================================
# count tests
# ===========================================================

class TestCount:
    """count 统计测试。"""

    async def test_count_all(self, db_session: AsyncSession):
        """统计所有记录数。"""
        await insert_many(
            db_session, User,
            data_list=[
                {"username": f"u{i}", "hashed_password": "h"}
                for i in range(3)
            ],
        )
        total = await count(db_session, User)
        assert total == 3

    async def test_count_with_filters(self, db_session: AsyncSession):
        """带条件统计。"""
        await insert_many(
            db_session, User,
            data_list=[
                {"username": "alice", "hashed_password": "h1"},
                {"username": "bob", "hashed_password": "h2"},
            ],
        )
        total = await count(db_session, User, filters={"username": "alice"})
        assert total == 1


# ===========================================================
# update_ tests
# ===========================================================

class TestUpdate:
    """update_ 更新测试。"""

    async def test_update_by_filter(self, db_session: AsyncSession):
        """按条件更新。"""
        user = await insert(db_session, User, data={"username": "oldname", "hashed_password": "h"})
        rows = await update_(
            db_session, User,
            filters={"username": "oldname"},
            data={"username": "newname"},
        )
        assert rows == 1
        await db_session.refresh(user)
        assert user.username == "newname"

    async def test_update_no_match(self, db_session: AsyncSession):
        """更新条件无匹配。"""
        rows = await update_(
            db_session, User,
            filters={"username": "nonexistent"},
            data={"username": "newname"},
        )
        assert rows == 0


# ===========================================================
# update_by_id tests
# ===========================================================

class TestUpdateById:
    """update_by_id 按 ID 更新测试。"""

    async def test_update_by_id_success(self, db_session: AsyncSession):
        """按 ID 更新成功。"""
        user = await insert(db_session, User, data={"username": "testuser", "hashed_password": "h"})
        success = await update_by_id(
            db_session, User, user.id,
            data={"username": "updated"},
        )
        assert success is True
        await db_session.refresh(user)
        assert user.username == "updated"

    async def test_update_by_id_not_found(self, db_session: AsyncSession):
        """按不存在的 ID 更新。"""
        success = await update_by_id(
            db_session, User, uuid.uuid4(),
            data={"username": "updated"},
        )
        assert success is False


# ===========================================================
# delete tests
# ===========================================================

class TestDelete:
    """delete 删除测试。"""

    async def test_delete_by_filter(self, db_session: AsyncSession):
        """按条件删除。"""
        await insert(db_session, User, data={"username": "todelete", "hashed_password": "h"})
        rows = await delete(db_session, User, filters={"username": "todelete"})
        assert rows == 1
        remaining = await select(db_session, User, filters={"username": "todelete"})
        assert len(remaining) == 0

    async def test_delete_no_match(self, db_session: AsyncSession):
        """删除条件无匹配。"""
        rows = await delete(db_session, User, filters={"username": "nonexistent"})
        assert rows == 0


# ===========================================================
# delete_by_id tests
# ===========================================================

class TestDeleteById:
    """delete_by_id 按 ID 删除测试。"""

    async def test_delete_by_id_success(self, db_session: AsyncSession):
        """按 ID 删除成功。"""
        user = await insert(db_session, User, data={"username": "todelete", "hashed_password": "h"})
        success = await delete_by_id(db_session, User, user.id)
        assert success is True
        found = await select_by_id(db_session, User, user.id)
        assert found is None

    async def test_delete_by_id_not_found(self, db_session: AsyncSession):
        """按不存在的 ID 删除。"""
        success = await delete_by_id(db_session, User, uuid.uuid4())
        assert success is False


# ===========================================================
# loadRelations tests（关系预加载）
# ===========================================================

class TestLoadRelations:
    """loadRelations 关系预加载测试。"""

    async def test_load_relation(self, db_session: AsyncSession):
        """预加载 ChatSession 的 messages 关系。"""
        user = await insert(db_session, User, data={"username": "testuser", "hashed_password": "h"})
        session = await insert(
            db_session, ChatSession,
            data={"user_id": user.id, "title": "Test Session"},
        )
        await insert(
            db_session, ChatMessage,
            data={"session_id": session.id, "role": "user", "content": "Hello"},
        )
        await insert(
            db_session, ChatMessage,
            data={"session_id": session.id, "role": "assistant", "content": "Hi there"},
        )

        # 不预加载关系时，messages 不会自动加载
        sessions = await select(db_session, ChatSession, filters={"user_id": user.id})
        assert len(sessions) == 1
        # lazy loading 可能触发，需要预加载
        sessions_loaded = await select(
            db_session, ChatSession,
            filters={"user_id": user.id},
            loadRelations=["messages"],
        )
        assert len(sessions_loaded[0].messages) == 2
