"""
backend/agents/planner_agent.py
PlannerAgent：解析用户意图，决定生成哪种资源类型并确定目标知识点。
"""

from __future__ import annotations

from backend.models.schemas import AgentState, ResourceType


SYSTEM_PROMPT = """你是一个学习计划分析助手。
根据学生的问题和画像，判断：
1. 学生想要生成什么类型的学习资源（doc/mindmap/quiz/code/summary）
2. 目标知识点 ID（从知识图谱节点中选择）

以 JSON 格式返回：{"resource_type": "...", "kp_id": "..."}
若无法判断，resource_type 设为 null。
"""


async def run(state: AgentState) -> AgentState:
    """
    PlannerAgent 节点入口。

    职责：
    1. 结合 user_message 和 profile 分析意图
    2. 确定 resource_type 和 kp_id
    3. 写入 state 供后续 Agent 使用

    :param state: 当前状态
    :return:      更新后的状态（含 resource_type, kp_id）
    """
    # TODO:
    # 1. profile_ctx = build_profile_context(state.profile)
    # 2. messages = [system_prompt, user_message + profile_ctx]
    # 3. result = json.loads(await chat_completion(messages))
    # 4. state.resource_type = ResourceType(result["resource_type"])
    # 5. state.kp_id = result["kp_id"]
    raise NotImplementedError


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
