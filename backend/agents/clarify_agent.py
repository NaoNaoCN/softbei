"""
backend/agents/clarify_agent.py
ClarifyAgent：针对用户追问/澄清请求，基于对话历史给出简短、针对性的回答。
不重新生成完整文档，直接对话式回复。
"""

from __future__ import annotations

from backend.models.schemas import AgentState
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig


SYSTEM_PROMPT = """你是一个学习辅导助手。学生正在对之前的对话内容进行追问或请求澄清。

你的任务：
- 基于对话历史，针对学生的追问给出简短、准确的回答
- 不要重新生成完整的学习文档或资源
- 回答要有针对性，直接解答学生的疑问
- 如果对话历史中有相关内容，引用并展开解释
- 保持回答简洁明了，像一个耐心的老师在回答学生的课堂提问

学生画像信息：
{profile_ctx}"""


async def run(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    ClarifyAgent 节点入口。

    职责：
    1. 基于 chat_history 和 user_message 生成针对性回答
    2. 写入 state.final_content
    3. 直接到 END，跳过 safety_agent
    """
    from backend.services import profile as profile_svc

    # 构建画像上下文
    profile_ctx = ""
    if state.profile:
        profile_ctx = await profile_svc.build_profile_context(state.profile)

    prompt = SYSTEM_PROMPT.format(profile_ctx=profile_ctx if profile_ctx else "暂无")

    messages = [
        {"role": "system", "content": prompt},
    ]
    # 注入对话历史
    messages.extend(state.chat_history)
    messages.append({"role": "user", "content": state.user_message})

    try:
        response = await chat_completion(messages, temperature=0.7)
        state = state.model_copy(update={"final_content": response})
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning(f"[ClarifyAgent] LLM 调用失败: {e}")
        state = state.model_copy(update={
            "final_content": "抱歉，我暂时无法回答这个问题，请稍后再试。",
            "error": str(e),
        })

    return state
