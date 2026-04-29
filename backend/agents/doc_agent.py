"""
backend/agents/doc_agent.py
DocAgent：基于 RAG 生成结构化学习文档（Markdown 格式）。
"""

from __future__ import annotations

import json
import logging

from backend.models.schemas import AgentState
from backend.agents.utils import resolve_kp_name
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig

_logger = logging.getLogger(__name__)


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


async def run(state: AgentState, config: RunnableConfig = None) -> AgentState:
    """
    DocAgent 节点入口。

    职责：
    1. 调用 retriever 检索知识点相关文档片段
    2. 构造 RAG prompt，调用 LLM 生成 Markdown 文档
    3. 将 draft_content 写入 state
    """
    # 获取 kp_name（从 DB 解析 ID → 名称）
    kp_name = await resolve_kp_name(state, config)
    _logger.info(f"[DocAgent] kp_name={kp_name}")
    # 检索相关文档
    try:
        chunks = await retrieve_by_kp(kp_name, n_results=5)
        context = format_context(chunks, max_tokens=3000)
        retrieved_texts = [c.text for c in chunks]
        if chunks:
            _logger.info(f"[DocAgent] RAG 检索到 {len(chunks)} 条参考资料，将基于课程文档生成内容。")
        else:
            _logger.warning(f"[DocAgent] RAG 未检索到参考资料，将仅依赖 LLM 自身知识生成（质量可能下降）。")
    except Exception as e:
        _logger.warning(f"[DocAgent] RAG 检索异常: {e}，降级为纯 LLM 生成。")
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
            max_tokens=4000,
        )
        state = state.model_copy(update={"draft_content": draft})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"文档生成失败：{e}"})

    return state
