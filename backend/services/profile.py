"""
backend/services/profile.py
学生画像服务：读取、更新、历史版本管理。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import StudentProfileIn, StudentProfileOut


# ----------------------------------------------------------
# 公开接口
# ----------------------------------------------------------

async def get_profile(user_id: uuid.UUID, db: AsyncSession) -> Optional[StudentProfileOut]:
    """
    查询指定用户的当前画像。
    若用户尚未建立画像，返回 None。
    """
    # TODO: 查询 student_profile 表
    raise NotImplementedError


async def create_or_update_profile(
    user_id: uuid.UUID,
    data: StudentProfileIn,
    db: AsyncSession,
) -> StudentProfileOut:
    """
    创建或更新用户画像。
    同时向 profile_history 插入历史快照（版本号自增）。
    """
    # TODO: upsert student_profile，insert profile_history
    raise NotImplementedError


async def get_profile_history(
    user_id: uuid.UUID,
    db: AsyncSession,
    limit: int = 10,
) -> list[StudentProfileOut]:
    """返回用户的画像历史版本列表（倒序）。"""
    # TODO: 查询 profile_history 表
    raise NotImplementedError


async def merge_chat_updates(
    user_id: uuid.UUID,
    updates: dict,
    db: AsyncSession,
) -> StudentProfileOut:
    """
    将 ProfileAgent 从对话中提取的画像字段增量合并进当前画像。
    只更新 updates 中非 None 的字段。
    """
    # TODO: 读取当前画像 -> 合并 -> 保存
    raise NotImplementedError


async def build_profile_context(profile: StudentProfileOut) -> str:
    """
    将画像对象序列化为 prompt 上下文字符串，注入到 Agent System Prompt 中。
    例如：'学生专业：计算机，目标：掌握深度学习基础，薄弱点：反向传播...'
    """
    # TODO: 格式化为自然语言描述
    raise NotImplementedError
