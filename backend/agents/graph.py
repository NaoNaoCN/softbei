"""
backend/agents/graph.py
LangGraph 主状态机：定义节点、边（含条件路由）并编译图。
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph

from backend.agents import (
    code_agent,
    doc_agent,
    mindmap_agent,
    planner_agent,
    profile_agent,
    quiz_agent,
    recommend_agent,
    safety_agent,
    summary_agent,
)
from backend.models.schemas import AgentState

# ----------------------------------------------------------
# 图构建
# ----------------------------------------------------------

def build_graph() -> StateGraph:
    """
    构建并返回编译后的 LangGraph 状态机。

    节点拓扑：
    profile_agent
      ├─ (画像不足) → END          ← 情况A/B：追问，本轮结束
      └─ (画像足够) → planner_agent ← 情况C：正常生成流程
                    ↙  ↙  ↙  ↘  ↘
                doc mindmap quiz code summary
                    ↘  ↘  ↘  ↙  ↙
                     safety_agent
                          ↓
                   recommend_agent → END
    """
    graph = StateGraph(AgentState)

    # -- 注册节点 --
    graph.add_node("profile_agent", profile_agent.run)
    graph.add_node("planner_agent", planner_agent.run)
    graph.add_node("doc_agent", doc_agent.run)
    graph.add_node("mindmap_agent", mindmap_agent.run)
    graph.add_node("quiz_agent", quiz_agent.run)
    graph.add_node("code_agent", code_agent.run)
    graph.add_node("summary_agent", summary_agent.run)
    graph.add_node("safety_agent", safety_agent.run)
    graph.add_node("recommend_agent", recommend_agent.run)

    # -- 起始节点 --
    graph.set_entry_point("profile_agent")

    # profile → 条件路由（画像不足则直接 END，足够则进 planner）
    graph.add_conditional_edges(
        "profile_agent",
        profile_agent.route_after_profile,
        {
            "planner_agent": "planner_agent",
            END: END,
        },
    )

    # planner → 条件路由（按 resource_type）
    graph.add_conditional_edges(
        "planner_agent",
        planner_agent.route_by_resource_type,
        {
            "doc_agent": "doc_agent",
            "mindmap_agent": "mindmap_agent",
            "quiz_agent": "quiz_agent",
            "code_agent": "code_agent",
            "summary_agent": "summary_agent",
            "recommend_agent": "recommend_agent",
        },
    )

    # 各生成 Agent → safety_agent
    for agent_name in ["doc_agent", "mindmap_agent", "quiz_agent", "code_agent", "summary_agent"]:
        graph.add_edge(agent_name, "safety_agent")

    # safety → recommend → END
    graph.add_edge("safety_agent", "recommend_agent")
    graph.add_edge("recommend_agent", END)

    return graph.compile()


# 模块级全局图实例（FastAPI 启动时调用 build_graph() 初始化）
_compiled_graph = None


def get_graph():
    """返回已编译的图，若未初始化则抛出 RuntimeError。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def invoke(user_id: str, session_id: str, message: str) -> AgentState:
    """
    执行一次完整的图推理，返回最终状态。

    :param user_id:   用户 UUID 字符串
    :param session_id: 会话 UUID 字符串
    :param message:   用户输入
    :return:           最终 AgentState
    """
    initial_state = AgentState(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
    )
    result = await get_graph().ainvoke(initial_state)
    return AgentState(**result)


async def stream_invoke(user_id: str, session_id: str, message: str):
    """
    流式执行图推理，逐步 yield AgentState 快照。
    供 FastAPI StreamingResponse 或 Streamlit 实时显示使用。
    """
    initial_state = AgentState(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
    )
    async for event in get_graph().astream(initial_state):
        yield event
