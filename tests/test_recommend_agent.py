"""
tests/test_recommend_agent.py
backend/agents/recommend_agent.py 单元测试。
"""

import json
import uuid
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import recommend_agent
from backend.models.schemas import AgentState, StudentProfileOut


class TestRecommendAgentRun:
    """recommend_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_recommendations_in_metadata(self):
        """run 应将推荐列表存入 state.metadata["recommendations"]。"""
        user_uuid = uuid.uuid4()
        state = AgentState(
            user_id=str(user_uuid),
            session_id=str(uuid.uuid4()),
            user_message="推荐下一步学习内容",
            profile=StudentProfileOut(
                id=uuid.uuid4(),
                user_id=user_uuid,
                version=1,
                updated_at=datetime.utcnow(),
                learning_goal="深度学习",
                knowledge_mastered=["Python"],
                knowledge_weak=["反向传播"],
            ),
        )

        recommendations = [
            {"kp_id": "kp_01", "kp_name": "梯度下降", "reason": "为反向传播打基础"},
            {"kp_id": "kp_02", "kp_name": "卷积神经网络", "reason": "深度学习核心"},
        ]

        with patch("backend.agents.recommend_agent.profile_svc.build_profile_context", new_callable=AsyncMock) as mock_profile_ctx:
            mock_profile_ctx.return_value = "学生目标：深度学习"

            with patch("backend.agents.recommend_agent.db_select", new_callable=AsyncMock) as mock_select:
                mock_node1 = MagicMock()
                mock_node1.id = "kp_01"
                mock_node1.name = "梯度下降"
                mock_node2 = MagicMock()
                mock_node2.id = "kp_02"
                mock_node2.name = "卷积神经网络"
                mock_select.return_value = [mock_node1, mock_node2]

                with patch("backend.agents.recommend_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = json.dumps(recommendations)

                    result = await recommend_agent.run(state, config={"configurable": {"db": MagicMock()}})

                    assert result.metadata["recommendations"] == recommendations
                    assert result.final_content == json.dumps(recommendations, ensure_ascii=False)

    @pytest.mark.asyncio
    async def test_run_handles_non_list_response(self):
        """LLM 返回非列表时 recommendations 为空列表。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="推荐",
        )

        with patch("backend.agents.recommend_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = '{"kp_id": "kp_01"}'

            result = await recommend_agent.run(state, config={"configurable": {"db": None}})

            assert result.metadata["recommendations"] == []

    @pytest.mark.asyncio
    async def test_run_handles_json_decode_error(self):
        """JSON 解析失败时 recommendations 为空列表。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="推荐",
        )

        with patch("backend.agents.recommend_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "这不是 JSON"

            result = await recommend_agent.run(state, config={"configurable": {"db": None}})

            assert result.metadata["recommendations"] == []

    @pytest.mark.asyncio
    async def test_run_handles_chat_failure(self):
        """LLM 调用失败时 recommendations 为空列表，final_content 含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="推荐",
        )

        with patch("backend.agents.recommend_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = Exception("LLM error")

            result = await recommend_agent.run(state, config={"configurable": {"db": None}})

            assert result.metadata["recommendations"] == []
            assert "推荐生成失败" in result.final_content

    @pytest.mark.asyncio
    async def test_run_without_db_shows_no_kp_message(self):
        """无数据库连接时 prompt 中标注无可用知识点。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="推荐",
        )

        with patch("backend.agents.recommend_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "[]"

            result = await recommend_agent.run(state, config={"configurable": {"db": None}})

            call_args = mock_chat.call_args
            prompt = call_args[0][0][0]["content"]
            assert "无数据库连接" in prompt
            assert result.metadata["recommendations"] == []
