"""
tests/test_safety_agent.py
backend/agents/safety_agent.py 单元测试。
"""

import json
import uuid

import pytest
from unittest.mock import AsyncMock, patch

from backend.agents import safety_agent
from backend.models.schemas import AgentState


# ===========================================================
# should_skip_safety 测试
# ===========================================================

class TestShouldSkipSafety:
    """should_skip_safety 决定是否跳过安全检查。"""

    def test_skip_when_no_draft_content(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            draft_content="",
        )
        assert safety_agent.should_skip_safety(state) is True

    def test_skip_when_draft_content_none(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
        )
        assert safety_agent.should_skip_safety(state) is True

    def test_no_skip_when_draft_content_exists(self):
        state = AgentState(
            user_id="u1", session_id="s1", user_message="hi",
            draft_content="some content",
        )
        assert safety_agent.should_skip_safety(state) is False


# ===========================================================
# run 函数测试
# ===========================================================

class TestSafetyAgentRun:
    """safety_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_passes_valid_content(self):
        """内容通过审核时 final_content = draft_content，safety_passed = True。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
            draft_content="深度学习是机器学习的子领域。",
            retrieved_docs=["深度学习是机器学习的一个分支。"],
        )

        llm_response = json.dumps({
            "passed": True,
            "issues": [],
            "revised_content": None,
        })

        with patch("backend.agents.safety_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = llm_response

            result = await safety_agent.run(state)

            assert result.safety_passed is True
            assert result.final_content == state.draft_content

    @pytest.mark.asyncio
    async def test_run_replaces_content_when_failed(self):
        """审核不通过时使用修正内容。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
            draft_content="深度学习最早由图灵提出。",
            retrieved_docs=["深度学习由Hinton等人于2006年提出。"],
        )

        llm_response = json.dumps({
            "passed": False,
            "issues": ["事实错误：深度学习由Hinton提出，非图灵"],
            "revised_content": "深度学习由Hinton等人于2006年提出。",
        })

        with patch("backend.agents.safety_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = llm_response

            result = await safety_agent.run(state)

            assert result.safety_passed is False
            assert result.final_content == "深度学习由Hinton等人于2006年提出。"
            assert result.metadata["safety_issues"] == ["事实错误：深度学习由Hinton提出，非图灵"]

    @pytest.mark.asyncio
    async def test_run_conservative_pass_on_json_decode_error(self):
        """JSON 解析失败时保守通过。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
            draft_content="some content",
        )

        with patch("backend.agents.safety_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = "not json"

            result = await safety_agent.run(state)

            assert result.safety_passed is True
            assert result.final_content == state.draft_content

    @pytest.mark.asyncio
    async def test_run_conservative_pass_on_exception(self):
        """LLM 调用异常时保守通过。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
            draft_content="some content",
        )

        with patch("backend.agents.safety_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.side_effect = Exception("network error")

            result = await safety_agent.run(state)

            assert result.safety_passed is True
            assert result.final_content == state.draft_content

    @pytest.mark.asyncio
    async def test_run_skips_check_when_no_draft(self):
        """无 draft_content 时直接返回 safety_passed=True。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
        )

        result = await safety_agent.run(state)

        assert result.safety_passed is True
        assert result.final_content == ""

    @pytest.mark.asyncio
    async def test_run_uses_first_three_retrieved_docs(self):
        """审核上下文只使用前 3 篇检索文档。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="hi",
            draft_content="test",
            retrieved_docs=["doc1", "doc2", "doc3", "doc4", "doc5"],
        )

        with patch("backend.agents.safety_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
            mock_chat.return_value = json.dumps({"passed": True, "issues": [], "revised_content": None})

            await safety_agent.run(state)

            call_args = mock_chat.call_args
            prompt = call_args[0][0][0]["content"]
            # 上下文应为前三篇
            assert "doc1" in prompt
            assert "doc2" in prompt
            assert "doc3" in prompt
            assert "doc4" not in prompt
