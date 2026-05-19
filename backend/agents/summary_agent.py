"""
backend/agents/summary_agent.py
SummaryAgent：生成知识点精简总结（适合复习的要点提炼）。
"""

from __future__ import annotations

from loguru import logger  # noqa: F401

from backend.config import config
from backend.models.schemas import AgentState
from backend.agents.utils import resolve_kp_name, retrieve_context
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig

SYSTEM_PROMPT = f"""你是一位学习总结专家。
请根据参考资料，为以下知识点生成一份简洁的复习总结，要求：
- 使用要点式 Markdown（无序列表 + 加粗重点词）
- 控制在 {config.agents.summary.target_words_min}-{config.agents.summary.target_words_max} 字以内
- 突出核心概念、常见误区和记忆技巧
- 若知识点有公式，用 LaTeX 格式列出

参考资料：
{{context}}

知识点：{{kp_name}}
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
    logger.info("[SummaryAgent] kp_name=%s", kp_name)

    # 检索相关文档
    context, retrieved_texts = await retrieve_context(kp_name, state.user_id, "SummaryAgent")

    # 更新 retrieved_docs
    state = state.model_copy(update={"retrieved_docs": retrieved_texts})

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(context=context, kp_name=kp_name)

    try:
        draft = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=config.agents.summary.temperature,
            max_tokens=config.agents.summary.max_tokens,
        )
        logger.info("[SummaryAgent] 总结生成成功，draft_len=%d", len(draft))
        state = state.model_copy(update={"draft_content": draft})
    except Exception as e:
        logger.error("[SummaryAgent] 生成失败: %s", e)
        state = state.model_copy(update={"draft_content": f"总结生成失败：{e}"})

    return state
