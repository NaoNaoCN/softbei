"""
backend/agents/doc_agent.py
DocAgent：基于 RAG 生成结构化学习文档（Markdown 格式）。
"""

from __future__ import annotations

import asyncio
import json

from loguru import logger  # noqa: F401

from backend.config import config as app_config
from backend.models.schemas import AgentState
from backend.agents.utils import resolve_kp_name, retrieve_context
from backend.services.llm import chat_completion
from backend.services.video_search import search_videos, inject_video_citations
from langchain_core.runnables import RunnableConfig

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
    logger.info(f"[DocAgent] kp_name={kp_name}")
    # 检索相关文档
    context, retrieved_texts = await retrieve_context(kp_name, state.user_id, "DocAgent")

    # 更新 retrieved_docs
    state = state.model_copy(update={"retrieved_docs": retrieved_texts})

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(context=context, kp_name=kp_name)

    try:
        draft, videos = await asyncio.gather(
            chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=app_config.agents.doc.temperature,
                max_tokens=app_config.agents.doc.max_tokens,
            ),
            search_videos(kp_name),
        )
        # 后处理：注入视频引用
        if videos:
            draft = inject_video_citations(draft, videos)
        logger.info("[DocAgent] 文档生成成功，draft_len=%d, videos=%d" % (len(draft), len(videos)))
        state = state.model_copy(update={
            "draft_content": draft,
            "metadata": {**state.metadata, "video_refs": [v.model_dump() for v in videos]},
        })
    except Exception as e:
        logger.error("[DocAgent] 生成失败: %s" % e)
        state = state.model_copy(update={"draft_content": f"文档生成失败：{e}"})

    return state
