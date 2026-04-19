"""
backend/agents/doc_agent.py
DocAgent：基于 RAG 生成结构化学习文档（Markdown 格式）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


SYSTEM_PROMPT = """你是一位专业的教学资料撰写专家。
请根据提供的参考资料和知识点信息，生成一份结构清晰、内容准确的学习文档。
要求：
- 使用 Markdown 格式，包含标题、正文、例子和小结
- 内容必须基于参考资料，不得捏造
- 在引用参考资料时，以 [n] 形式标注来源编号
- 难度和深度适配学生当前画像

参考资料：
{context}

知识点：{kp_name}
"""


async def run(state: AgentState) -> AgentState:
    """
    DocAgent 节点入口。

    职责：
    1. 调用 retriever 检索知识点相关文档片段
    2. 构造 RAG prompt，调用 LLM 生成 Markdown 文档
    3. 将 draft_content 写入 state

    :param state: 当前状态（含 kp_id, profile）
    :return:      更新后的状态（含 draft_content）
    """
    # TODO:
    # 1. chunks = await retrieve_by_kp(state.kp_id)
    # 2. context = format_context(chunks)
    # 3. state.retrieved_docs = [c.text for c in chunks]
    # 4. prompt = SYSTEM_PROMPT.format(context=context, kp_name=...)
    # 5. state.draft_content = await chat_completion([system, user])
    raise NotImplementedError
