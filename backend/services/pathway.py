"""
backend/services/pathway.py
学习路径服务：LearningPath 和 LearningPathItem 的 CRUD 操作。
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.crud import (
    select,
    select_one,
    insert,
    update_by_id,
    delete,
    delete_by_id,
)
from backend.db.models import LearningPath, LearningPathItem
from backend.models.schemas import (
    LearningPathCreate,
    LearningPathUpdate,
    LearningPathItemCreate,
    LearningPathItemUpdate,
    LearningPathOut,
    LearningPathItemOut,
)


# ----------------------------------------------------------
# 学习路径（LearningPath）
# ----------------------------------------------------------

async def get_pathway(
    path_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[LearningPathOut]:
    """按 ID 获取单条学习路径。"""
    path = await select_one(
        db, LearningPath,
        filters={"id": path_id},
        loadRelations=["items.kp"],
    )
    if not path:
        return None
    return _path_to_out(path)


async def list_pathways(
    user_id: uuid.UUID,
    db: AsyncSession,
) -> list[LearningPathOut]:
    """列举用户的所有学习路径。"""
    paths = await select(
        db, LearningPath,
        filters={"user_id": user_id},
        loadRelations=["items.kp"],
    )
    return [_path_to_out(p) for p in paths]


async def create_pathway(
    user_id: uuid.UUID,
    data: LearningPathCreate,
    db: AsyncSession,
) -> LearningPathOut:
    """创建新学习路径。"""
    path = await insert(
        db, LearningPath,
        data={"user_id": user_id, "title": data.name, "description": data.description},
    )
    return LearningPathOut(
        id=path.id,
        name=path.title or "",
        description=path.description,
        items=[],
        created_at=path.created_at,
    )


async def update_pathway(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    data: LearningPathUpdate,
    db: AsyncSession,
) -> Optional[LearningPathOut]:
    """更新学习路径标题/描述。"""
    # 确认归属
    path = await select_one(db, LearningPath, filters={"id": path_id, "user_id": user_id})
    if not path:
        return None
    update_data = {}
    if data.name is not None:
        update_data["title"] = data.name
    if data.description is not None:
        update_data["description"] = data.description
    if not update_data:
        return await get_pathway(path_id, db)

    updated = await update_by_id(db, LearningPath, path_id, update_data)
    if not updated:
        return None
    return await get_pathway(path_id, db)


async def delete_pathway(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """
    删除学习路径（级联删除 items）。
    先删 items 再删 path。
    """
    # 确认归属
    path = await select_one(db, LearningPath, filters={"id": path_id, "user_id": user_id})
    if not path:
        return False
    # 删除关联的 items（按 path_id 过滤）
    await delete(db, LearningPathItem, {"path_id": path_id}, commit=False)
    return await delete_by_id(db, LearningPath, path_id)


# ----------------------------------------------------------
# 学习路径项（LearningPathItem）
# ----------------------------------------------------------

async def add_pathway_item(
    path_id: uuid.UUID,
    user_id: uuid.UUID,
    data: LearningPathItemCreate,
    db: AsyncSession,
) -> Optional[LearningPathItemOut]:
    """向学习路径添加一个知识点项。"""
    # 确认 path 归属正确
    path = await select_one(db, LearningPath, filters={"id": path_id, "user_id": user_id})
    if not path:
        return None

    item = await insert(
        db, LearningPathItem,
        data={
            "path_id": path_id,
            "kp_id": data.kp_id,
            "order_index": data.order_index,
        },
    )
    return LearningPathItemOut(
        id=item.id,
        order_index=item.order_index,
        kp_id=item.kp_id,
        kp_name=item.kp_id,  # kp.name 需额外查询，此处先用 kp_id
        is_completed=item.is_completed,
    )


async def update_pathway_item(
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    data: LearningPathItemUpdate,
    db: AsyncSession,
) -> Optional[LearningPathItemOut]:
    """更新学习路径项（顺序/完成状态）。"""
    # 验证归属：item -> path -> user_id
    item = await select_one(db, LearningPathItem, filters={"id": item_id})
    if not item:
        return None
    path = await select_one(db, LearningPath, filters={"id": item.path_id, "user_id": user_id})
    if not path:
        return None

    update_data = {}
    if data.order_index is not None:
        update_data["order_index"] = data.order_index
    if data.is_completed is not None:
        update_data["is_completed"] = data.is_completed
    if not update_data:
        return _item_to_out(item)

    await update_by_id(db, LearningPathItem, item_id, update_data)
    # 重新查询以获取更新后的数据
    updated = await select_one(db, LearningPathItem, filters={"id": item_id})
    return _item_to_out(updated)


async def remove_pathway_item(
    item_id: uuid.UUID,
    user_id: uuid.UUID,
    db: AsyncSession,
) -> bool:
    """从学习路径移除一个知识点项。"""
    item = await select_one(db, LearningPathItem, filters={"id": item_id})
    if not item:
        return False
    path = await select_one(db, LearningPath, filters={"id": item.path_id, "user_id": user_id})
    if not path:
        return False
    return await delete_by_id(db, LearningPathItem, item_id)


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def _item_to_out(item: LearningPathItem) -> LearningPathItemOut:
    return LearningPathItemOut(
        id=item.id,
        order_index=item.order_index,
        kp_id=item.kp_id,
        kp_name=item.kp.name if item.kp else item.kp_id,
        is_completed=item.is_completed,
    )


def _path_to_out(path: LearningPath) -> LearningPathOut:
    items = sorted(path.items, key=lambda x: x.order_index) if path.items else []
    return LearningPathOut(
        id=path.id,
        name=path.title or "",
        description=path.description,
        items=[_item_to_out(i) for i in items],
        created_at=path.created_at,
    )
