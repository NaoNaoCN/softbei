"""
tests/test_services.py
backend/services 模块（profile, resource, pathway）单元测试。
使用 SQLite 内存数据库。
"""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.db.database import Base
from backend.db import models as _models  # noqa: F401 — 注册所有 ORM 模型
from backend.db.models import User, KGNode, StudentProfile
from backend.db.crud import insert
from backend.models.schemas import (
    CognitiveStyle,
    GenerateRequest,
    LearningPathCreate,
    LearningPathItemCreate,
    LearningPathItemUpdate,
    LearningPathUpdate,
    LearningRecordCreate,
    ResourceType,
    StudentProfileIn,
    TaskStatus,
)


# ===========================================================
# 共享 fixtures
# ===========================================================

@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession):
    return await insert(db_session, User, {"username": "alice", "hashed_password": "h"})


@pytest_asyncio.fixture
async def sample_user_b(db_session: AsyncSession):
    return await insert(db_session, User, {"username": "bob", "hashed_password": "h"})

@pytest_asyncio.fixture
async def sample_kp_node(db_session: AsyncSession):
    return await insert(db_session, KGNode, {
        "id": "kp_01_01",
        "name": "梯度下降",
        "node_type": "KnowledgePoint",
    })


# ===========================================================
# profile.py 测试
# ===========================================================

from backend.services.profile import (
    get_profile,
    create_or_update_profile,
    get_profile_history,
    merge_chat_updates,
    build_profile_context,
)


class TestGetProfile:
    async def test_existing_profile(self, db_session, sample_user):
        data = StudentProfileIn(major="CS", learning_goal="DL")
        await create_or_update_profile(sample_user.id, data, db_session)
        result = await get_profile(sample_user.id, db_session)
        assert result is not None
        assert result.major == "CS"

    async def test_no_profile(self, db_session, sample_user):
        result = await get_profile(sample_user.id, db_session)
        assert result is None


class TestCreateOrUpdateProfile:
    async def test_create_new(self, db_session, sample_user):
        data = StudentProfileIn(major="EE", daily_time_minutes=60)
        out = await create_or_update_profile(sample_user.id, data, db_session)
        assert out.major == "EE"
        assert out.daily_time_minutes == 60
        assert out.user_id == sample_user.id

    async def test_update_existing(self, db_session, sample_user):
        d1 = StudentProfileIn(major="CS")
        await create_or_update_profile(sample_user.id, d1, db_session)
        d2 = StudentProfileIn(major="EE", learning_goal="ML")
        out = await create_or_update_profile(sample_user.id, d2, db_session)
        assert out.major == "EE"
        assert out.learning_goal == "ML"

    async def test_history_snapshot_created(self, db_session, sample_user):
        d1 = StudentProfileIn(major="CS")
        await create_or_update_profile(sample_user.id, d1, db_session)
        d2 = StudentProfileIn(major="EE")
        await create_or_update_profile(sample_user.id, d2, db_session)
        history = await get_profile_history(sample_user.id, db_session)
        assert len(history) >= 2

    async def test_json_fields_roundtrip(self, db_session, sample_user):
        data = StudentProfileIn(
            knowledge_mastered=["线性代数", "概率论"],
            knowledge_weak=["微积分"],
            error_prone=["极限"],
        )
        out = await create_or_update_profile(sample_user.id, data, db_session)
        assert out.knowledge_mastered == ["线性代数", "概率论"]
        assert out.knowledge_weak == ["微积分"]


class TestGetProfileHistory:
    async def test_empty_history(self, db_session, sample_user):
        result = await get_profile_history(sample_user.id, db_session)
        assert result == []

    async def test_limit(self, db_session, sample_user):
        for i in range(5):
            await create_or_update_profile(
                sample_user.id,
                StudentProfileIn(major=f"M{i}"),
                db_session,
            )
        history = await get_profile_history(sample_user.id, db_session, limit=3)
        assert len(history) <= 3


class TestMergeChatUpdates:
    async def test_creates_when_no_profile(self, db_session, sample_user):
        out = await merge_chat_updates(sample_user.id, {"major": "CS"}, db_session)
        assert out.major == "CS"

    async def test_partial_update(self, db_session, sample_user):
        await create_or_update_profile(
            sample_user.id, StudentProfileIn(major="CS", learning_goal="DL"), db_session
        )
        out = await merge_chat_updates(sample_user.id, {"major": "EE"}, db_session)
        assert out.major == "EE"

    async def test_empty_update(self, db_session, sample_user):
        await create_or_update_profile(
            sample_user.id, StudentProfileIn(major="CS"), db_session
        )
        out = await merge_chat_updates(sample_user.id, {}, db_session)
        assert out.major == "CS"


