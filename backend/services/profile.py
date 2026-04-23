"""
backend/services/profile.py
学生画像服务：读取、更新、历史版本管理。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.crud import select_one, select, insert, update_by_id
from backend.db.models import StudentProfile, ProfileHistory
from backend.models.schemas import StudentProfileIn, StudentProfileOut


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def get_profile(user_id: uuid.UUID, db: AsyncSession) -> Optional[StudentProfileOut]:
    """
    查询指定用户的当前画像。
    若用户尚未建立画像，返回 None。
    """
    profile = await select_one(
        db, StudentProfile, filters={"user_id": user_id}
    )
    if not profile:
        return None
    return StudentProfileOut.model_validate(profile)


async def create_or_update_profile(
    user_id: uuid.UUID,
    data: StudentProfileIn,
    db: AsyncSession,
) -> StudentProfileOut:
    """
    创建或更新用户画像。
    同时向 profile_history 插入历史快照（版本号自增）。
    """
    existing = await select_one(db, StudentProfile, filters={"user_id": user_id})

    # 序列化当前数据为快照
    if existing:
        snapshot = StudentProfileOut.model_validate(existing).model_dump()
        await insert(db, ProfileHistory, {"profile_id": existing.id, "snapshot": snapshot}, commit=False)

        await update_by_id(
            db, StudentProfile, existing.id,
            data={
                "major": data.major,
                "learning_goal": data.learning_goal,
                "cognitive_style": data.cognitive_style.value if data.cognitive_style else None,
                "daily_time_minutes": data.daily_time_minutes,
                "knowledge_mastered": data.knowledge_mastered,
                "knowledge_weak": data.knowledge_weak,
                "error_prone": data.error_prone,
                "current_progress": data.current_progress,
            }
        )
        await db.refresh(existing)
        return StudentProfileOut.model_validate(existing)
    else:
        # 新建画像
        new_profile = await insert(
            db, StudentProfile,
            data={
                "user_id": user_id,
                "major": data.major,
                "learning_goal": data.learning_goal,
                "cognitive_style": data.cognitive_style.value if data.cognitive_style else None,
                "daily_time_minutes": data.daily_time_minutes,
                "knowledge_mastered": data.knowledge_mastered,
                "knowledge_weak": data.knowledge_weak,
                "error_prone": data.error_prone,
                "current_progress": data.current_progress,
            }
        )
        # 初始化历史
        snapshot = StudentProfileOut.model_validate(new_profile).model_dump()
        await insert(db, ProfileHistory, {"profile_id": new_profile.id, "snapshot": snapshot})
        return StudentProfileOut.model_validate(new_profile)


async def get_profile_history(
    user_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 10,
) -> list[StudentProfileOut]:
    """返回用户的画像历史版本列表（倒序）。"""
    profile = await select_one(db, StudentProfile, filters={"user_id": user_id})
    if not profile:
        return []

    history_records = await select(
        db, ProfileHistory,
        filters={"profile_id": profile.id},
        order_by=ProfileHistory.created_at.desc(),
        limit=limit,
    )
    return [
        StudentProfileOut(**record.snapshot)
        for record in history_records
    ]


async def merge_chat_updates(
    user_id: uuid.UUID,
    updates: dict,
    db: AsyncSession,
) -> StudentProfileOut:
    """
    将 ProfileAgent 从对话中提取的画像字段增量合并进当前画像。
    只更新 updates 中非 None 的字段。
    """
    existing = await select_one(db, StudentProfile, filters={"user_id": user_id})
    if not existing:
        # 不存在则创建新画像
        return await create_or_update_profile(
            user_id,
            StudentProfileIn(
                major=updates.get("major"),
                learning_goal=updates.get("learning_goal"),
                cognitive_style=updates.get("cognitive_style"),
                daily_time_minutes=updates.get("daily_time_minutes"),
                knowledge_mastered=updates.get("knowledge_mastered", []),
                knowledge_weak=updates.get("knowledge_weak", []),
                error_prone=updates.get("error_prone", []),
                current_progress=updates.get("current_progress"),
            ),
            db,
        )

    # 快照当前状态
    snapshot = StudentProfileOut.model_validate(existing).model_dump()
    await insert(db, ProfileHistory, {"profile_id": existing.id, "snapshot": snapshot}, commit=False)

    # 只更新非 None 的字段
    update_data = {}
    for key in ["major", "learning_goal", "cognitive_style", "daily_time_minutes",
                "knowledge_mastered", "knowledge_weak", "error_prone", "current_progress"]:
        if key in updates and updates[key] is not None:
            update_data[key] = updates[key]

    if update_data:
        await update_by_id(db, StudentProfile, existing.id, update_data)
        await db.refresh(existing)

    return StudentProfileOut.model_validate(existing)


async def build_profile_context(profile: StudentProfileOut) -> str:
    """
    将画像对象序列化为 prompt 上下文字符串，注入到 Agent System Prompt 中。
    例如：'学生专业：计算机，目标：掌握深度学习基础，薄弱点：反向传播...'
    """
    parts = []

    if profile.major:
        parts.append(f"学生专业：{profile.major}")
    if profile.learning_goal:
        parts.append(f"学习目标：{profile.learning_goal}")
    if profile.cognitive_style:
        parts.append(f"认知风格：{profile.cognitive_style.value}")
    if profile.daily_time_minutes:
        parts.append(f"每日学习时间：{profile.daily_time_minutes}分钟")
    if profile.knowledge_mastered:
        parts.append(f"已掌握的知识点：{', '.join(profile.knowledge_mastered)}")
    if profile.knowledge_weak:
        parts.append(f"薄弱知识点：{', '.join(profile.knowledge_weak)}")
    if profile.error_prone:
        parts.append(f"容易出错的知识点：{', '.join(profile.error_prone)}")
    if profile.current_progress:
        parts.append(f"当前进度：{profile.current_progress}")

    if not parts:
        return "暂无学生画像信息"
    return "，".join(parts)
