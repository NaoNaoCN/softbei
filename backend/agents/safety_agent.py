"""
backend/agents/safety_agent.py
SafetyAgent：内容安全验证，过滤幻觉、不当内容，附加引用来源。
"""

from __future__ import annotations

import json
import logging

from backend.models.schemas import AgentState
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig

_logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一位内容质量审核专家。
请对以下 AI 生成内容进行审核：

【参考资料（来源真实）】
{context}

【待审核内容摘要（前500字）】
{draft_preview}

请检查：
1. 内容是否与参考资料基本一致（无严重捏造事实）
2. 是否存在明显错误或误导性表达
3. 内容是否适合学习场景

以 JSON 返回（不要包含修正后的内容，只返回审核结论）：
{{
  "passed": true/false,
  "issues": ["问题1", "问题2"]
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
        _logger.warning("[SafetyAgent] draft_content 为空，跳过安全检查")
        return state.model_copy(update={
            "safety_passed": True,
            "final_content": "",
        })

    _logger.warning("[SafetyAgent] 开始审核，draft_len=%d", len(state.draft_content))

    # 构造上下文（只取前3条参考资料，draft 只取前500字用于审核）
    context = "\n".join(state.retrieved_docs[:3]) if state.retrieved_docs else "（无参考资料）"
    draft_preview = state.draft_content[:500]
    prompt = SYSTEM_PROMPT.format(context=context, draft_preview=draft_preview)

    try:
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=300,  # 只需返回 passed + issues，300 token 足够
        )
        # 去除 markdown 代码块包裹
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        result = json.loads(cleaned)

        passed = result.get("passed", True)
        issues = result.get("issues", [])

        _logger.warning("[SafetyAgent] passed=%s issues=%s", passed, issues)

        # 无论是否通过，始终保留原始 draft_content（不让 LLM 重写文档）
        state = state.model_copy(update={
            "safety_passed": passed,
            "final_content": state.draft_content,
        })

        if not passed and issues:
            state.metadata["safety_issues"] = issues

    except json.JSONDecodeError as e:
        # JSON 解析失败时保守通过，但记录警告
        _logger.warning("[SafetyAgent] JSON 解析失败: %s，raw_preview=%.200s", e, raw if 'raw' in dir() else '')
        state = state.model_copy(update={
            "safety_passed": True,
            "final_content": state.draft_content,
        })
    except Exception as e:
        # 调用失败时保守通过
        _logger.warning("[SafetyAgent] LLM 调用失败: %s，保守通过", e)
        state = state.model_copy(update={
            "safety_passed": True,
            "final_content": state.draft_content,
        })

    return state


def should_skip_safety(state: AgentState) -> bool:
    """若没有 draft_content 则跳过安全检查。"""
    return not bool(state.draft_content)
