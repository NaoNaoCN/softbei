"""
tests/test_summary_agent.py
backend/agents/summary_agent.py 单元测试。
"""

import uuid

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import summary_agent
from backend.models.schemas import AgentState


class TestSummaryAgentRun:
    """summary_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_draft_content(self):
        """run 应调用 LLM 生成总结并写入 draft_content。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成总结",
            kp_id="kp_01_01",
        )

        mock_chunk = MagicMock()
        mock_chunk.text = "反向传播是深度学习核心算法。"

        with patch("backend.agents.summary_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = [mock_chunk]

            with patch("backend.agents.summary_agent.format_context") as mock_format:
                mock_format.return_value = "[1] 反向传播是深度学习核心算法。"

                with patch("backend.agents.summary_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = "## 总结\n- 核心：反向传播"

                    result = await summary_agent.run(state)

                    assert result.draft_content == "## 总结\n- 核心：反向传播"
                    assert "反向传播是深度学习核心算法。" in result.retrieved_docs

    @pytest.mark.asyncio
    async def test_run_handles_retrieve_failure(self):
        """检索失败时使用默认上下文。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成总结",
            kp_id="kp_01",
        )

        with patch("backend.agents.summary_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.side_effect = Exception("vector db error")

            with patch("backend.agents.summary_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = "总结内容"

                result = await summary_agent.run(state)

                assert result.draft_content == "总结内容"
                assert result.retrieved_docs == []

    @pytest.mark.asyncio
    async def test_run_handles_chat_failure(self):
        """LLM 失败时 draft_content 包含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成总结",
            kp_id="kp_01",
        )

        with patch("backend.agents.summary_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.summary_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.side_effect = Exception("LLM error")

                result = await summary_agent.run(state)

                assert "总结生成失败" in result.draft_content
