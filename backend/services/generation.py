"""
backend/services/generation.py
资源生成服务：封装 LangGraph Agent 调用与结果持久化。
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

logger = logging.getLogger(__name__)

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

    # -- 兜底：若用户尚无学习路径，自动从推荐创建一条 --
    try:
        recommendations = state.metadata.get("recommendations", []) if state.metadata else []
        if recommendations:
            from backend.services import pathway as pathway_svc
            from backend.models.schemas import LearningPathCreate, LearningPathItemCreate
            from backend.db.models import KGNode

            existing = await pathway_svc.list_pathways(uuid.UUID(user_id), db)
            if not existing:
                new_path = await pathway_svc.create_pathway(
                    uuid.UUID(user_id),
                    LearningPathCreate(name=f"{kp_name} 学习路径"),
                    db,
                )
                if new_path:
                    for i, rec in enumerate(recommendations):
                        rec_kp_id = rec.get("kp_id")
                        if not rec_kp_id:
                            continue
                        node = await select_one(db, KGNode, filters={"id": rec_kp_id})
                        if node:
                            await pathway_svc.add_pathway_item(
                                uuid.UUID(new_path.id),
                                uuid.UUID(user_id),
                                LearningPathItemCreate(kp_id=rec_kp_id, order_index=i),
                                db,
                            )
    except Exception as e:
        logger.warning("[auto_pathway] failed to auto-create pathway: %s", e)


def _parse_code_block(draft: str) -> tuple[str, str]:
    """从 LLM 返回的 Markdown 中提取代码块和语言标识。

    优先提取"参考答案"分隔符之后的代码块；若无分隔符则取最后一个代码块
    （通常最后一个是完整答案，前面的可能是题目中的片段）。
    """
    # 如果有"参考答案"分隔符，只在答案部分搜索
    answer_section = draft
    sep_idx = draft.find("参考答案")
    if sep_idx != -1:
        answer_section = draft[sep_idx:]
        logger.debug("[parse_code] found answer separator at pos %d", sep_idx)

    # 提取所有代码块
    blocks = re.findall(r"```(\w*)\s*\n([\s\S]*?)```", answer_section)
    if blocks:
        lang, code = blocks[-1]  # 取最后一个（最完整的答案）
        lang = lang.strip() or "python"
        code = code.strip()
        logger.debug("[parse_code] extracted lang=%s code_len=%d from %d blocks", lang, len(code), len(blocks))
        return code, lang

    # answer_section 没找到，回退到全文搜索
    if sep_idx != -1:
        blocks = re.findall(r"```(\w*)\s*\n([\s\S]*?)```", draft)
        if blocks:
            lang, code = blocks[-1]
            lang = lang.strip() or "python"
            logger.debug("[parse_code] fallback to full draft, lang=%s", lang)
            return code.strip(), lang

    # 没有代码块标记，整段当作代码
    logger.warning("[parse_code] no fenced code block found, using raw draft")
    return draft.strip(), "python"


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

    logger.info(
        "[persist] type=%s resource_id=%s draft_len=%d draft_preview=%.200s",
        resource_type, resource_id, len(draft), draft,
    )

    if resource_type == ResourceType.mindmap:
        # mindmap 是 JSON，存入 content_json
        try:
            content_json = json.loads(draft)
        except json.JSONDecodeError:
            match = re.search(r"\{[\s\S]*\}", draft)
            content_json = json.loads(match.group(0)) if match else {"tree": {}}
        logger.info("[persist] mindmap content_json keys=%s", list(content_json.keys()))
        await update_by_id(db, ResourceMeta, resource_id, {"content_json": content_json})

    elif resource_type == ResourceType.code:
        # code 需要解析为结构化 JSON 存入 content_json，前端从 content_json.code 读取
        code_text, language = _parse_code_block(draft)
        content_json = {"code": code_text, "language": language}
        logger.info(
            "[persist] code language=%s code_len=%d code_preview=%.120s",
            language, len(code_text), code_text,
        )
        await update_by_id(
            db, ResourceMeta, resource_id,
            {"content": draft, "content_json": content_json},
        )

    else:
        # doc/summary 存为纯文本 content
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
