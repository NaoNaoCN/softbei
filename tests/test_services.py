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
    """创建测试用 SQLite 内存数据库会话，测试结束后自动销毁。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession):
    """插入测试用户 alice，供各测试用例使用。"""
    return await insert(db_session, User, {"username": "alice", "hashed_password": "h"})


@pytest_asyncio.fixture
async def sample_user_b(db_session: AsyncSession):
    """插入第二个测试用户 bob，用于权限隔离测试。"""
    return await insert(db_session, User, {"username": "bob", "hashed_password": "h"})

@pytest_asyncio.fixture
async def sample_kp_node(db_session: AsyncSession):
    """插入测试用知识点节点，ResourceMeta / LearningPathItem 的外键依赖。"""
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
    """get_profile 查询画像测试。"""

    async def test_existing_profile(self, db_session, sample_user):
        """已存在画像时应正确返回。"""
        data = StudentProfileIn(major="CS", learning_goal="DL")
        await create_or_update_profile(sample_user.id, data, db_session)
        result = await get_profile(sample_user.id, db_session)
        assert result is not None
        assert result.major == "CS"

    async def test_no_profile(self, db_session, sample_user):
        """用户尚未建立画像时应返回 None。"""
        result = await get_profile(sample_user.id, db_session)
        assert result is None


class TestCreateOrUpdateProfile:
    """create_or_update_profile 创建/更新画像测试。"""

    async def test_create_new(self, db_session, sample_user):
        """首次调用应创建新画像并返回正确字段。"""
        data = StudentProfileIn(major="EE", daily_time_minutes=60)
        out = await create_or_update_profile(sample_user.id, data, db_session)
        assert out.major == "EE"
        assert out.daily_time_minutes == 60
        assert out.user_id == sample_user.id

    async def test_update_existing(self, db_session, sample_user):
        """已有画像时应更新字段。"""
        d1 = StudentProfileIn(major="CS")
        await create_or_update_profile(sample_user.id, d1, db_session)
        d2 = StudentProfileIn(major="EE", learning_goal="ML")
        out = await create_or_update_profile(sample_user.id, d2, db_session)
        assert out.major == "EE"
        assert out.learning_goal == "ML"

    async def test_history_snapshot_created(self, db_session, sample_user):
        """每次更新应在 profile_history 中生成快照记录。"""
        d1 = StudentProfileIn(major="CS")
        await create_or_update_profile(sample_user.id, d1, db_session)
        d2 = StudentProfileIn(major="EE")
        await create_or_update_profile(sample_user.id, d2, db_session)
        history = await get_profile_history(sample_user.id, db_session)
        assert len(history) >= 2

    async def test_json_fields_roundtrip(self, db_session, sample_user):
        """JSON 列表字段（knowledge_mastered 等）应正确存取往返。"""
        data = StudentProfileIn(
            knowledge_mastered=["线性代数", "概率论"],
            knowledge_weak=["微积分"],
            error_prone=["极限"],
        )
        out = await create_or_update_profile(sample_user.id, data, db_session)
        assert out.knowledge_mastered == ["线性代数", "概率论"]
        assert out.knowledge_weak == ["微积分"]


class TestGetProfileHistory:
    """get_profile_history 画像历史版本测试。"""

    async def test_empty_history(self, db_session, sample_user):
        """无画像时应返回空列表。"""
        result = await get_profile_history(sample_user.id, db_session)
        assert result == []

    async def test_limit(self, db_session, sample_user):
        """limit 参数应限制返回的历史条数。"""
        for i in range(5):
            await create_or_update_profile(
                sample_user.id,
                StudentProfileIn(major=f"M{i}"),
                db_session,
            )
        history = await get_profile_history(sample_user.id, db_session, limit=3)
        assert len(history) <= 3


class TestMergeChatUpdates:
    """merge_chat_updates 增量合并画像字段测试。"""

    async def test_creates_when_no_profile(self, db_session, sample_user):
        """无画像时应自动创建新画像。"""
        out = await merge_chat_updates(sample_user.id, {"major": "CS"}, db_session)
        assert out.major == "CS"

    async def test_partial_update(self, db_session, sample_user):
        """只更新 updates 中非 None 的字段，其余保持不变。"""
        await create_or_update_profile(
            sample_user.id, StudentProfileIn(major="CS", learning_goal="DL"), db_session
        )
        out = await merge_chat_updates(sample_user.id, {"major": "EE"}, db_session)
        assert out.major == "EE"

    async def test_empty_update(self, db_session, sample_user):
        """空 updates 不应修改任何字段。"""
        await create_or_update_profile(
            sample_user.id, StudentProfileIn(major="CS"), db_session
        )
        out = await merge_chat_updates(sample_user.id, {}, db_session)
        assert out.major == "CS"


class TestBuildProfileContext:
    """build_profile_context 画像序列化为 prompt 上下文测试。"""

    async def test_full_fields(self):
        """所有字段都有值时应拼接完整上下文字符串。"""
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
        """所有字段为空时应返回"暂无学生画像信息"。"""        
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
    """get_resource 按 ID 查询资源元数据测试。"""

    async def test_existing(self, db_session, sample_user, sample_kp_node):
        """存在的资源应正确返回元数据。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        res = await get_resource(status.result_id, db_session)
        assert res is not None
        assert res.kp_id == "kp_01_01"

    async def test_not_found(self, db_session):
        """不存在的资源 ID 应返回 None。"""
        res = await get_resource(uuid.uuid4(), db_session)
        assert res is None


