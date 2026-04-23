"""
backend/agents/quiz_agent.py
QuizAgent：生成多题型测验题目集合。
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import AgentState, QuestionType
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services.llm import chat_completion
from backend.db.crud import insert_many
from backend.db.models import QuizItem


SYSTEM_PROMPT = """你是一位出题专家。
请为以下知识点出 {count} 道题目，题型分布：
- 单选题（single）：{single_count} 道
- 多选题（multi）：{multi_count} 道
- 填空题（fill）：{fill_count} 道

以 JSON 数组返回，每道题格式：
{{
  "question_type": "single/multi/fill",
  "difficulty": 1-5,
  "stem": "题干",
  "options": ["A. ...", "B. ..."],  // 填空题为 null
  "answer": "A" 或 ["A","C"] 或 "答案文本",
  "explanation": "解析"
}}

参考资料：
{context}

知识点：{kp_name}
"""


def _get_question_counts(profile) -> tuple[int, int, int]:
    """根据画像决定题目数量分布。"""
    if not profile:
        return 2, 1, 1
    # 根据薄弱知识点数量决定题目量
    weak_count = len(getattr(profile, "knowledge_weak", []) or [])
    if weak_count > 5:
        return 3, 2, 2
    elif weak_count > 2:
        return 2, 1, 1
    return 2, 1, 1


async def run(state: AgentState, config: dict | None = None) -> AgentState:
    """
    QuizAgent 节点入口。

    职责：
    1. 检索知识点相关文档
    2. 调用 LLM 生成题目 JSON 数组
    3. 将题目列表序列化后存入 draft_content
    """
    kp_name = state.kp_id or "未知知识点"

    # 决定题目数量
    total, single, multi = 4, 2, 1
    fill = max(0, total - single - multi)
    if state.profile:
        total, single, multi = _get_question_counts(state.profile)
        fill = max(0, total - single - multi)

    # 检索相关文档
    try:
        chunks = await retrieve_by_kp(kp_name, n_results=5)
        context = format_context(chunks, max_tokens=3000)
        retrieved_texts = [c.text for c in chunks]
    except Exception:
        context = "（暂无参考资料）"
        retrieved_texts = []

    # 更新 retrieved_docs
    state = state.model_copy(update={"retrieved_docs": retrieved_texts})

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(
        count=total,
        single_count=single,
        multi_count=multi,
        fill_count=fill,
        context=context,
        kp_name=kp_name,
    )

    try:
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.6,
            max_tokens=3000,
        )

        # 解析 JSON
        questions = json.loads(raw)
        draft = json.dumps(questions, ensure_ascii=False)
        state = state.model_copy(update={"draft_content": draft})
    except json.JSONDecodeError:
        state = state.model_copy(update={"draft_content": "[]"})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"题目生成失败：{e}"})

    return state


async def save_quiz_items(
    resource_id: str,
    kp_id: str,
    questions: list[dict[str, Any]],
    db: AsyncSession,
) -> None:
    """将题目列表批量写入 quiz_item 表。"""
    if not questions:
        return

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

    try:
        await insert_many(db, QuizItem, data_list=items_data)
    except Exception:
        raise
