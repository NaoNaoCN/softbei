"""
backend/agents/mindmap_agent.py
MindmapAgent：生成思维导图数据（ECharts tree 格式 JSON）。
"""

from __future__ import annotations

import json

from backend.models.schemas import AgentState
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services.llm import chat_completion


SYSTEM_PROMPT = """你是一位思维导图设计专家。
请根据知识点和参考资料，生成一份适合 ECharts tree 图表的 JSON 数据。
格式要求（严格 JSON，不含任何 Markdown 标记）：
{{
  "name": "知识点名称",
  "children": [
    {{
      "name": "子概念1",
      "children": [...]
    }},
    ...
  ]
}}

参考资料：
{context}

知识点：{kp_name}
层级深度：不超过 4 层，每节点子项不超过 6 个。
"""


async def run(state: AgentState, config: dict | None = None) -> AgentState:
    """
    MindmapAgent 节点入口。

    职责：
    1. 检索相关文档
    2. 调用 LLM 生成 ECharts tree JSON
    3. 将 JSON 字符串存入 draft_content
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

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(context=context, kp_name=kp_name)

    try:
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2000,
        )

        # 验证 JSON 合法性
        try:
            json.loads(raw)
        except json.JSONDecodeError:
            # 如果不是合法 JSON，尝试提取 JSON 部分
            import re
            match = re.search(r"\{[\s\S]*\}", raw)
            if match:
                raw = match.group(0)
                json.loads(raw)  # 再验证一次

        state = state.model_copy(update={"draft_content": raw})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"思维导图生成失败：{e}"})

    return state