class TestBuildProfileContext:
    async def test_full_fields(self):
        p = StudentProfileIn(
            major="CS",
            learning_goal="DL",
            cognitive_style=CognitiveStyle.visual,
            daily_time_minutes=60,
            knowledge_mastered=["LA"],
            knowledge_weak=["Calc"],
            error_prone=["Limit"],
            current_progress="Chapter 3",
        )
        from backend.models.schemas import StudentProfileOut
        from datetime import datetime
        out = StudentProfileOut(
            id=uuid.uuid4(), user_id=uuid.uuid4(), version=1,
            updated_at=datetime.utcnow(), **p.model_dump()
        )
        ctx = await build_profile_context(out)
        assert "CS" in ctx
        assert "DL" in ctx
        assert "visual" in ctx

    async def test_empty_profile(self):
        from backend.models.schemas import StudentProfileOut
        from datetime import datetime
        out = StudentProfileOut(
            id=uuid.uuid4(), user_id=uuid.uuid4(), version=1,
            updated_at=datetime.utcnow(),
        )
        ctx = await build_profile_context(out)
        assert ctx == "暂无学生画像信息"

# ===========================================================
# resource.py 测试
# ===========================================================

from backend.services.resource import (
    get_resource,
    list_resources,
    delete_resource,
    create_generation_task,
    get_task_status,
    update_task_progress,
    record_learning,
    list_learning_records,
)


class TestGetResource:
    async def test_existing(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        res = await get_resource(status.result_id, db_session)
        assert res is not None
        assert res.kp_id == "kp_01_01"

    async def test_not_found(self, db_session):
        res = await get_resource(uuid.uuid4(), db_session)
        assert res is None


class TestListResources:
    async def test_list_all(self, db_session, sample_user, sample_kp_node):
        for rt in [ResourceType.doc, ResourceType.quiz]:
            req = GenerateRequest(kp_id="kp_01_01", resource_type=rt)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session)
        assert len(result) == 2

    async def test_filter_by_type(self, db_session, sample_user, sample_kp_node):
        for rt in [ResourceType.doc, ResourceType.quiz]:
            req = GenerateRequest(kp_id="kp_01_01", resource_type=rt)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session, resource_type="doc")
        assert len(result) == 1
        assert result[0].resource_type == ResourceType.doc

    async def test_empty(self, db_session, sample_user):
        result = await list_resources(sample_user.id, db_session)
        assert result == []

    async def test_pagination(self, db_session, sample_user, sample_kp_node):
        for _ in range(5):
            req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session, skip=0, limit=2)
        assert len(result) == 2


