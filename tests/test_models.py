"""
tests/test_models.py
backend/db/models.py 单元测试。
测试 ORM 模型定义、字段类型、关系和约束。
"""

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from backend.db.database import Base
from backend.db import models  # noqa: F401 - 注册所有模型


# ===========================================================
# fixtures
# ===========================================================

@pytest.fixture
def sync_engine():
    """同步引擎用于表结构检查。"""
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


# ===========================================================
# 模型注册测试
# ===========================================================

class TestModelRegistration:
    """确认所有模型已正确注册到 Base.metadata。"""

    def test_all_models_are_registered(self, sync_engine):
        """所有定义的模型类都应在 metadata 中。"""
        table_names = set(inspect(sync_engine).get_table_names())
        expected_tables = {
            "user",
            "student_profile",
            "profile_history",
            "chat_session",
            "chat_message",
            "kg_node",
            "kg_edge",
            "resource_meta",
            "generation_task",
            "quiz_item",
            "quiz_attempt",
            "learning_path",
            "learning_path_item",
            "learning_record",
        }
        assert expected_tables.issubset(table_names)


# ===========================================================
# User 模型测试
# ===========================================================

class TestUserModel:
    """User 模型测试。"""

    def test_user_tablename(self):
        assert models.User.__tablename__ == "user"

    def test_user_primary_key_is_uuid(self):
        pk = inspect(models.User).primary_key[0]
        assert pk.name == "id"

    def test_user_username_unique(self):
        cols = {c.name: c for c in inspect(models.User).columns}
        assert cols["username"].unique is True

    def test_user_relationships(self, sync_engine):
        """User 应与 StudentProfile、ChatSession、ResourceMeta、LearningPath、LearningRecord 建立关系。"""
        from sqlalchemy.orm import Session
        with Session(sync_engine) as sess:
            # 验证关系属性存在
            user_cls = models.User
            assert hasattr(user_cls, "profile")
            assert hasattr(user_cls, "sessions")
            assert hasattr(user_cls, "resources")
            assert hasattr(user_cls, "learning_paths")
            assert hasattr(user_cls, "learning_records")


# ===========================================================
# StudentProfile 模型测试
# ===========================================================

class TestStudentProfileModel:
    """StudentProfile 模型测试。"""

    def test_profile_tablename(self):
        assert models.StudentProfile.__tablename__ == "student_profile"

    def test_profile_user_id_unique(self):
        """profile.user_id 应是 unique=True（与 user 一对一）。"""
        cols = {c.name: c for c in inspect(models.StudentProfile).columns}
        assert cols["user_id"].unique is True

    def test_profile_cognitive_style_enum(self):
        """cognitive_style 字段应为 Enum 类型。"""
        cols = {c.name: c for c in inspect(models.StudentProfile).columns}
        col = cols["cognitive_style"]
        assert col.type is not None


# ===========================================================
# ChatSession / ChatMessage 模型测试
# ===========================================================

class TestChatModels:
    """ChatSession / ChatMessage 模型测试。"""

    def test_session_tablename(self):
        assert models.ChatSession.__tablename__ == "chat_session"

    def test_message_tablename(self):
        assert models.ChatMessage.__tablename__ == "chat_message"

    def test_message_role_length(self):
        """role 字段长度为 16。"""
        cols = {c.name: c for c in inspect(models.ChatMessage).columns}
        # SQLAlchemy 2.x String 类型通过 type.length 访问
        str_type = cols["role"].type
        assert str_type.length == 16


# ===========================================================
# KGNode / KGEdge 模型测试
# ===========================================================

class TestKGModels:
    """KGNode / KGEdge 模型测试。"""

    def test_node_tablename(self):
        assert models.KGNode.__tablename__ == "kg_node"

    def test_node_primary_key_is_string(self):
        """KGNode 主键为 String 类型（非 UUID）。"""
        pk = inspect(models.KGNode).primary_key[0]
        assert pk.name == "id"
        assert pk.type.length == 64

    def test_edge_unique_constraint(self):
        """KGEdge 应有 (source_id, target_id, relation) 唯一约束。"""
        # 从 __table__ 获取 constraints（不是 Mapper）
        constraints = inspect(models.KGEdge.__table__).constraints
        ux = next((c for c in constraints if c.__class__.__name__ == "UniqueConstraint"), None)
        assert ux is not None
        col_names = {c.name for c in ux.columns}
        assert {"source_id", "target_id", "relation"}.issubset(col_names)


# ===========================================================
# ResourceMeta / GenerationTask 模型测试
# ===========================================================

class TestResourceModels:
    """ResourceMeta / GenerationTask 模型测试。"""

    def test_resource_tablename(self):
        assert models.ResourceMeta.__tablename__ == "resource_meta"

    def test_task_tablename(self):
        assert models.GenerationTask.__tablename__ == "generation_task"

    def test_task_resource_id_unique(self):
        """GenerationTask.resource_id 应为 unique=True。"""
        cols = {c.name: c for c in inspect(models.GenerationTask).columns}
        assert cols["resource_id"].unique is True

    def test_resource_task_one_to_one(self):
        """ResourceMeta 与 GenerationTask 为一对一关系。"""
        assert models.ResourceMeta.__mapper__.relationships["task"].uselist is False


# ===========================================================
# QuizItem / QuizAttempt 模型测试
# ===========================================================

class TestQuizModels:
    """QuizItem / QuizAttempt 模型测试。"""

    def test_quiz_item_tablename(self):
        assert models.QuizItem.__tablename__ == "quiz_item"

    def test_quiz_attempt_tablename(self):
        assert models.QuizAttempt.__tablename__ == "quiz_attempt"

    def test_quiz_attempt_is_correct_not_null(self):
        """QuizAttempt.is_correct 应为非空。"""
        cols = {c.name: c for c in inspect(models.QuizAttempt).columns}
        assert cols["is_correct"].nullable is False


# ===========================================================
# LearningPath / LearningPathItem 模型测试
# ===========================================================

class TestLearningPathModels:
    """LearningPath / LearningPathItem 模型测试。"""

    def test_path_tablename(self):
        assert models.LearningPath.__tablename__ == "learning_path"

    def test_path_item_tablename(self):
        assert models.LearningPathItem.__tablename__ == "learning_path_item"

    def test_path_item_order_index_not_nullable(self):
        """LearningPathItem.order_index 不可为空。"""
        cols = {c.name: c for c in inspect(models.LearningPathItem).columns}
        assert cols["order_index"].nullable is False


# ===========================================================
# LearningRecord 模型测试
# ===========================================================

class TestLearningRecordModel:
    """LearningRecord 模型测试。"""

    def test_record_tablename(self):
        assert models.LearningRecord.__tablename__ == "learning_record"

    def test_record_action_not_nullable(self):
        """LearningRecord.action 不可为空。"""
        cols = {c.name: c for c in inspect(models.LearningRecord).columns}
        assert cols["action"].nullable is False


# ===========================================================
# ProfileHistory 模型测试
# ===========================================================

class TestProfileHistoryModel:
    """ProfileHistory 模型测试。"""

    def test_history_tablename(self):
        assert models.ProfileHistory.__tablename__ == "profile_history"

    def test_history_snapshot_not_nullable(self):
        """ProfileHistory.snapshot 不可为空。"""
        cols = {c.name: c for c in inspect(models.ProfileHistory).columns}
        assert cols["snapshot"].nullable is False
