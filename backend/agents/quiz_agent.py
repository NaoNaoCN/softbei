"""
backend/agents/quiz_agent.py
QuizAgent：生成多题型测验题目集合。
"""

from __future__ import annotations

import json
from typing import Any

from backend.models.schemas import AgentState, QuestionType


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


async def run(state: AgentState) -> AgentState:
    """
    QuizAgent 节点入口。

    职责：
    1. 检索知识点相关文档
    2. 调用 LLM 生成题目 JSON 数组
    3. 将题目列表序列化后存入 draft_content

    :param state: 当前状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. 检索 context
    # 2. 从 profile 决定题目难度分布
    # 3. prompt = SYSTEM_PROMPT.format(...)
    # 4. raw = await chat_completion(messages, temperature=0.6)
    # 5. questions: list[dict] = json.loads(raw)
    # 6. state.draft_content = json.dumps(questions, ensure_ascii=False)
    raise NotImplementedError


async def save_quiz_items(
    resource_id: str,
    kp_id: str,
    questions: list[dict[str, Any]],
    db: Any,
) -> None:
    """将题目列表批量写入 quiz_item 表。"""
    # TODO: INSERT INTO quiz_item (resource_id, kp_id, ...)
    raise NotImplementedError
