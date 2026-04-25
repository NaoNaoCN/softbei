"""
backend/services/resource.py
学习资源服务：元数据管理、生成任务跟踪、学习记录。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.crud import select_one, select, insert, update_by_id, delete_by_id
from backend.db.models import ResourceMeta, GenerationTask, LearningRecord
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
    resource = await select_one(db, ResourceMeta, filters={"id": resource_id})
    if not resource:
        return None
    return ResourceMetaOut(
        id=resource.id,
        user_id=resource.user_id,
        kp_id=resource.kp_id,
        resource_type=resource.resource_type,
        title=resource.title or "",
        content_path=resource.content,
        content_json=resource.content_json,
        created_at=resource.created_at,
    )


async def list_resources(
    user_id: uuid.UUID,
    db: AsyncSession,
    resource_type: Optional[str] = None,
    kp_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> list[ResourceMetaOut]:
    """分页列举用户的资源，可按类型或知识点过滤。"""
    filters = {"user_id": user_id}
    if resource_type:
        filters["resource_type"] = resource_type
    if kp_id:
        filters["kp_id"] = kp_id

    resources = await select(
        db, ResourceMeta,
        filters=filters,
        limit=limit,
        offset=skip,
    )
    return [
        ResourceMetaOut(
            id=r.id,
            user_id=r.user_id,
            kp_id=r.kp_id,
            resource_type=r.resource_type,
            title=r.title or "",
            content_path=r.content,
            content_json=r.content_json,
            created_at=r.created_at,
        )
        for r in resources
    ]


async def delete_resource(resource_id: uuid.UUID, db: AsyncSession) -> bool:
    """物理删除资源元数据（级联删除 quiz_item 等）。"""
    return await delete_by_id(db, ResourceMeta, resource_id)


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
    # 先创建资源记录
    resource = await insert(
        db, ResourceMeta,
        data={
            "user_id": user_id,
            "kp_id": request.kp_id,
            "resource_type": request.resource_type.value,
            "title": f"{request.resource_type.value} - {request.kp_id}",
        },
        commit=False,
    )
    await db.flush()  # 确保 resource.id 已生成

    # 创建任务记录
    task = await insert(
        db, GenerationTask,
        data={
            "resource_id": resource.id,
            "status": TaskStatus.pending.value,
            "progress": 0,
        },
    )
    return GenerateTaskOut(
        task_id=task.id,
        status=TaskStatus.pending,
        progress=0,
    )


async def get_task_status(task_id: uuid.UUID, db: AsyncSession) -> Optional[GenerateTaskOut]:
    """轮询接口：返回任务当前状态与进度。"""
    task = await select_one(db, GenerationTask, filters={"id": task_id})
    if not task:
        return None
    return GenerateTaskOut(
        task_id=task.id,
        status=TaskStatus(task.status),
        progress=task.progress,
        error_msg=task.error_message,
        result_id=task.resource_id,
    )


async def update_task_progress(
    task_id: uuid.UUID,
    progress: int,
    status: TaskStatus,
    db: AsyncSession,
    error_msg: Optional[str] = None,
    result_id: Optional[uuid.UUID] = None,
) -> None:
    """由 Agent 执行过程中调用，更新进度与状态。"""
    update_data = {"progress": progress, "status": status.value}
    if error_msg is not None:
        update_data["error_message"] = error_msg
    if result_id is not None:
        update_data["resource_id"] = result_id
    await update_by_id(db, GenerationTask, task_id, update_data)


# ----------------------------------------------------------
# 学习记录
# ----------------------------------------------------------

async def record_learning(
    user_id: uuid.UUID,
    data: LearningRecordCreate,
    db: AsyncSession,
) -> LearningRecordOut:
    """记录用户对某资源的学习行为（时长、评分、反馈）。"""
    record = await insert(
        db, LearningRecord,
        data={
            "user_id": user_id,
            "resource_id": data.resource_id,
            "action": "view",
            "duration_seconds": data.duration_seconds,
        },
    )
    return LearningRecordOut(
        id=record.id,
        user_id=record.user_id,
        resource_id=record.resource_id,
        duration_seconds=record.duration_seconds,
        rating=data.rating,
        feedback=data.feedback,
        created_at=record.recorded_at,
    )


async def list_learning_records(
    user_id: uuid.UUID,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list[LearningRecordOut]:
    """列举用户的学习历史。"""
    records = await select(
        db, LearningRecord,
        filters={"user_id": user_id},
        limit=limit,
        offset=skip,
    )
    return [
        LearningRecordOut(
            id=r.id,
            user_id=r.user_id,
            resource_id=r.resource_id,
            duration_seconds=r.duration_seconds,
            created_at=r.recorded_at,
        )
        for r in records
    ]