class TestListResources:
    """list_resources 分页列举用户资源测试。"""

    async def test_list_all(self, db_session, sample_user, sample_kp_node):
        """应返回用户的全部资源。"""
        for rt in [ResourceType.doc, ResourceType.quiz]:
            req = GenerateRequest(kp_id="kp_01_01", resource_type=rt)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session)
        assert len(result) == 2

    async def test_filter_by_type(self, db_session, sample_user, sample_kp_node):
        """按 resource_type 过滤应只返回匹配类型的资源。"""        
        for rt in [ResourceType.doc, ResourceType.quiz]:
            req = GenerateRequest(kp_id="kp_01_01", resource_type=rt)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session, resource_type="doc")
        assert len(result) == 1
        assert result[0].resource_type == ResourceType.doc

    async def test_empty(self, db_session, sample_user):
        """无资源时应返回空列表。"""
        result = await list_resources(sample_user.id, db_session)
        assert result == []

    async def test_pagination(self, db_session, sample_user, sample_kp_node):
        """skip/limit 分页参数应正确限制返回数量。"""
        for _ in range(5):
            req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
            await create_generation_task(sample_user.id, req, db_session)
        result = await list_resources(sample_user.id, db_session, skip=0, limit=2)
        assert len(result) == 2


class TestDeleteResource:
    """delete_resource 物理删除资源测试。"""

    async def test_delete_existing(self, db_session, sample_user, sample_kp_node):
        """删除存在的资源应返回 True。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        ok = await delete_resource(status.result_id, db_session)
        assert ok is True

    async def test_delete_not_found(self, db_session):
        """删除不存在的资源应返回 False。"""
        ok = await delete_resource(uuid.uuid4(), db_session)
        assert ok is False


class TestCreateGenerationTask:
    """create_generation_task 创建生成任务测试。"""

    async def test_creates_resource_and_task(self, db_session, sample_user, sample_kp_node):
        """应同时创建资源记录和任务记录，初始状态为 pending。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.mindmap)
        out = await create_generation_task(sample_user.id, req, db_session)
        assert out.status == TaskStatus.pending
        assert out.progress == 0

    async def test_title_format(self, db_session, sample_user, sample_kp_node):
        """资源标题应包含 resource_type 和 kp_id。"""        
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        res = await get_resource(status.result_id, db_session)
        assert "doc" in res.title
        assert "kp_01_01" in res.title


class TestGetTaskStatus:
    """get_task_status 轮询任务状态测试。"""

    async def test_existing(self, db_session, sample_user, sample_kp_node):
        """存在的任务应返回当前状态。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        assert status is not None
        assert status.status == TaskStatus.pending

    async def test_not_found(self, db_session):
        """不存在的任务 ID 应返回 None。"""
        status = await get_task_status(uuid.uuid4(), db_session)
        assert status is None


class TestUpdateTaskProgress:
    """update_task_progress 更新任务进度/状态测试。"""

    async def test_update(self, db_session, sample_user, sample_kp_node):
        """应正确更新进度和状态。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        await update_task_progress(task.task_id, 50, TaskStatus.running, db_session)
        status = await get_task_status(task.task_id, db_session)
        assert status.progress == 50
        assert status.status == TaskStatus.running

    async def test_update_with_error(self, db_session, sample_user, sample_kp_node):
        """失败时应记录 error_msg。"""        
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        await update_task_progress(
            task.task_id, 0, TaskStatus.failed, db_session, error_msg="LLM timeout"
        )
        status = await get_task_status(task.task_id, db_session)
        assert status.status == TaskStatus.failed
        assert status.error_msg == "LLM timeout"


