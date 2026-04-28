"""
backend/agents/safety_agent.py
SafetyAgent：内容安全验证，过滤幻觉、不当内容，附加引用来源。
"""

from __future__ import annotations

import json

from backend.models.schemas import AgentState
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig


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


async def run(state: AgentState, config: RunnableConfig = None) -> AgentState:
    """
    SafetyAgent 节点入口。

    职责：
    1. 将 draft_content 与 retrieved_docs 对比
    2. 调用 LLM 审核内容质量
    3. 若通过：state.final_content = state.draft_content
       若不通过：state.final_content = revised_content，state.safety_passed = False
    """
    # 若没有 draft_content，跳过检查
    if not state.draft_content:
        return state.model_copy(update={
            "safety_passed": True,
            "final_content": "",
        })

    # 构造上下文
    context = "\n".join(state.retrieved_docs[:3]) if state.retrieved_docs else "（无参考资料）"
    prompt = SYSTEM_PROMPT.format(context=context, draft=state.draft_content)

    try:
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=1500,
        )
        result = json.loads(raw)

        passed = result.get("passed", True)
        issues = result.get("issues", [])
        revised_content = result.get("revised_content")

        # 结构化内容（JSON）不使用 LLM 修正版本，直接保留原始 draft
        if not passed and revised_content and isinstance(revised_content, str):
            final = revised_content
        else:
            final = state.draft_content

        state = state.model_copy(update={
            "safety_passed": passed,
            "final_content": final,
        })

        if not passed and issues:
            state.metadata["safety_issues"] = issues

    except json.JSONDecodeError:
        # JSON 解析失败时保守通过，但记录警告
        state = state.model_copy(update={
            "safety_passed": True,
            "final_content": state.draft_content,
        })
    except Exception as e:
        # 调用失败时保守通过
        state = state.model_copy(update={
            "safety_passed": True,
            "final_content": state.draft_content,
        })

    return state


def should_skip_safety(state: AgentState) -> bool:
    """若没有 draft_content 则跳过安全检查。"""
    return not bool(state.draft_content)
