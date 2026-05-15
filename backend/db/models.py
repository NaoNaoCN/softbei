"""
backend/db/models.py
SQLAlchemy 2.x ORM 模型定义（13 张表）。
所有模型继承 Base，模块被导入后自动注册到 Base.metadata。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.database import Base
from backend.models.schemas import (
    CognitiveStyle,
    KGNodeType,
    KGRelation,
    QuestionType,
    ResourceType,
    TaskStatus,
)


# ----------------------------------------------------------
# 1. User
# ----------------------------------------------------------

class User(Base):
    __tablename__ = "user"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile: Mapped["StudentProfile"] = relationship(back_populates="user", uselist=False)
    sessions: Mapped[list["ChatSession"]] = relationship(back_populates="user")
    resources: Mapped[list["ResourceMeta"]] = relationship(back_populates="user")
    learning_paths: Mapped[list["LearningPath"]] = relationship(back_populates="user")
    learning_records: Mapped[list["LearningRecord"]] = relationship(back_populates="user")


# ----------------------------------------------------------
# 2. StudentProfile + ProfileHistory
# ----------------------------------------------------------

class StudentProfile(Base):
    __tablename__ = "student_profile"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), unique=True, nullable=False)
    major: Mapped[str | None] = mapped_column(String(128))
    learning_goal: Mapped[str | None] = mapped_column(Text)
    cognitive_style: Mapped[str | None] = mapped_column(
        Enum(CognitiveStyle, values_callable=lambda e: [m.value for m in e])
    )
    daily_time_minutes: Mapped[int | None] = mapped_column(Integer)
    knowledge_mastered: Mapped[list | None] = mapped_column(JSON)
    knowledge_weak: Mapped[list | None] = mapped_column(JSON)
    error_prone: Mapped[list | None] = mapped_column(JSON)
    current_progress: Mapped[str | None] = mapped_column(Text)
    # 学习目标历史提问列表：记录每轮对话的 user_message，供 LLM 做总体概括
    goal_questions: Mapped[list | None] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="profile")
    history: Mapped[list["ProfileHistory"]] = relationship(back_populates="profile")


class ProfileHistory(Base):
    __tablename__ = "profile_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    profile_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("student_profile.id"), nullable=False)
    snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    profile: Mapped["StudentProfile"] = relationship(back_populates="history")


# ----------------------------------------------------------
# 3. ChatSession
# ----------------------------------------------------------

class ChatSession(Base):
    __tablename__ = "chat_session"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    last_used_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="sessions")


# ----------------------------------------------------------
# 3b. ChatMessage（取代动态 per-session 消息表）
# ----------------------------------------------------------

class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("chat_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    resource_type: Mapped[str | None] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_chat_message_session_time", "session_id", "created_at"),
    )


# ----------------------------------------------------------
# 3c. DocumentChunk（向量存储）
# ----------------------------------------------------------

class DocumentChunk(Base):
    __tablename__ = "document_chunk"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    chunk_id: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)
    collection_name: Mapped[str] = mapped_column(String(64), default="knowledge_base", index=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)
    source: Mapped[str | None] = mapped_column(String(512))
    page: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String(256))
    user_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_document_chunk_doc_id", "doc_id"),
    )


# ----------------------------------------------------------
# 4. KGNode + KGEdge（知识图谱）
# ----------------------------------------------------------

class KGNode(Base):
    __tablename__ = "kg_node"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)   # e.g. "kp_03_01"
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    node_type: Mapped[str] = mapped_column(
        Enum(KGNodeType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    description: Mapped[str | None] = mapped_column(Text)
    course_id: Mapped[str | None] = mapped_column(String(64))
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)

    out_edges: Mapped[list["KGEdge"]] = relationship(
        back_populates="source_node", foreign_keys="KGEdge.source_id"
    )
    in_edges: Mapped[list["KGEdge"]] = relationship(
        back_populates="target_node", foreign_keys="KGEdge.target_id"
    )


class KGEdge(Base):
    __tablename__ = "kg_edge"
    __table_args__ = (UniqueConstraint("source_id", "target_id", "relation"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(ForeignKey("kg_node.id"), nullable=False)
    target_id: Mapped[str] = mapped_column(ForeignKey("kg_node.id"), nullable=False)
    relation: Mapped[str] = mapped_column(
        Enum(KGRelation, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )

    source_node: Mapped["KGNode"] = relationship(back_populates="out_edges", foreign_keys=[source_id])
    target_node: Mapped["KGNode"] = relationship(back_populates="in_edges", foreign_keys=[target_id])


# ----------------------------------------------------------
# 5. ResourceMeta + GenerationTask
# ----------------------------------------------------------

class ResourceMeta(Base):
    __tablename__ = "resource_meta"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(256), nullable=False)
    resource_type: Mapped[str] = mapped_column(
        Enum(ResourceType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(256))
    content: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[dict | None] = mapped_column(JSON)   # 思维导图等结构化内容，与content字段互斥使用
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="resources")
    task: Mapped["GenerationTask | None"] = relationship(back_populates="resource", uselist=False)
    quiz_items: Mapped[list["QuizItem"]] = relationship(back_populates="resource")
    learning_records: Mapped[list["LearningRecord"]] = relationship(back_populates="resource")


class GenerationBatch(Base):
    """批量生成任务批次，关联多个 GenerationTask。"""
    __tablename__ = "generation_batch"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    kp_id: Mapped[str] = mapped_column(String(256), nullable=False)
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus, values_callable=lambda e: [m.value for m in e]),
        default=TaskStatus.pending,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    resource_types: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    tasks: Mapped[list["GenerationTask"]] = relationship(back_populates="batch")


class GenerationTask(Base):
    __tablename__ = "generation_task"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_meta.id"), unique=True, nullable=False)
    batch_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("generation_batch.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus, values_callable=lambda e: [m.value for m in e]),
        default=TaskStatus.pending,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)   # 0-100
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    resource: Mapped["ResourceMeta"] = relationship(back_populates="task")
    batch: Mapped["GenerationBatch | None"] = relationship(back_populates="tasks")


# ----------------------------------------------------------
# 5b. KGBuildTask（知识图谱构建任务）
# ----------------------------------------------------------

class KGBuildTask(Base):
    __tablename__ = "kg_build_task"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    doc_id: Mapped[str] = mapped_column(String(128), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("user.id"), nullable=True)
    status: Mapped[str] = mapped_column(
        Enum(TaskStatus, values_callable=lambda e: [m.value for m in e]),
        default=TaskStatus.pending,
        nullable=False,
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(String(64))
    nodes_count: Mapped[int] = mapped_column(Integer, default=0)
    edges_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ----------------------------------------------------------
# 6. QuizItem + QuizAttempt
# ----------------------------------------------------------

class QuizItem(Base):
    __tablename__ = "quiz_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resource_meta.id"), nullable=False)
    kp_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    question_type: Mapped[str] = mapped_column(
        Enum(QuestionType, values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    stem: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list | None] = mapped_column(JSON)          # 选择题选项
    answer: Mapped[str] = mapped_column(Text, nullable=False)   # 标准答案
    explanation: Mapped[str | None] = mapped_column(Text)
    order_index: Mapped[int] = mapped_column(Integer, default=0)

    resource: Mapped["ResourceMeta"] = relationship(back_populates="quiz_items")
    attempts: Mapped[list["QuizAttempt"]] = relationship(back_populates="quiz_item")


class QuizAttempt(Base):
    __tablename__ = "quiz_attempt"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    quiz_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("quiz_item.id"), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    user_answer: Mapped[str] = mapped_column(Text, nullable=False)
    is_correct: Mapped[bool] = mapped_column(Boolean, nullable=False)
    score: Mapped[float | None] = mapped_column(Float)
    kp_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column("submitted_at", DateTime, default=datetime.utcnow)

    quiz_item: Mapped["QuizItem"] = relationship(back_populates="attempts")


# ----------------------------------------------------------
# 7. LearningPath + LearningPathItem
# ----------------------------------------------------------

class LearningPath(Base):
    __tablename__ = "learning_path"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256))
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="learning_paths")
    items: Mapped[list["LearningPathItem"]] = relationship(
        back_populates="path", order_by="LearningPathItem.order_index"
    )


class LearningPathItem(Base):
    __tablename__ = "learning_path_item"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    path_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("learning_path.id"), nullable=False)
    kp_id: Mapped[str] = mapped_column(ForeignKey("kg_node.id"), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False)
    is_completed: Mapped[bool] = mapped_column(Boolean, default=False)

    path: Mapped["LearningPath"] = relationship(back_populates="items")
    kp: Mapped["KGNode"] = relationship()


# ----------------------------------------------------------
# 8. LearningRecord
# ----------------------------------------------------------

class LearningRecord(Base):
    __tablename__ = "learning_record"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    resource_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resource_meta.id"))
    kp_id: Mapped[str | None] = mapped_column(ForeignKey("kg_node.id"))
    action: Mapped[str] = mapped_column(String(64), nullable=False)   # "view" | "complete" | "quiz"
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    user: Mapped["User"] = relationship(back_populates="learning_records")
    resource: Mapped["ResourceMeta | None"] = relationship(back_populates="learning_records")
