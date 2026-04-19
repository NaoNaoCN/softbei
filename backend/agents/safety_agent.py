"""
backend/agents/safety_agent.py
SafetyAgent：内容安全验证，过滤幻觉、不当内容，附加引用来源。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


SYSTEM_PROMPT = """你是一位内容质量审核专家。
请对以下 AI 生成内容进行审核：

【参考资料（来源真实）】
{context}

【待审核内容】
{draft}

请检查：
1. 内容是否与参考资料一致（无捏造事实）
2. 是否存在明显错误或误导性表达
3. 内容是否适合学习场景

以 JSON 返回：
{{
  "passed": true/false,
  "issues": ["问题1", "问题2"],
  "revised_content": "修正后内容（若 passed=false）或 null"
}}
"""


async def run(state: AgentState) -> AgentState:
    """
    SafetyAgent 节点入口。

    职责：
    1. 将 draft_content 与 retrieved_docs 对比
    2. 调用 LLM 审核内容质量
    3. 若通过：state.final_content = state.draft_content
       若不通过：state.final_content = revised_content，state.safety_passed = False

    :param state: 当前状态
    :return:      更新后的状态（含 final_content, safety_passed）
    """
    # TODO:
    # 1. context = "\n".join(state.retrieved_docs[:3])
    # 2. prompt = SYSTEM_PROMPT.format(context=context, draft=state.draft_content)
    # 3. result = json.loads(await chat_completion([system, user], temperature=0.1))
    # 4. state.safety_passed = result["passed"]
    # 5. state.final_content = result["revised_content"] or state.draft_content
    raise NotImplementedError


def should_skip_safety(state: AgentState) -> bool:
    """若没有 draft_content 则跳过安全检查。"""
    return not bool(state.draft_content)
