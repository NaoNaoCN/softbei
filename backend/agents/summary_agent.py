"""
backend/agents/summary_agent.py
SummaryAgent：生成知识点精简总结（适合复习的要点提炼）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


SYSTEM_PROMPT = """你是一位学习总结专家。
请根据参考资料，为以下知识点生成一份简洁的复习总结，要求：
- 使用要点式 Markdown（无序列表 + 加粗重点词）
- 控制在 300-500 字以内
- 突出核心概念、常见误区和记忆技巧
- 若知识点有公式，用 LaTeX 格式列出

参考资料：
{context}

知识点：{kp_name}
"""


async def run(state: AgentState) -> AgentState:
    """
    SummaryAgent 节点入口。

    职责：
    1. 检索相关文档
    2. 调用 LLM 生成复习总结 Markdown
    3. 写入 state.draft_content

    :param state: 当前状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. chunks = await retrieve_by_kp(state.kp_id)
    # 2. context = format_context(chunks)
    # 3. state.draft_content = await chat_completion(messages, max_tokens=800)
    raise NotImplementedError
