"""
tests/test_doc_agent.py
backend/agents/doc_agent.py 单元测试。
"""

import uuid

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import doc_agent
from backend.models.schemas import AgentState


class TestDocAgentRun:
    """doc_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_draft_content(self):
        """run 应调用 LLM 生成文档并写入 draft_content。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成反向传播的文档",
            kp_id="kp_01_01",
        )

        mock_chunk = MagicMock()
        mock_chunk.text = "反向传播是深度学习核心算法。"
        mock_chunk.source = "doc.pdf"
        mock_chunk.chunk_id = "c1"
        mock_chunk.score = 0.9
        mock_chunk.doc_id = "d1"

        with patch("backend.agents.doc_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = [mock_chunk]

            with patch("backend.agents.doc_agent.format_context") as mock_format:
                mock_format.return_value = "[1] 反向传播是深度学习核心算法。"

                with patch("backend.agents.doc_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                    mock_chat.return_value = "# 反向传播\n\n本文介绍..."

                    result = await doc_agent.run(state)

                    assert result.draft_content == "# 反向传播\n\n本文介绍..."
                    assert "反向传播是深度学习核心算法。" in result.retrieved_docs

    @pytest.mark.asyncio
    async def test_run_handles_retrieve_failure(self):
        """检索失败时使用默认上下文，不崩溃。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成文档",
            kp_id="kp_01",
        )

        with patch("backend.agents.doc_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.side_effect = Exception("vector db error")

            with patch("backend.agents.doc_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = "文档内容"

                result = await doc_agent.run(state)

                assert result.draft_content == "文档内容"
                assert result.retrieved_docs == []

    @pytest.mark.asyncio
    async def test_run_handles_chat_completion_failure(self):
        """LLM 调用失败时 draft_content 应包含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成文档",
            kp_id="kp_01",
        )

        with patch("backend.agents.doc_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.doc_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.side_effect = Exception("LLM error")

                result = await doc_agent.run(state)

                assert "文档生成失败" in result.draft_content

    @pytest.mark.asyncio
    async def test_run_uses_unknown_knowledge_point_when_kp_id_none(self):
        """kp_id 为 None 时使用默认提示。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成文档",
            kp_id=None,
        )

        with patch("backend.agents.doc_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.doc_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = "文档"

                result = await doc_agent.run(state)

                mock_chat.assert_called_once()
                call_args = mock_chat.call_args
                prompt = call_args[0][0][0]["content"]
                assert "未知知识点" in prompt
