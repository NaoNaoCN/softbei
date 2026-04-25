"""
tests/test_planner_agent.py
backend/agents/planner_agent.py 单元测试。
"""

import uuid
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import planner_agent
from backend.models.schemas import AgentState, StudentProfileOut, ResourceType


# ===========================================================
# route_by_resource_type 测试
# ===========================================================

class TestRouteByResourceType:
    """route_by_resource_type 条件路由测试。"""

    def test_routes_doc(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=ResourceType.doc,
        )
        assert planner_agent.route_by_resource_type(state) == "doc_agent"

    def test_routes_mindmap(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=ResourceType.mindmap,
        )
        assert planner_agent.route_by_resource_type(state) == "mindmap_agent"

    def test_routes_quiz(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=ResourceType.quiz,
        )
        assert planner_agent.route_by_resource_type(state) == "quiz_agent"

    def test_routes_code(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=ResourceType.code,
        )
        assert planner_agent.route_by_resource_type(state) == "code_agent"

    def test_routes_summary(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=ResourceType.summary,
        )
        assert planner_agent.route_by_resource_type(state) == "summary_agent"

    def test_routes_to_recommend_when_type_unknown(self):
        """resource_type 为 None 或不在映射中时默认 recommend。"""
        state1 = AgentState(user_id="u1", session_id="s1", user_message="hi")
        assert planner_agent.route_by_resource_type(state1) == "recommend_agent"

        state2 = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            resource_type=None,
        )
        assert planner_agent.route_by_resource_type(state2) == "recommend_agent"


# ===========================================================
# run 函数测试
# ===========================================================

class TestPlannerAgentRun:
    """planner_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_parses_llm_response(self):
        """run 应解析 LLM 返回的 JSON 并设置 state。"""
        user_uuid = uuid.uuid4()
        profile_uuid = uuid.uuid4()
        state = AgentState(
            user_id=str(user_uuid),
            session_id=str(uuid.uuid4()),
            user_message="帮我生成一份关于反向传播的文档",
            profile=StudentProfileOut(
                id=profile_uuid,
                user_id=user_uuid,
                version=1,
                updated_at=datetime.utcnow(),
                learning_goal="深度学习",
            ),
        )

        llm_response = '{"resource_type": "doc", "kp_id": "kp_01_01"}'

        with patch("backend.agents.planner_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = llm_response

            with patch("backend.agents.planner_agent.profile_svc.build_profile_context", new_callable=AsyncMock) as mock_profile_ctx:
                mock_profile_ctx.return_value = "学生专业：CS"

                with patch("backend.db.crud.select", new_callable=AsyncMock) as mock_select:
                    mock_node = MagicMock()
                    mock_node.id = "kp_01_01"
                    mock_node.name = "反向传播"
                    mock_select.return_value = [mock_node]

                    result = await planner_agent.run(state, config={"configurable": {"db": MagicMock()}})

                    assert result.resource_type == ResourceType.doc
                    assert result.kp_id == "kp_01_01"

    @pytest.mark.asyncio
    async def test_run_handles_invalid_json(self):
        """LLM 返回非 JSON 时不崩溃，保持 state 原样。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        with patch("backend.agents.planner_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = Exception("network error")

            result = await planner_agent.run(state)
            assert result.resource_type is None
            assert result.kp_id is None

    @pytest.mark.asyncio
    async def test_run_handles_invalid_resource_type(self):
        """LLM 返回未知 resource_type 时设为 None。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        llm_response = '{"resource_type": "unknown_type", "kp_id": "kp_01"}'

        with patch("backend.agents.planner_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = llm_response

            result = await planner_agent.run(state)
            assert result.resource_type is None

    @pytest.mark.asyncio
    async def test_run_without_db_skips_kp_list(self):
        """无 db 时跳过知识点列表获取。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        with patch("backend.agents.planner_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = '{"resource_type": "quiz", "kp_id": null}'

            with patch("backend.agents.planner_agent.profile_svc.build_profile_context", new_callable=AsyncMock) as mock_profile_ctx:
                mock_profile_ctx.return_value = ""

                result = await planner_agent.run(state, config={"configurable": {"db": None}})

                assert result.resource_type == ResourceType.quiz
                mock_chat.assert_called_once()
