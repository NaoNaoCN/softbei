"""
tests/test_graph.py
backend/agents/graph.py 单元测试。
"""

import uuid

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import graph
from backend.models.schemas import AgentState


# ===========================================================
# build_graph 测试
# ===========================================================

class TestBuildGraph:
    """build_graph 图构建测试。"""

    def test_build_graph_returns_compiled_graph(self):
        """build_graph 应返回编译后的图（CompiledStateGraph）。"""
        from langgraph.graph.state import CompiledStateGraph
        result = graph.build_graph()
        assert isinstance(result, CompiledStateGraph)

    def test_build_graph_has_all_nodes(self):
        """图中应注册所有 Agent 节点。"""
        built = graph.build_graph()

        # 获取图的节点
        node_names = {n for n in graph.build_graph().nodes}

        expected = {
            "profile_agent",
            "planner_agent",
            "doc_agent",
            "mindmap_agent",
            "quiz_agent",
            "code_agent",
            "summary_agent",
            "safety_agent",
            "recommend_agent",
        }
        assert expected.issubset(node_names)


# ===========================================================
# get_graph 测试
# ===========================================================

class TestGetGraph:
    """get_graph 单例测试。"""

    def test_get_graph_returns_same_instance(self):
        """get_graph 应返回同一实例（单例）。"""
        # 重置全局状态
        graph._compiled_graph = None

        g1 = graph.get_graph()
        g2 = graph.get_graph()
        assert g1 is g2

        # 重置
        graph._compiled_graph = None

    def test_get_graph_initializes_on_first_call(self):
        """首次调用时自动初始化。"""
        graph._compiled_graph = None

        g = graph.get_graph()
        assert g is not None
        assert graph._compiled_graph is g

        # 重置
        graph._compiled_graph = None


# ===========================================================
# invoke 测试
# ===========================================================

class TestInvoke:
    """invoke 图执行测试。"""

    @pytest.mark.asyncio
    async def test_invoke_returns_final_agent_state(self):
        """invoke 应返回最终 AgentState。"""
        graph._compiled_graph = None

        mock_db = MagicMock()

        # 模拟图的 invoke 返回最终状态字典
        with patch.object(graph, "get_graph") as mock_get_graph:
            mock_graph_instance = MagicMock()
            mock_graph_instance.ainvoke = AsyncMock(return_value={
                "user_id": "u1",
                "session_id": "s1",
                "user_message": "hello",
                "profile": None,
                "profile_complete": False,
                "clarify_message": "请补充信息",
                "metadata": {},
            })
            mock_get_graph.return_value = mock_graph_instance

            result = await graph.invoke(
                user_id="u1",
                session_id="s1",
                message="hello",
                db=mock_db,
            )

            assert isinstance(result, AgentState)
            assert result.user_id == "u1"
            mock_graph_instance.ainvoke.assert_called_once()

        graph._compiled_graph = None

    @pytest.mark.asyncio
    async def test_invoke_passes_db_in_config(self):
        """invoke 应将 db 传入 config。"""
        graph._compiled_graph = None

        mock_db = MagicMock()

        with patch.object(graph, "get_graph") as mock_get_graph:
            mock_graph_instance = MagicMock()
            mock_graph_instance.ainvoke = AsyncMock(return_value={
                "user_id": "u1",
                "session_id": "s1",
                "user_message": "hi",
                "profile": None,
                "profile_complete": True,
                "metadata": {},
            })
            mock_get_graph.return_value = mock_graph_instance

            await graph.invoke("u1", "s1", "hi", db=mock_db)

            call_kwargs = mock_graph_instance.ainvoke.call_args[1]
            assert "config" in call_kwargs
            assert call_kwargs["config"]["configurable"]["db"] is mock_db

        graph._compiled_graph = None


# ===========================================================
# stream_invoke 测试
# ===========================================================

class TestStreamInvoke:
    """stream_invoke 流式执行测试。"""

    @pytest.mark.asyncio
    async def test_stream_invoke_yields_events(self):
        """stream_invoke 应逐个 yield 事件。"""
        graph._compiled_graph = None

        mock_db = MagicMock()

        async def mock_astream(state, config):
            yield {"user_id": "u1", "session_id": "s1", "user_message": "hi", "profile": None, "metadata": {}, "profile_complete": False}
            yield {"user_id": "u1", "session_id": "s1", "user_message": "hi", "profile": None, "metadata": {}, "profile_complete": True}

        with patch.object(graph, "get_graph") as mock_get_graph:
            mock_graph_instance = MagicMock()
            mock_graph_instance.astream = mock_astream
            mock_get_graph.return_value = mock_graph_instance

            events = []
            async for event in graph.stream_invoke("u1", "s1", "hi", db=mock_db):
                events.append(event)

            assert len(events) == 2

        graph._compiled_graph = None


# ===========================================================
# _run_with_db 测试
# ===========================================================

class TestRunWithDb:
    """_run_with_db 辅助函数测试。"""

    @pytest.mark.asyncio
    async def test_run_with_db_passes_db_when_needed(self):
        """node_func 需要 db 参数时应传递。"""
        async def node_with_db(state, db):
            return state

        state = AgentState(user_id="u1", session_id="s1", user_message="hi")
        mock_db = MagicMock()

        result = await graph._run_with_db(node_with_db, state, mock_db)
        assert result is state

    @pytest.mark.asyncio
    async def test_run_with_db_calls_without_db_when_not_needed(self):
        """node_func 不需要 db 参数时直接调用。"""
        async def node_without_db(state):
            return state

        state = AgentState(user_id="u1", session_id="s1", user_message="hi")
        mock_db = MagicMock()

        result = await graph._run_with_db(node_without_db, state, mock_db)
        assert result is state
