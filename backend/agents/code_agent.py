"""
backend/agents/code_agent.py
CodeAgent：生成代码示例或编程练习题（含参考答案）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion


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


async def run(state: AgentState, config: dict | None = None) -> AgentState:
    """
    CodeAgent 节点入口。

    职责：
    1. 检索相关文档和代码示例
    2. 调用 LLM 生成代码内容
    3. 写入 state.draft_content
    """
    kp_name = state.kp_id or "未知知识点"

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

    # 构建画像上下文
    profile_summary = ""
    if state.profile:
        try:
            profile_summary = await profile_svc.build_profile_context(state.profile)
        except Exception:
            profile_summary = "（暂无画像信息）"
    else:
        profile_summary = "（暂无画像信息）"

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(
        context=context,
        kp_name=kp_name,
        profile_summary=profile_summary,
    )

    try:
        draft = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=3000,
        )
        state = state.model_copy(update={"draft_content": draft})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"代码生成失败：{e}"})

    return state
