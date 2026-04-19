"""
backend/agents/mindmap_agent.py
MindmapAgent：生成思维导图数据（ECharts tree 格式 JSON）。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


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


async def run(state: AgentState) -> AgentState:
    """
    MindmapAgent 节点入口。

    职责：
    1. 检索相关文档
    2. 调用 LLM 生成 ECharts tree JSON
    3. 将 JSON 字符串存入 draft_content

    :param state: 当前状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. 检索 + 构造 context
    # 2. prompt = SYSTEM_PROMPT.format(...)
    # 3. raw = await chat_completion(messages, temperature=0.5)
    # 4. json.loads(raw)  # 验证 JSON 合法性
    # 5. state.draft_content = raw
    raise NotImplementedError
