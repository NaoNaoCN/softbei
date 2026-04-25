"""
tests/test_code_agent.py
backend/agents/code_agent.py 单元测试。
"""

import uuid
from datetime import datetime

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import code_agent
from backend.models.schemas import AgentState, StudentProfileOut


class TestCodeAgentRun:
    """code_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_draft_content(self):
        """run 应调用 LLM 生成代码并写入 draft_content。"""
        user_uuid = uuid.uuid4()
        profile_uuid = uuid.uuid4()
        state = AgentState(
            user_id=str(user_uuid),
            session_id=str(uuid.uuid4()),
            user_message="生成代码示例",
            kp_id="kp_01_01",
            profile=StudentProfileOut(
                id=profile_uuid,
                user_id=user_uuid,
                version=1,
                updated_at=datetime.utcnow(),
                cognitive_style="practice",
            ),
        )

        mock_chunk = MagicMock()
        mock_chunk.text = "反向传播代码示例"

        with patch("backend.agents.code_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = [mock_chunk]

            with patch("backend.agents.code_agent.format_context") as mock_format:
                mock_format.return_value = "[1] 反向传播代码示例"

                with patch("backend.agents.code_agent.profile_svc.build_profile_context", new_callable=AsyncMock) as mock_profile_ctx:
                    mock_profile_ctx.return_value = "学生认知风格：实践型"

                    with patch("backend.agents.code_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                        mock_chat.return_value = "```python\nprint('hello')\n```"

                        result = await code_agent.run(state)

                        assert "print('hello')" in result.draft_content

    @pytest.mark.asyncio
    async def test_run_handles_retrieve_failure(self):
        """检索失败时继续执行，使用默认上下文。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成代码",
            kp_id="kp_01",
        )

        with patch("backend.agents.code_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.side_effect = Exception("vector db error")

            with patch("backend.agents.code_agent.profile_svc.build_profile_context", new_callable=AsyncMock) as mock_profile_ctx:
                mock_profile_ctx.return_value = "暂无画像"

                with patch("backend.agents.code_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = "代码内容"

                    result = await code_agent.run(state)

                    assert result.draft_content == "代码内容"

    @pytest.mark.asyncio
    async def test_run_handles_chat_failure(self):
        """LLM 调用失败时 draft_content 包含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成代码",
            kp_id="kp_01",
        )

        with patch("backend.agents.code_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.code_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.side_effect = Exception("LLM error")

                result = await code_agent.run(state)

                assert "代码生成失败" in result.draft_content
