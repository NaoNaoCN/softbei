"""
backend/services/generation.py
资源生成服务：封装 LangGraph Agent 调用与结果持久化。
"""

from __future__ import annotations

import json
import re
import traceback
import uuid

from loguru import logger  # noqa: F401
from sqlalchemy.ext.asyncio import AsyncSession

from backend.agents.graph import get_graph
from backend.db.crud import insert_many, select_one, update_by_id
from backend.db.models import GenerationTask, KGNode, QuizItem, ResourceMeta
from backend.models.schemas import (
    AgentState,
    GenerateRequest,
    LearningPathCreate,
    LearningPathItemCreate,
    ResourceType,
    TaskStatus,
)


async def run_generation(
    task_id: uuid.UUID,
    user_id: str,
    session_id: str,
    request: dict,
) -> None:
    """
    后台资源生成任务：
    1. 调用 LangGraph Agent Pipeline 生成内容
    2. 将内容持久化到 ResourceMeta
    3. quiz 类型需额外批量写入 quiz_item 表
    4. 更新 GenerationTask 状态
    """
    from backend.db.database import _session_factory
    from backend.services import pathway as pathway_svc

    req = GenerateRequest(**request)
    print(f"[run_generation] started task_id={task_id} kp_id={req.kp_id} type={req.resource_type}")

    try:
        async with _session_factory() as db:
            # -- 阶段 1：初始化 AgentState，执行 Agent Pipeline --
            await update_by_id(
                db, GenerationTask, task_id,
                {"status": TaskStatus.running.value, "progress": 10},
            )

            # 解析 kp_id → 知识点名称
            kp_name = req.kp_id
            if req.kp_id.startswith("kp_"):
                node = await select_one(db, KGNode, filters={"id": req.kp_id})
                if node:
                    kp_name = node.name

            initial_state = AgentState(
                user_id=user_id,
                session_id=session_id,
                user_message=f"请生成一份关于 {kp_name} 的 {req.resource_type.value} 学习资源",
                kp_id=req.kp_id,
                resource_type=req.resource_type,
                num_questions=req.num_questions,
                question_type_counts=req.question_type_counts,
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
            resource_type = req.resource_type

            # 检测是否是错误信息（各 agent 失败时写入）
            is_error = (
                draft.startswith("文档生成失败")
                or draft.startswith("思维导图生成失败")
                or draft.startswith("题目生成失败")
                or draft.startswith("代码生成失败")
                or draft.startswith("总结生成失败")
                or not draft
            )

            if is_error and not req.resource_type == ResourceType.quiz:
                await update_by_id(
                    db, GenerationTask, task_id,
                    {"status": TaskStatus.failed.value, "progress": 0, "error_message": draft},
                )
                return

            try:
                if resource_type == ResourceType.quiz:
                    await _persist_quiz(task_id, req.kp_id, draft, db)
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

            # -- 兜底：若用户尚无学习路径，自动从推荐创建一条 --
            try:
                recommendations = (state.metadata or {}).get("recommendations", [])
                if recommendations:
                    valid_recs = []
                    for rec in recommendations:
                        rec_kp_id = rec.get("kp_id")
                        if rec_kp_id and await select_one(db, KGNode, filters={"id": rec_kp_id}):
                            valid_recs.append(rec)

                    if valid_recs:
                        existing = await pathway_svc.list_pathways(uuid.UUID(user_id), db)
                        if not existing:
                            new_path = await pathway_svc.create_pathway(
                                uuid.UUID(user_id),
                                LearningPathCreate(name=f"{kp_name} 学习路径"),
                                db,
                            )
                            if new_path:
                                for i, rec in enumerate(valid_recs):
                                    await pathway_svc.add_pathway_item(
                                        uuid.UUID(new_path.id),
                                        uuid.UUID(user_id),
                                        LearningPathItemCreate(kp_id=rec["kp_id"], order_index=i),
                                        db,
                                    )
            except Exception as e:
                logger.warning("[auto_pathway] failed to auto-create pathway: %s", e)

    except Exception as exc:
        import sys
        import traceback as tb
        tb.print_exc()
        logger.error("[run_generation] unexpected error: %s | %r", exc, exc)


def _parse_code_block(draft: str) -> tuple[str, str]:
    """从 LLM 返回的 Markdown 中提取代码块和语言标识。"""
    answer_section = draft
    sep_idx = draft.find("参考答案")
    if sep_idx != -1:
        answer_section = draft[sep_idx:]

    blocks = re.findall(r"```(\w*)\s*\n([\s\S]*?)```", answer_section)
    if blocks:
        lang, code = blocks[-1]
        lang = lang.strip() or "python"
        code = code.strip()
        return code, lang

    if sep_idx != -1:
        blocks = re.findall(r"```(\w*)\s*\n([\s\S]*?)```", draft)
        if blocks:
            lang, code = blocks[-1]
            lang = lang.strip() or "python"
            return code.strip(), lang

    return draft.strip(), "python"


async def _persist_content(
    task_id: uuid.UUID,
    resource_type: ResourceType,
    draft: str,
    db: AsyncSession,
) -> None:
    """将非 quiz 类型的生成内容写入 ResourceMeta。"""
    task = await select_one(db, GenerationTask, filters={"id": task_id})
    if not task:
        return
    resource_id = task.resource_id

    if resource_type == ResourceType.mindmap:
        try:
            content_json = json.loads(draft)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", draft)
            content_json = json.loads(match.group(0)) if match else {"tree": {}}
        await update_by_id(db, ResourceMeta, resource_id, {"content_json": content_json})

    elif resource_type == ResourceType.code:
        code_text, language = _parse_code_block(draft)
        content_json = {"code": code_text, "language": language}
        await update_by_id(
            db, ResourceMeta, resource_id,
            {"content": draft, "content_json": content_json},
        )

    else:
        await update_by_id(db, ResourceMeta, resource_id, {"content": draft})


async def _persist_quiz(
    task_id: uuid.UUID,
    kp_id: str,
    draft: str,
    db: AsyncSession,
) -> None:
    """解析 quiz JSON，批量写入 quiz_item 表，并存入 ResourceMeta.content_json。"""
    task = await select_one(db, GenerationTask, filters={"id": task_id})
    if not task:
        return
    resource_id = task.resource_id

    try:
        questions = json.loads(draft)
    except json.JSONDecodeError:
        questions = []

    if questions:
        items_data = [
            {
                "resource_id": resource_id,
                "kp_id": kp_id,
                "question_type": q.get("question_type", "single"),
                "stem": q.get("stem", ""),
                "options": q.get("options"),
                "answer": str(q.get("answer", "")),
                "explanation": q.get("explanation"),
                "order_index": i,
            }
            for i, q in enumerate(questions)
        ]
        await insert_many(db, QuizItem, data_list=items_data)

    await update_by_id(
        db, ResourceMeta, resource_id,
        {"content_json": {"items": questions}},
    )
