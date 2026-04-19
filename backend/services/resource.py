"""
backend/services/resource.py
学习资源服务：元数据管理、生成任务跟踪、学习记录。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import (
    GenerateRequest,
    GenerateTaskOut,
    LearningRecordCreate,
    LearningRecordOut,
    ResourceMetaOut,
    TaskStatus,
)


# ----------------------------------------------------------
# 资源元数据
# ----------------------------------------------------------

async def get_resource(resource_id: uuid.UUID, db: AsyncSession) -> Optional[ResourceMetaOut]:
    """按 ID 查询资源元数据。"""
    # TODO: 查询 resource_meta 表
    raise NotImplementedError


async def list_resources(
    user_id: uuid.UUID,
    db: AsyncSession,
    resource_type: Optional[str] = None,
    kp_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[ResourceMetaOut]:
    """分页列举用户的资源，可按类型或知识点过滤。"""
    # TODO: 查询 resource_meta 表（带 WHERE + LIMIT + OFFSET）
    raise NotImplementedError


async def delete_resource(resource_id: uuid.UUID, db: AsyncSession) -> bool:
    """软删除或物理删除资源元数据（级联删除 quiz_item 等）。"""
    # TODO: DELETE FROM resource_meta WHERE id = ...
    raise NotImplementedError


# ----------------------------------------------------------
# 生成任务
# ----------------------------------------------------------

async def create_generation_task(
    user_id: uuid.UUID,
    request: GenerateRequest,
    db: AsyncSession,
) -> GenerateTaskOut:
    """
    在数据库中创建一条 pending 状态的生成任务记录，
    返回任务 ID 供前端轮询进度。
    实际异步执行由 BackgroundTasks / Celery 触发。
    """
    # TODO: INSERT INTO generation_task (user_id, kp_id, resource_type, status='pending')
    raise NotImplementedError


async def get_task_status(task_id: uuid.UUID, db: AsyncSession) -> Optional[GenerateTaskOut]:
    """轮询接口：返回任务当前状态与进度。"""
    # TODO: 查询 generation_task 表
    raise NotImplementedError


async def update_task_progress(
    task_id: uuid.UUID,
    progress: int,
    status: TaskStatus,
    db: AsyncSession,
    error_msg: Optional[str] = None,
    result_id: Optional[uuid.UUID] = None,
) -> None:
    """由 Agent 执行过程中调用，更新进度与状态。"""
    # TODO: UPDATE generation_task SET progress=..., status=..., ... WHERE id=...
    raise NotImplementedError


# ----------------------------------------------------------
# 学习记录
# ----------------------------------------------------------

async def record_learning(
    user_id: uuid.UUID,
    data: LearningRecordCreate,
    db: AsyncSession,
) -> LearningRecordOut:
    """记录用户对某资源的学习行为（时长、评分、反馈）。"""
    # TODO: INSERT INTO learning_record
    raise NotImplementedError


async def list_learning_records(
    user_id: uuid.UUID,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list[LearningRecordOut]:
    """列举用户的学习历史。"""
    # TODO: 查询 learning_record 表
    raise NotImplementedError
