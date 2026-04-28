"""
backend/agents/summary_agent.py
SummaryAgent：生成知识点精简总结（适合复习的要点提炼）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState
from backend.agents.utils import resolve_kp_name
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig


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


async def run(state: AgentState, config: RunnableConfig = None) -> AgentState:
    """
    SummaryAgent 节点入口。

    职责：
    1. 检索相关文档
    2. 调用 LLM 生成复习总结 Markdown
    3. 写入 state.draft_content
    """
    kp_name = await resolve_kp_name(state, config)

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
    prompt = SYSTEM_PROMPT.format(context=context, kp_name=kp_name)

    try:
        draft = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=1200,
        )
        state = state.model_copy(update={"draft_content": draft})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"总结生成失败：{e}"})

    return state
