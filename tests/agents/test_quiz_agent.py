"""
tests/agents/test_quiz_agent.py
backend/agents/quiz_agent.py 单元测试。
"""

import json
import uuid

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents import quiz_agent
from backend.models.schemas import AgentState


# ===========================================================
# _get_question_counts 测试
# ===========================================================

class TestGetQuestionCounts:
    """_get_question_counts 根据画像决定题目数量。"""

    def test_none_profile_returns_defaults(self):
        """无画像时返回默认数量 (2, 1, 1)。"""
        total, single, multi = quiz_agent._get_question_counts(None)
        assert total == 2
        assert single == 1
        assert multi == 1

    def test_many_weak_points_returns_more_questions(self):
        """薄弱知识点 > 5 时返回 (3, 2, 2)。"""
        # 使用普通对象避免 MagicMock 与 getattr 的问题
        class MockProfile:
            knowledge_weak = ["kp1", "kp2", "kp3", "kp4", "kp5", "kp6"]
        total, single, multi = quiz_agent._get_question_counts(MockProfile())
        assert total == 3
        assert single == 2
        assert multi == 2

    def test_medium_weak_points(self):
        """薄弱知识点 3-5 时返回 (2, 1, 1)。"""
        class MockProfile:
            knowledge_weak = ["kp1", "kp2", "kp3"]
        total, single, multi = quiz_agent._get_question_counts(MockProfile())
        assert total == 2
        assert single == 1
        assert multi == 1


# ===========================================================
# run 函数测试
# ===========================================================

class TestQuizAgentRun:
    """quiz_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_draft_content_with_questions_json(self):
        """run 应将题目 JSON 数组序列化后写入 draft_content。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="出几道题",
            kp_id="kp_01",
        )

        questions = [
            {
                "question_type": "single",
                "difficulty": 2,
                "stem": "反向传播中梯度用于？",
                "options": ["A. 正向传播", "B. 更新权重", "C. 初始化", "D. 正则化"],
                "answer": "B",
                "explanation": "梯度用于更新网络权重。",
            }
        ]

        with patch("backend.agents.quiz_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.quiz_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = json.dumps(questions)

                result = await quiz_agent.run(state)

                parsed = json.loads(result.draft_content)
                assert len(parsed) == 1
                assert parsed[0]["question_type"] == "single"

    @pytest.mark.asyncio
    async def test_run_handles_invalid_json_response(self):
        """LLM 返回非 JSON 时 draft_content 为空数组。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="出题",
            kp_id="kp_01",
        )

        with patch("backend.agents.quiz_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.quiz_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = "这是一道题..."

                result = await quiz_agent.run(state)

                assert result.draft_content == "[]"

    @pytest.mark.asyncio
    async def test_run_handles_chat_failure(self):
        """LLM 调用失败时包含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="出题",
            kp_id="kp_01",
        )

        with patch("backend.agents.quiz_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.quiz_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.side_effect = Exception("LLM error")

                result = await quiz_agent.run(state)

                assert "题目生成失败" in result.draft_content
