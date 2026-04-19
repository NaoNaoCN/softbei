"""
backend/models/schemas.py
Pydantic v2 数据模型，供 FastAPI 路由、Agent 以及前端 API 调用共同使用。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


# ===========================================================
# 枚举定义
# ===========================================================

class ResourceType(str, Enum):
    doc = "doc"
    mindmap = "mindmap"
    quiz = "quiz"
    code = "code"
    summary = "summary"


class TaskStatus(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    failed = "failed"


class KGNodeType(str, Enum):
    Course = "Course"
    Chapter = "Chapter"
    KnowledgePoint = "KnowledgePoint"
    SubPoint = "SubPoint"
    Concept = "Concept"


class KGRelation(str, Enum):
    IS_PART_OF = "IS_PART_OF"
    REQUIRES = "REQUIRES"
    RELATED_TO = "RELATED_TO"
    CONTAINS = "CONTAINS"


class QuestionType(str, Enum):
    single = "single"
    multi = "multi"
    fill = "fill"
    short = "short"


class CognitiveStyle(str, Enum):
    visual = "visual"
    text = "text"
    practice = "practice"


# ===========================================================
# 用户相关
# ===========================================================

class UserCreate(BaseModel):
    username: str = Field(..., min_length=2, max_length=64)
    password: str = Field(..., min_length=6)
    email: Optional[str] = None


class UserOut(BaseModel):
    id: uuid.UUID
    username: str
    email: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ===========================================================
# 学生画像
# ===========================================================

class StudentProfileIn(BaseModel):
    """用户提交 / 更新画像时的请求体"""
    major: Optional[str] = None
    learning_goal: Optional[str] = None
    cognitive_style: Optional[CognitiveStyle] = None
    daily_time_minutes: Optional[int] = Field(None, ge=10, le=480)
    knowledge_mastered: list[str] = Field(default_factory=list)
    knowledge_weak: list[str] = Field(default_factory=list)
    error_prone: list[str] = Field(default_factory=list)
    current_progress: Optional[str] = None


class StudentProfileOut(StudentProfileIn):
    id: uuid.UUID
    user_id: uuid.UUID
    version: int
    updated_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# 对话会话
# ===========================================================

class ChatMessageIn(BaseModel):
    content: str = Field(..., min_length=1, max_length=4096)


class ChatMessageOut(BaseModel):
    role: str
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ChatSessionOut(BaseModel):
    id: uuid.UUID
    title: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# 知识图谱
# ===========================================================

class KGNodeOut(BaseModel):
    id: str
    type: KGNodeType
    name: str
    difficulty: Optional[int]
    is_core: bool
    extra: dict[str, Any] = {}

    model_config = {"from_attributes": True}


class KGEdgeOut(BaseModel):
    source_id: str
    target_id: str
    relation: KGRelation

    model_config = {"from_attributes": True}


class KGGraphOut(BaseModel):
    """完整子图，用于前端 ECharts 渲染"""
    nodes: list[KGNodeOut]
    edges: list[KGEdgeOut]


# ===========================================================
# 学习路径
# ===========================================================

class LearningPathItemOut(BaseModel):
    order_index: int
    kp_id: str
    kp_name: str
    is_completed: bool

    model_config = {"from_attributes": True}


class LearningPathOut(BaseModel):
    id: uuid.UUID
    name: str
    description: Optional[str]
    items: list[LearningPathItemOut] = []
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# 资源生成
# ===========================================================

class GenerateRequest(BaseModel):
    """触发资源生成的请求体"""
    kp_id: str = Field(..., description="目标知识点节点 ID")
    resource_type: ResourceType
    extra_params: dict[str, Any] = Field(default_factory=dict)


class GenerateTaskOut(BaseModel):
    task_id: uuid.UUID
    status: TaskStatus
    progress: int = Field(ge=0, le=100)
    error_msg: Optional[str] = None
    result_id: Optional[uuid.UUID] = None

    model_config = {"from_attributes": True}


class ResourceMetaOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    kp_id: Optional[str]
    resource_type: ResourceType
    title: str
    content_path: Optional[str]
    content_json: Optional[dict[str, Any]]
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# 测验 / 题目
# ===========================================================

class QuizItemOut(BaseModel):
    id: uuid.UUID
    kp_id: Optional[str]
    question_type: QuestionType
    difficulty: Optional[int]
    stem: str
    options: Optional[list[str]]
    answer: Any
    explanation: Optional[str]

    model_config = {"from_attributes": True}


class QuizSubmitIn(BaseModel):
    """学生提交答题结果"""
    quiz_item_id: uuid.UUID
    user_answer: Any


class QuizAttemptOut(BaseModel):
    id: uuid.UUID
    quiz_item_id: uuid.UUID
    user_answer: Any
    is_correct: bool
    score: float
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# 学习记录
# ===========================================================

class LearningRecordCreate(BaseModel):
    resource_id: uuid.UUID
    duration_seconds: Optional[int] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    feedback: Optional[str] = None


class LearningRecordOut(LearningRecordCreate):
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


# ===========================================================
# Agent 内部状态（LangGraph State）
# ===========================================================

class AgentState(BaseModel):
    """LangGraph 全局状态，在各 Agent 节点间传递"""
    user_id: str
    session_id: str
    user_message: str
    profile: Optional[StudentProfileOut] = None
    kp_id: Optional[str] = None
    resource_type: Optional[ResourceType] = None
    retrieved_docs: list[str] = Field(default_factory=list)
    draft_content: Optional[str] = None
    final_content: Optional[str] = None
    safety_passed: bool = True
    error: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