class TestDeleteResource:
    async def test_delete_existing(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        ok = await delete_resource(status.result_id, db_session)
        assert ok is True

    async def test_delete_not_found(self, db_session):
        ok = await delete_resource(uuid.uuid4(), db_session)
        assert ok is False


class TestCreateGenerationTask:
    async def test_creates_resource_and_task(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.mindmap)
        out = await create_generation_task(sample_user.id, req, db_session)
        assert out.status == TaskStatus.pending
        assert out.progress == 0

    async def test_title_format(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        res = await get_resource(status.result_id, db_session)
        assert "doc" in res.title
        assert "kp_01_01" in res.title


class TestGetTaskStatus:
    async def test_existing(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        assert status is not None
        assert status.status == TaskStatus.pending

    async def test_not_found(self, db_session):
        status = await get_task_status(uuid.uuid4(), db_session)
        assert status is None


class TestUpdateTaskProgress:
    async def test_update(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        await update_task_progress(task.task_id, 50, TaskStatus.running, db_session)
        status = await get_task_status(task.task_id, db_session)
        assert status.progress == 50
        assert status.status == TaskStatus.running

    async def test_update_with_error(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        await update_task_progress(
            task.task_id, 0, TaskStatus.failed, db_session, error_msg="LLM timeout"
        )
        status = await get_task_status(task.task_id, db_session)
        assert status.status == TaskStatus.failed
        assert status.error_msg == "LLM timeout"


class TestRecordLearning:
    async def test_create_record(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        data = LearningRecordCreate(resource_id=status.result_id, duration_seconds=120)
        rec = await record_learning(sample_user.id, data, db_session)
        assert rec.user_id == sample_user.id
        assert rec.duration_seconds == 120


class TestListLearningRecords:
    async def test_list(self, db_session, sample_user, sample_kp_node):
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        for _ in range(3):
            data = LearningRecordCreate(resource_id=status.result_id)
            await record_learning(sample_user.id, data, db_session)
        records = await list_learning_records(sample_user.id, db_session)
        assert len(records) == 3

    async def test_empty(self, db_session, sample_user):
        records = await list_learning_records(sample_user.id, db_session)
        assert records == []

# ===========================================================
# pathway.py 测试
# ===========================================================

from backend.services.pathway import (
    get_pathway,
    list_pathways,
    create_pathway,
    update_pathway,
    delete_pathway,
    add_pathway_item,
    update_pathway_item,
    remove_pathway_item,
)


class TestCreatePathway:
    async def test_create(self, db_session, sample_user):
        data = LearningPathCreate(name="DL路径", description="深度学习")
        out = await create_pathway(sample_user.id, data, db_session)
        assert out.name == "DL路径"
        assert out.description == "深度学习"
        assert out.items == []


class TestGetPathway:
    async def test_existing(self, db_session, sample_user):
        data = LearningPathCreate(name="路径A")
        created = await create_pathway(sample_user.id, data, db_session)
        out = await get_pathway(created.id, db_session)
        assert out is not None
        assert out.name == "路径A"

    async def test_not_found(self, db_session):
        out = await get_pathway(uuid.uuid4(), db_session)
        assert out is None


class TestListPathways:
    async def test_list(self, db_session, sample_user):
        for i in range(3):
            await create_pathway(sample_user.id, LearningPathCreate(name=f"P{i}"), db_session)
        result = await list_pathways(sample_user.id, db_session)
        assert len(result) == 3

    async def test_empty(self, db_session, sample_user):
        result = await list_pathways(sample_user.id, db_session)
        assert result == []


class TestUpdatePathway:
    async def test_update_title(self, db_session, sample_user):
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Old"), db_session
        )
        out = await update_pathway(
            created.id, sample_user.id, LearningPathUpdate(name="New"), db_session
        )
        assert out is not None
        assert out.name == "New"

    async def test_wrong_user(self, db_session, sample_user, sample_user_b):
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Mine"), db_session
        )
        out = await update_pathway(
            created.id, sample_user_b.id, LearningPathUpdate(name="Stolen"), db_session
        )
        assert out is None

    async def test_not_found(self, db_session, sample_user):
        out = await update_pathway(
            uuid.uuid4(), sample_user.id, LearningPathUpdate(name="X"), db_session
        )
        assert out is None


class TestDeletePathway:
    async def test_delete(self, db_session, sample_user, sample_kp_node):
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="ToDelete"), db_session
        )
        await add_pathway_item(
            created.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        ok = await delete_pathway(created.id, sample_user.id, db_session)
        assert ok is True
        assert await get_pathway(created.id, db_session) is None

    async def test_wrong_user(self, db_session, sample_user, sample_user_b):
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Mine"), db_session
        )
        ok = await delete_pathway(created.id, sample_user_b.id, db_session)
        assert ok is False


class TestAddPathwayItem:
    async def test_add(self, db_session, sample_user, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        assert item is not None
        assert item.kp_id == "kp_01_01"

    async def test_wrong_user(self, db_session, sample_user, sample_user_b, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user_b.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        assert item is None


class TestUpdatePathwayItem:
    async def test_update_completed(self, db_session, sample_user, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        updated = await update_pathway_item(
            item.id, sample_user.id,
            LearningPathItemUpdate(is_completed=True), db_session
        )
        assert updated is not None
        assert updated.is_completed is True

    async def test_wrong_user(self, db_session, sample_user, sample_user_b, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        updated = await update_pathway_item(
            item.id, sample_user_b.id,
            LearningPathItemUpdate(is_completed=True), db_session
        )
        assert updated is None


class TestRemovePathwayItem:
    async def test_remove(self, db_session, sample_user, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        ok = await remove_pathway_item(item.id, sample_user.id, db_session)
        assert ok is True

    async def test_wrong_user(self, db_session, sample_user, sample_user_b, sample_kp_node):
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        ok = await remove_pathway_item(item.id, sample_user_b.id, db_session)
        assert ok is False
