"""
tests/test_profile_agent.py
backend/agents/profile_agent.py 单元测试。
"""

import json
import uuid
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import profile_agent
from backend.models.schemas import AgentState, StudentProfileOut


# ===========================================================
# 辅助函数测试
# ===========================================================

class TestProfileToKnownFields:
    """_profile_to_known_fields 函数测试。"""

    def test_empty_profile_returns_empty_dict(self):
        result = profile_agent._profile_to_known_fields(None)
        assert result == {}

    def test_profile_excludes_empty_values(self):
        """空字符串、空列表、None 应被排除。"""
        profile = StudentProfileOut(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            version=1,
            updated_at=datetime.utcnow(),
            major="CS",
            learning_goal="",
            knowledge_mastered=[],
            knowledge_weak=[],
        )
        result = profile_agent._profile_to_known_fields(profile)
        assert "major" in result
        assert "learning_goal" not in result
        assert "knowledge_mastered" not in result


class TestMergeProfileInMemory:
    """_merge_profile_in_memory 函数测试。"""

    def test_merge_updates_existing_fields(self):
        """已有字段应被覆盖。"""
        profile = StudentProfileOut(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            version=1,
            updated_at=datetime.utcnow(),
            major="CS",
            learning_goal="AI",
        )
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hello",
            profile=profile,
        )
        result = profile_agent._merge_profile_in_memory(state, {"major": "EE"})
        assert result.profile.major == "EE"
        assert result.profile.learning_goal == "AI"

    def test_merge_concatenates_lists(self):
        """列表字段应合并去重。"""
        profile = StudentProfileOut(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),
            version=1,
            updated_at=datetime.utcnow(),
            knowledge_mastered=["kp1", "kp2"],
        )
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hello",
            profile=profile,
        )
        result = profile_agent._merge_profile_in_memory(state, {"knowledge_mastered": ["kp2", "kp3"]})
        assert set(result.profile.knowledge_mastered) == {"kp1", "kp2", "kp3"}


class TestCheckProfileComplete:
    """_check_profile_complete 函数测试。"""

    def test_none_profile_returns_false(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile=None,
        )
        assert profile_agent._check_profile_complete(state) is False

    def test_learning_goal_satisfied(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile=StudentProfileOut(
                id=uuid.uuid4(), user_id=uuid.uuid4(), version=1,
                updated_at=datetime.utcnow(),
                learning_goal="掌握深度学习",
            ),
        )
        assert profile_agent._check_profile_complete(state) is True

    def test_knowledge_weak_satisfied(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile=StudentProfileOut(
                id=uuid.uuid4(), user_id=uuid.uuid4(), version=1,
                updated_at=datetime.utcnow(),
                knowledge_weak=["反向传播"],
            ),
        )
        assert profile_agent._check_profile_complete(state) is True

    def test_all_fields_empty_returns_false(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile=StudentProfileOut(
                id=uuid.uuid4(), user_id=uuid.uuid4(), version=1,
                updated_at=datetime.utcnow(),
            ),
        )
        assert profile_agent._check_profile_complete(state) is False


class TestRouteAfterProfile:
    """route_after_profile 条件路由测试。"""

    def test_complete_profile_routes_to_planner(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile_complete=True,
        )
        from langgraph.graph import END
        assert profile_agent.route_after_profile(state) == "planner_agent"

    def test_incomplete_profile_routes_to_end(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            profile_complete=False,
        )
        from langgraph.graph import END
        assert profile_agent.route_after_profile(state) == END


# ===========================================================
# run 函数测试
# ===========================================================

class TestProfileAgentRun:
    """profile_agent.run 集成测试。"""

    @pytest.mark.asyncio
    async def test_run_extracts_and_merges_profile(self):
        """run 应调用 LLM 提取画像并合并。"""
        mock_db = MagicMock()
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="我想学习深度学习，每天能花两小时",
        )

        extract_response = json.dumps({
            "major": "CS",
            "learning_goal": "深度学习",
            "cognitive_style": "visual",
            "daily_time_minutes": 120,
            "knowledge_mastered": ["Python"],
            "knowledge_weak": [],
            "error_prone": [],
            "current_progress": None,
        })

        intent_response = "yes"
        clarify_response = "好的，我来帮你生成资料。"

        with patch("backend.agents.profile_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = [extract_response, intent_response, clarify_response]

            with patch("backend.agents.profile_agent.profile_svc.merge_chat_updates", new_callable=AsyncMock) as mock_merge:
                mock_profile = StudentProfileOut(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(state.user_id),
                    version=1,
                    updated_at=datetime.utcnow(),
                    major="CS",
                    learning_goal="深度学习",
                )
                mock_merge.return_value = mock_profile

                result = await profile_agent.run(state, config={"configurable": {"db": mock_db}})

                assert result.profile is not None
                assert result.profile_complete is True

    @pytest.mark.asyncio
    async def test_run_without_db_uses_memory_merge(self):
        """无 db 时应回退到内存合并。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        with patch("backend.agents.profile_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = ["{}", "no", "请补充信息"]

            result = await profile_agent.run(state, config={"configurable": {"db": None}})

            # profile_complete 为 False（内存合并返回默认空 profile）
            assert result.profile_complete is False
            assert result.clarify_message is not None

    @pytest.mark.asyncio
    async def test_run_handles_json_decode_error(self):
        """LLM 返回非 JSON 时不崩溃。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        with patch("backend.agents.profile_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = ["not json", "no", "请补充信息"]

            result = await profile_agent.run(state, config={"configurable": {"db": None}})
            assert result.profile_complete is False

    @pytest.mark.asyncio
    async def test_run_sets_clarify_message_when_incomplete(self):
        """画像不足时应设置 clarify_message。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        with patch("backend.agents.profile_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = ["{}", "no", "请问你的学习目标是什么？"]

            with patch("backend.agents.profile_agent.profile_svc.merge_chat_updates", new_callable=AsyncMock) as mock_merge:
                mock_merge.return_value = StudentProfileOut(
                    id=uuid.uuid4(),
                    user_id=uuid.UUID(state.user_id),
                    version=1,
                    updated_at=datetime.utcnow(),
                )
                result = await profile_agent.run(state, config={"configurable": {"db": None}})

                assert result.clarify_message is not None
                assert result.final_content == result.clarify_message
