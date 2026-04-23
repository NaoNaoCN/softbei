"""
backend/db/crud.py
数据库基础增删改查封装（基于 SQLAlchemy 异步会话）。
"""

from __future__ import annotations

from typing import Any, Sequence, TypeVar

from sqlalchemy import select as sa_select, delete as sa_delete, update as sa_update, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.db.database import get_session

ModelT = TypeVar("ModelT")


async def insert(
    session: AsyncSession,
    model: type[ModelT],
    data: dict[str, Any],
    commit: bool = True,
) -> ModelT:
    """
    插入单条记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        data: 要插入的字段数据字典
        commit: 是否立即提交，默认 True

    Returns:
        新创建的模型实例
    """
    instance = model(**data)
    session.add(instance)
    if commit:
        await session.commit()
        await session.refresh(instance)
    return instance


async def insert_many(
    session: AsyncSession,
    model: type[ModelT],
    data_list: list[dict[str, Any]],
    commit: bool = True,
) -> list[ModelT]:
    """
    批量插入多条记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        data_list: 要插入的字段数据字典列表
        commit: 是否立即提交，默认 True

    Returns:
        新创建模型实例列表
    """
    instances = [model(**data) for data in data_list]
    session.add_all(instances)
    if commit:
        await session.commit()
    return instances


async def select(
    session: AsyncSession,
    model: type[ModelT],
    filters: dict[str, Any] | None = None,
    order_by: Any | None = None,
    limit: int | None = None,
    offset: int | None = None,
    loadRelations: list[str] | None = None,
) -> Sequence[ModelT]:
    """
    查询记录列表。

    Args:
        session: 数据库会话
        model: ORM 模型类
        filters: 过滤条件字典，键为字段名，值为过滤值
        order_by: 排序字段，如 User.username 或 desc(User.id)
        limit: 返回条数限制
        offset: 跳过条数
        loadRelations: 预加载的关系属性名列表

    Returns:
        模型实例序列
    """
    stmt = sa_select(model)

    if loadRelations:
        for rel in loadRelations:
            # 支持嵌套路径如 "items.kp"，也支持普通关系名
            rel_path = rel.split(".")
            if len(rel_path) == 1:
                stmt = stmt.options(selectinload(getattr(model, rel)))
            else:
                # 多层嵌套：items.kp -> items，然后 items.kp
                stmt = stmt.options(selectinload(rel_path[0]).selectinload(rel_path[1]))

    if filters:
        for key, value in filters.items():
            if value is None:
                stmt = stmt.where(getattr(model, key).is_(None))
            else:
                stmt = stmt.where(getattr(model, key) == value)

    if order_by is not None:
        stmt = stmt.order_by(order_by)

    if limit is not None:
        stmt = stmt.limit(limit)

    if offset is not None:
        stmt = stmt.offset(offset)

    result = await session.execute(stmt)
    return result.scalars().all()


async def select_one(
    session: AsyncSession,
    model: type[ModelT],
    filters: dict[str, Any] | None = None,
    loadRelations: list[str] | None = None,
) -> ModelT | None:
    """
    查询单条记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        filters: 过滤条件字典
        loadRelations: 预加载的关系属性名列表

    Returns:
        模型实例或 None
    """
    results = await select(
        session, model, filters=filters, limit=1, loadRelations=loadRelations
    )
    return results[0] if results else None


async def select_by_id(
    session: AsyncSession,
    model: type[ModelT],
    id: Any,
    loadRelations: list[str] | None = None,
) -> ModelT | None:
    """
    根据主键 ID 查询单条记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        id: 主键值
        loadRelations: 预加载的关系属性名列表

    Returns:
        模型实例或 None
    """
    return await select_one(
        session, model, filters={"id": id}, loadRelations=loadRelations
    )


async def count(
    session: AsyncSession,
    model: type[ModelT],
    filters: dict[str, Any] | None = None,
) -> int:
    """
    统计符合条件的记录数量。

    Args:
        session: 数据库会话
        model: ORM 模型类
        filters: 过滤条件字典

    Returns:
        记录数量
    """
    stmt = sa_select(func.count()).select_from(model)

    if filters:
        for key, value in filters.items():
            if value is None:
                stmt = stmt.where(getattr(model, key).is_(None))
            else:
                stmt = stmt.where(getattr(model, key) == value)

    result = await session.execute(stmt)
    return result.scalar() or 0


async def update_(
    session: AsyncSession,
    model: type[ModelT],
    filters: dict[str, Any],
    data: dict[str, Any],
    commit: bool = True,
) -> int:
    """
    更新符合条件的记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        filters: 过滤条件字典
        data: 要更新的字段数据字典
        commit: 是否立即提交，默认 True

    Returns:
        实际更新的记录数
    """
    stmt = sa_update(model)
    for key, value in filters.items():
        if value is None:
            stmt = stmt.where(getattr(model, key).is_(None))
        else:
            stmt = stmt.where(getattr(model, key) == value)
    stmt = stmt.values(**data)

    result = await session.execute(stmt)
    if commit:
        await session.commit()
    return result.rowcount


async def update_by_id(
    session: AsyncSession,
    model: type[ModelT],
    id: Any,
    data: dict[str, Any],
    commit: bool = True,
) -> bool:
    """
    根据主键 ID 更新记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        id: 主键值
        data: 要更新的字段数据字典
        commit: 是否立即提交，默认 True

    Returns:
        是否更新了记录
    """
    rows = await update_(session, model, filters={"id": id}, data=data, commit=commit)
    return rows > 0


async def delete(
    session: AsyncSession,
    model: type[ModelT],
    filters: dict[str, Any],
    commit: bool = True,
) -> int:
    """
    删除符合条件的记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        filters: 过滤条件字典
        commit: 是否立即提交，默认 True

    Returns:
        实际删除的记录数
    """
    stmt = sa_delete(model)
    for key, value in filters.items():
        if value is None:
            stmt = stmt.where(getattr(model, key).is_(None))
        else:
            stmt = stmt.where(getattr(model, key) == value)

    result = await session.execute(stmt)
    if commit:
        await session.commit()
    return result.rowcount


async def delete_by_id(
    session: AsyncSession,
    model: type[ModelT],
    id: Any,
    commit: bool = True,
) -> bool:
    """
    根据主键 ID 删除记录。

    Args:
        session: 数据库会话
        model: ORM 模型类
        id: 主键值
        commit: 是否立即提交，默认 True

    Returns:
        是否删除了记录
    """
    rows = await delete(session, model, filters={"id": id}, commit=commit)
    return rows > 0
