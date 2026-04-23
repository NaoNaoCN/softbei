"""
backend/agents/planner_agent.py
PlannerAgent：解析用户意图，决定生成哪种资源类型并确定目标知识点。
"""

from __future__ import annotations

import json

from backend.models.schemas import AgentState, ResourceType
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion


SYSTEM_PROMPT = """你是一个学习计划分析助手。
根据学生的问题和画像，判断：
1. 学生想要生成什么类型的学习资源（doc/mindmap/quiz/code/summary）
2. 目标知识点 ID（从以下可用知识点中选择）

可用知识点：
{kp_list}

以 JSON 格式返回：{{"resource_type": "...", "kp_id": "..."}}
若无法判断，resource_type 设为 null。
"""


async def run(state: AgentState, config: dict | None = None) -> AgentState:
    """
    PlannerAgent 节点入口。

    职责：
    1. 结合 user_message 和 profile 分析意图
    2. 确定 resource_type 和 kp_id
    3. 写入 state 供后续 Agent 使用
    """
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
    prompt = SYSTEM_PROMPT.format(kp_list=kp_list or "（无可用知识点）")
    messages = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": f"学生画像：{profile_ctx}\n\n学生需求：{state.user_message}"},
    ]

    try:
        raw = await chat_completion(messages, temperature=0.1)
        result = json.loads(raw)
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
    except (json.JSONDecodeError, Exception):
        # 解析失败时不设置，保持 state 原样
        pass

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
    }
    if state.resource_type and state.resource_type in mapping:
        return mapping[state.resource_type]
    return "recommend_agent"  # 默认推荐
