"""
backend/agents/graph.py
LangGraph 主状态机：定义节点、边（含条件路由）并编译图。
"""

from __future__ import annotations

from typing import Any
from sqlalchemy.ext.asyncio import AsyncSession

from langgraph.graph import END, StateGraph

from backend.agents import (
    clarify_agent,
    code_agent,
    doc_agent,
    kg_agent,
    mindmap_agent,
    planner_agent,
    profile_agent,
    quiz_agent,
    recommend_agent,
    safety_agent,
    summary_agent,
)
from backend.models.schemas import AgentState
from backend.services.profile import get_profile
from backend.services.chat_history import load_chat_history

# ----------------------------------------------------------
# 数据库会话注入辅助
# ----------------------------------------------------------

async def _run_with_db(node_func, state: AgentState, db: AsyncSession) -> AgentState:
    """
    通用包装器：如果 node_func 签名需要 db，则传递。
    LangGraph 节点函数签名为 (state,) 或 (state, config)。
    """
    import inspect
    sig = inspect.signature(node_func)
    params = list(sig.parameters.keys())
    if "db" in params:
        return await node_func(state, db)
    return await node_func(state)


# ----------------------------------------------------------
# 图构建
# ----------------------------------------------------------

def build_graph() -> StateGraph:
    """
    构建并返回编译后的 LangGraph 状态机。

    节点拓扑（条件路由，非并行）：

    START → profile_agent
              ├─ (画像不足) → END
              └─ (画像足够) → planner_agent
                              │ (先判断 intent_type)
                              ├─ intent="clarify" → clarify_agent → END
                              │
                              │ (intent="generate", 按 resource_type 路由)
                              ├─ doc_agent ─────┐
                              ├─ mindmap_agent ─┤
                              ├─ quiz_agent ────┼─→ safety_agent → recommend_agent → END
                              ├─ code_agent ────┤
                              ├─ summary_agent ─┘
                              ├─ kg_agent ──────────────────────→ recommend_agent → END
                              └─ recommend_agent → END           ← 兜底路由
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
    graph.add_node("kg_agent", kg_agent.run)
    graph.add_node("clarify_agent", clarify_agent.run)

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

    # planner → 条件路由（按 intent_type + resource_type）
    graph.add_conditional_edges(
        "planner_agent",
        planner_agent.route_by_resource_type,
        {
            "doc_agent": "doc_agent",
            "mindmap_agent": "mindmap_agent",
            "quiz_agent": "quiz_agent",
            "code_agent": "code_agent",
            "summary_agent": "summary_agent",
            "kg_agent": "kg_agent",
            "recommend_agent": "recommend_agent",
            "clarify_agent": "clarify_agent",
        },
    )

    # 各生成 Agent → safety_agent
    for agent_name in ["doc_agent", "mindmap_agent", "quiz_agent", "code_agent", "summary_agent"]:
        graph.add_edge(agent_name, "safety_agent")

    # safety → recommend → END
    graph.add_edge("safety_agent", "recommend_agent")
    graph.add_edge("kg_agent", "recommend_agent")  # KG 跳过 safety，直接到 recommend
    graph.add_edge("recommend_agent", END)
    graph.add_edge("clarify_agent", END)  # clarify 直接结束，无需 safety

    return graph.compile()


# 模块级全局图实例（FastAPI 启动时调用 build_graph() 初始化）
_compiled_graph = None


def get_graph() -> StateGraph:
    """返回已编译的图，若未初始化则抛出 RuntimeError。"""
    global _compiled_graph
    if _compiled_graph is None:
        _compiled_graph = build_graph()
    return _compiled_graph


async def invoke(user_id: int, session_id: int, message: str, db: AsyncSession) -> AgentState:
    """
    执行一次完整的图推理，返回最终状态。

    :param user_id:   用户 ID（Snowflake BIGINT）
    :param session_id: 会话 ID（Snowflake BIGINT）
    :param message:   用户输入
    :param db:        数据库会话
    :return:           最终 AgentState
    """
    existing_profile = await get_profile(user_id, db)

    # 加载多轮对话历史
    chat_history = await load_chat_history(session_id, db)

    initial_state = AgentState(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
        profile=existing_profile,
        chat_history=chat_history,
    )

    result = await get_graph().ainvoke(
        initial_state,
        config={"configurable": {"db": db}},
    )
    return AgentState(**result)


async def stream_invoke(user_id: int, session_id: int, message: str, db: AsyncSession):
    """
    流式执行图推理，逐步 yield AgentState 快照。
    供 FastAPI StreamingResponse 或 Streamlit 实时显示使用。
    """
    existing_profile = await get_profile(user_id, db)

    # 加载多轮对话历史
    chat_history = await load_chat_history(session_id, db)

    initial_state = AgentState(
        user_id=user_id,
        session_id=session_id,
        user_message=message,
        profile=existing_profile,
        chat_history=chat_history,
    )
    async for event in get_graph().astream(
        initial_state,
        config={"configurable": {"db": db}},
    ):
        yield event
