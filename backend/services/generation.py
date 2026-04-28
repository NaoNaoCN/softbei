"""
backend/services/generation.py
资源生成服务：封装 LangGraph Agent 调用与结果持久化。
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.graph import get_graph
from backend.db.crud import update_by_id, select_one
from backend.db.models import GenerationTask, ResourceMeta, QuizItem
from backend.models.schemas import AgentState, GenerateRequest, ResourceType, TaskStatus


async def run_generation(
    task_id: uuid.UUID,
    user_id: str,
    session_id: str,
    request: GenerateRequest,
    db: AsyncSession,
) -> None:
    """
    后台资源生成任务：
    1. 调用 LangGraph Agent Pipeline 生成内容
    2. 将内容持久化到 ResourceMeta
    3. quiz 类型需额外批量写入 quiz_item 表
    4. 更新 GenerationTask 状态
    """
    # -- 阶段 1：初始化 AgentState，执行 Agent Pipeline --
    await update_by_id(
        db, GenerationTask, task_id,
        {"status": TaskStatus.running.value, "progress": 10},
    )

    # 解析 kp_id → 知识点名称
    kp_name = request.kp_id
    if request.kp_id.startswith("kp_"):
        from backend.db.models import KGNode
        node = await select_one(db, KGNode, filters={"id": request.kp_id})
        if node:
            kp_name = node.name

    initial_state = AgentState(
        user_id=user_id,
        session_id=session_id,
        user_message=f"请生成一份关于 {kp_name} 的 {request.resource_type.value} 学习资源",
        kp_id=request.kp_id,
        resource_type=request.resource_type,
    )

    try:
        result = await get_graph().ainvoke(
            initial_state,
            config={"configurable": {"db": db}},
        )
        state = AgentState(**result)
    except Exception as e:
        await update_by_id(
            db, GenerationTask, task_id,
            {"status": TaskStatus.failed.value, "progress": 0, "error_message": str(e)},
        )
        return

    # -- 阶段 2：内容持久化 --
    await update_by_id(db, GenerationTask, task_id, {"progress": 80})

    draft = state.draft_content or ""
    resource_type = request.resource_type

    # 检测是否是错误信息（各 agent 失败时写入）
    is_error = draft.startswith("文档生成失败") or draft.startswith("思维导图生成失败") \
        or draft.startswith("题目生成失败") or draft.startswith("代码生成失败") \
        or draft.startswith("总结生成失败") or not draft

    if is_error and not request.resource_type == ResourceType.quiz:
        await update_by_id(
            db, GenerationTask, task_id,
            {"status": TaskStatus.failed.value, "progress": 0, "error_message": draft},
        )
        return

    try:
        if resource_type == ResourceType.quiz:
            await _persist_quiz(task_id, request.kp_id, draft, db)
        else:
            await _persist_content(task_id, resource_type, draft, db)
    except Exception as e:
        await update_by_id(
            db, GenerationTask, task_id,
            {"status": TaskStatus.failed.value, "error_message": str(e)},
        )
        return

    # -- 阶段 3：完成 --
    await update_by_id(
        db, GenerationTask, task_id,
        {"status": TaskStatus.done.value, "progress": 100},
    )


async def _persist_content(
    task_id: uuid.UUID,
    resource_type: ResourceType,
    draft: str,
    db: AsyncSession,
) -> None:
    """将非 quiz 类型的生成内容写入 ResourceMeta。"""
    # 找到对应的 resource_id
    task = await select_one(db, GenerationTask, filters={"id": task_id})
    if not task:
        return
    resource_id = task.resource_id

    if resource_type == ResourceType.mindmap:
        # mindmap 是 JSON，存入 content_json
        try:
            content_json = json.loads(draft)
        except json.JSONDecodeError:
            # 尝试提取 JSON 部分
            import re
            match = re.search(r"\{[\s\S]*\}", draft)
            content_json = json.loads(match.group(0)) if match else {"tree": {}}
        await update_by_id(db, ResourceMeta, resource_id, {"content_json": content_json})
    else:
        # doc/summary/code 存为纯文本 content
        await update_by_id(db, ResourceMeta, resource_id, {"content": draft})


async def _persist_quiz(
    task_id: uuid.UUID,
    kp_id: str,
    draft: str,
    db: AsyncSession,
) -> None:
    """
    解析 quiz JSON，批量写入 quiz_item 表，
    并将 items 摘要存入 ResourceMeta.content_json。
    """
    task = await select_one(db, GenerationTask, filters={"id": task_id})
    if not task:
        return
    resource_id = task.resource_id

    try:
        questions = json.loads(draft)
    except json.JSONDecodeError:
        questions = []

    # 批量写入 quiz_item 表
    if questions:
        items_data = []
        for i, q in enumerate(questions):
            items_data.append({
                "resource_id": resource_id,
                "kp_id": kp_id,
                "question_type": q.get("question_type", "single"),
                "stem": q.get("stem", ""),
                "options": q.get("options"),
                "answer": str(q.get("answer", "")),
                "explanation": q.get("explanation"),
                "order_index": i,
            })
        from backend.db.crud import insert_many
        await insert_many(db, QuizItem, data_list=items_data)

    # content_json 存 items 摘要供前端预览
    await update_by_id(
        db, ResourceMeta, resource_id,
        {"content_json": {"items": questions}},
    )
