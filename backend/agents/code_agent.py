"""
backend/agents/code_agent.py
CodeAgent：生成代码示例或编程练习题（含参考答案）。
"""

from __future__ import annotations

import logging

from backend.models.schemas import AgentState
from backend.agents.utils import resolve_kp_name
from backend.rag.retriever import retrieve_by_kp, format_context
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig

logger = logging.getLogger(__name__)


SYSTEM_PROMPT = """你是一位编程教学专家。
请为以下知识点生成一个编程练习（含完整参考答案），要求：
- 使用 Python（除非学生有特殊要求）
- 题目描述简洁明了，控制在 10 行以内，不要过度展开
- 参考答案必须是完整可运行的代码，包含详细注释
- 用 "# ===== 参考答案 =====" 分隔题目和答案
- 答案代码是最重要的部分，必须完整输出，不得省略

输出格式（Markdown）：
## 题目描述
（简要描述题目要求）

# ===== 参考答案 =====
```python
（完整的参考答案代码）
```

参考资料：
{context}

知识点：{kp_name}
学生画像：{profile_summary}
"""


async def run(state: AgentState, config: RunnableConfig = None) -> AgentState:
    """
    CodeAgent 节点入口。

    职责：
    1. 检索相关文档和代码示例
    2. 调用 LLM 生成代码内容
    3. 写入 state.draft_content
    """
    kp_name = await resolve_kp_name(state, config)

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
            max_tokens=5000,
        )
        logger.info(
            "[code_agent] draft_len=%d has_fence=%s preview=%.200s",
            len(draft), "```" in draft, draft,
        )
        state = state.model_copy(update={"draft_content": draft})
    except Exception as e:
        state = state.model_copy(update={"draft_content": f"代码生成失败：{e}"})

    return state
