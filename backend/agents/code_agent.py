"""
backend/agents/code_agent.py
CodeAgent：生成代码示例或编程练习题（含参考答案）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


SYSTEM_PROMPT = """你是一位编程教学专家。
请为以下知识点生成一个代码示例或编程练习，要求：
- 使用 Python（除非学生有特殊要求）
- 代码包含详细注释
- 先给出题目描述，再给出参考答案
- 若是练习题，在答案前用 "# ===== 参考答案 =====" 分隔

以 Markdown 代码块格式输出。

参考资料：
{context}

知识点：{kp_name}
学生画像：{profile_summary}
"""


async def run(state: AgentState) -> AgentState:
    """
    CodeAgent 节点入口。

    职责：
    1. 检索相关文档和代码示例
    2. 调用 LLM 生成代码内容
    3. 写入 state.draft_content

    :param state: 当前状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. 检索 context（可优先检索包含代码的文档块）
    # 2. profile_summary = build_profile_context(state.profile)
    # 3. prompt = SYSTEM_PROMPT.format(...)
    # 4. state.draft_content = await chat_completion(messages)
    raise NotImplementedError