class TestRecordLearning:
    """record_learning 记录学习行为测试。"""

    async def test_create_record(self, db_session, sample_user, sample_kp_node):
        """应创建学习记录并返回正确的 user_id 和 duration。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        data = LearningRecordCreate(resource_id=status.result_id, duration_seconds=120)
        rec = await record_learning(sample_user.id, data, db_session)
        assert rec.user_id == sample_user.id
        assert rec.duration_seconds == 120


class TestListLearningRecords:
    """list_learning_records 列举学习历史测试。"""

    async def test_list(self, db_session, sample_user, sample_kp_node):
        """应返回用户的全部学习记录。"""
        req = GenerateRequest(kp_id="kp_01_01", resource_type=ResourceType.doc)
        task = await create_generation_task(sample_user.id, req, db_session)
        status = await get_task_status(task.task_id, db_session)
        for _ in range(3):
            data = LearningRecordCreate(resource_id=status.result_id)
            await record_learning(sample_user.id, data, db_session)
        records = await list_learning_records(sample_user.id, db_session)
        assert len(records) == 3

    async def test_empty(self, db_session, sample_user):
        """无记录时应返回空列表。"""
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
    """create_pathway 创建学习路径测试。"""

    async def test_create(self, db_session, sample_user):
        """应创建路径并返回正确的 name、description，items 为空。"""
        data = LearningPathCreate(name="DL路径", description="深度学习")
        out = await create_pathway(sample_user.id, data, db_session)
        assert out.name == "DL路径"
        assert out.description == "深度学习"
        assert out.items == []


class TestGetPathway:
    """get_pathway 按 ID 获取学习路径测试。"""

    async def test_existing(self, db_session, sample_user):
        """存在的路径应正确返回。"""
        data = LearningPathCreate(name="路径A")
        created = await create_pathway(sample_user.id, data, db_session)
        out = await get_pathway(created.id, db_session)
        assert out is not None
        assert out.name == "路径A"

    async def test_not_found(self, db_session):
        """不存在的路径 ID 应返回 None。"""
        out = await get_pathway(uuid.uuid4(), db_session)
        assert out is None


class TestListPathways:
    """list_pathways 列举用户学习路径测试。"""

    async def test_list(self, db_session, sample_user):
        """应返回用户的全部学习路径。"""
        for i in range(3):
            await create_pathway(sample_user.id, LearningPathCreate(name=f"P{i}"), db_session)
        result = await list_pathways(sample_user.id, db_session)
        assert len(result) == 3

    async def test_empty(self, db_session, sample_user):
        """无路径时应返回空列表。"""
        result = await list_pathways(sample_user.id, db_session)
        assert result == []


class TestUpdatePathway:
    """update_pathway 更新学习路径标题/描述测试。"""

    async def test_update_title(self, db_session, sample_user):
        """应正确更新路径标题。"""
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Old"), db_session
        )
        out = await update_pathway(
            created.id, sample_user.id, LearningPathUpdate(name="New"), db_session
        )
        assert out is not None
        assert out.name == "New"

    async def test_wrong_user(self, db_session, sample_user, sample_user_b):
        """非所有者更新应返回 None（权限隔离）。"""
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Mine"), db_session
        )
        out = await update_pathway(
            created.id, sample_user_b.id, LearningPathUpdate(name="Stolen"), db_session
        )
        assert out is None

    async def test_not_found(self, db_session, sample_user):
        """不存在的路径 ID 应返回 None。"""
        out = await update_pathway(
            uuid.uuid4(), sample_user.id, LearningPathUpdate(name="X"), db_session
        )
        assert out is None


class TestDeletePathway:
    """delete_pathway 删除学习路径测试（含级联删除 items）。"""

    async def test_delete(self, db_session, sample_user, sample_kp_node):
        """删除路径应同时级联删除关联的 items。"""
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
        """非所有者删除应返回 False（权限隔离）。"""
        created = await create_pathway(
            sample_user.id, LearningPathCreate(name="Mine"), db_session
        )
        ok = await delete_pathway(created.id, sample_user_b.id, db_session)
        assert ok is False


class TestAddPathwayItem:
    """add_pathway_item 向路径添加知识点项测试。"""

    async def test_add(self, db_session, sample_user, sample_kp_node):
        """应成功添加知识点项并返回正确的 kp_id。"""
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
        """非所有者添加应返回 None（权限隔离）。"""
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user_b.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        assert item is None


class TestUpdatePathwayItem:
    """update_pathway_item 更新路径项（顺序/完成状态）测试。"""

    async def test_update_completed(self, db_session, sample_user, sample_kp_node):
        """应正确将 is_completed 更新为 True。"""
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
        """非所有者更新路径项应返回 None（权限隔离）。"""
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
    """remove_pathway_item 从路径移除知识点项测试。"""

    async def test_remove(self, db_session, sample_user, sample_kp_node):
        """应成功移除路径项并返回 True。"""
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
        """非所有者移除路径项应返回 False（权限隔离）。"""
        path = await create_pathway(
            sample_user.id, LearningPathCreate(name="P"), db_session
        )
        item = await add_pathway_item(
            path.id, sample_user.id,
            LearningPathItemCreate(kp_id="kp_01_01", order_index=0), db_session
        )
        ok = await remove_pathway_item(item.id, sample_user_b.id, db_session)
        assert ok is False
