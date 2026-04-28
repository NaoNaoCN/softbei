"""
backend/agents/planner_agent.py
PlannerAgent：解析用户意图，决定生成哪种资源类型并确定目标知识点。
"""

from __future__ import annotations

import json

from backend.models.schemas import AgentState, ResourceType
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig


SYSTEM_PROMPT = """你是一个学习计划分析助手。
根据学生的问题和画像，判断：
1. 学生想要生成什么类型的学习资源：
   - doc: 学习文档（默认，当学生想学习某个知识点时）
   - mindmap: 思维导图（当学生想要知识结构概览时）
   - quiz: 测验题目（当学生想测试自己时）
   - code: 代码示例（当学生想看代码实现时）
   - summary: 知识总结（当学生想要复习总结时）
   - kg: 知识图谱构建（当学生想构建知识图谱、分析知识结构时）
2. 目标知识点名称（从学生消息中提取）

{kp_list_section}

以 JSON 格式返回：{{"resource_type": "doc", "kp_id": "知识点名称"}}
resource_type 不能为 null，如果无法判断具体类型，默认使用 "doc"。
kp_id 使用学生提到的知识点名称，如"多层感知机"、"反向传播"等。
只返回 JSON，不要包含其他内容。"""


async def run(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    PlannerAgent 节点入口。

    职责：
    1. 结合 user_message 和 profile 分析意图
    2. 确定 resource_type 和 kp_id
    3. 写入 state 供后续 Agent 使用

    如果 state 中已预设了 resource_type 和 kp_id（直接生成模式），跳过 LLM 分析。
    """
    # 如果已经预设了 resource_type 和 kp_id，直接跳过
    if state.resource_type and state.kp_id:
        import logging
        logging.getLogger(__name__).warning(
            f"[PlannerAgent] 跳过分析（已预设 resource_type={state.resource_type}, kp_id={state.kp_id}）"
        )
        return state
    # 从 config 中获取 db
    db = None
    if config and "configurable" in config:
        db = config["configurable"].get("db")

    # -- 1. 构建画像上下文 --
    profile_ctx = ""
    if state.profile:
        profile_ctx = await profile_svc.build_profile_context(state.profile)

    # -- 2. 获取可用知识点列表 --
    kp_list = ""
    if db:
        try:
            from backend.db.crud import select as db_select
            from backend.db.models import KGNode
            nodes = await db_select(db, KGNode)
            kp_list = "\n".join([f"- {n.id}: {n.name}" for n in nodes])
        except Exception:
            kp_list = "（知识点列表获取失败）"

    # -- 3. 调用 LLM 分析意图 --
    kp_section = ""
    if kp_list:
        kp_section = f"可用知识点（优先从中选择）：\n{kp_list}"
    prompt = SYSTEM_PROMPT.format(kp_list_section=kp_section)
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"学生画像：{profile_ctx}\n\n学生需求：{state.user_message}"},
    ]

    try:
        raw = await chat_completion(messages, temperature=0.1)
        # 处理 markdown 代码块包裹的 JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        result = json.loads(cleaned)
        resource_type_str = result.get("resource_type")
        kp_id = result.get("kp_id")

        # 设置 resource_type
        if resource_type_str:
            try:
                state = state.model_copy(update={"resource_type": ResourceType(resource_type_str)})
            except ValueError:
                state = state.model_copy(update={"resource_type": None})

        # 设置 kp_id
        if kp_id:
            state = state.model_copy(update={"kp_id": kp_id})
    except (json.JSONDecodeError, Exception) as e:
        import logging
        logging.getLogger(__name__).warning(f"[PlannerAgent] LLM 解析失败: {e}, raw={raw if 'raw' in dir() else 'N/A'}")
        # 解析失败时默认生成文档
        state = state.model_copy(update={"resource_type": ResourceType.doc})

    # 确保 resource_type 有值
    if not state.resource_type:
        state = state.model_copy(update={"resource_type": ResourceType.doc})

    # 确保 kp_id 有值（从用户消息中截取）
    if not state.kp_id:
        state = state.model_copy(update={"kp_id": state.user_message[:50]})

    import logging
    logging.getLogger(__name__).warning(f"[PlannerAgent] resource_type={state.resource_type}, kp_id={state.kp_id}")

    return state


def route_by_resource_type(state: AgentState) -> str:
    """
    LangGraph 条件路由：根据 resource_type 决定下一个 Agent 节点名称。
    返回值需与 graph.py 中注册的节点名对应。
    """
    mapping = {
        ResourceType.doc: "doc_agent",
        ResourceType.mindmap: "mindmap_agent",
        ResourceType.quiz: "quiz_agent",
        ResourceType.code: "code_agent",
        ResourceType.summary: "summary_agent",
        ResourceType.kg: "kg_agent",
    }
    if state.resource_type and state.resource_type in mapping:
        return mapping[state.resource_type]
    return "recommend_agent"  # 默认推荐
