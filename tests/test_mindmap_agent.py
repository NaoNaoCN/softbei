"""
tests/test_mindmap_agent.py
backend/agents/mindmap_agent.py 单元测试。
"""

import json
import uuid

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from backend.agents import mindmap_agent
from backend.models.schemas import AgentState


class TestMindmapAgentRun:
    """mindmap_agent.run 测试。"""

    @pytest.mark.asyncio
    async def test_run_sets_draft_content_with_valid_json(self):
        """run 应将 LLM 返回的 JSON 写入 draft_content。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成思维导图",
            kp_id="kp_01_01",
        )

        mindmap_json = json.dumps({
            "name": "反向传播",
            "children": [{"name": "前向传播"}, {"name": "梯度下降"}],
        })

        with patch("backend.agents.mindmap_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.mindmap_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = mindmap_json

                result = await mindmap_agent.run(state)

                # 验证是合法 JSON
                parsed = json.loads(result.draft_content)
                assert parsed["name"] == "反向传播"
                assert len(parsed["children"]) == 2

    @pytest.mark.asyncio
    async def test_run_extracts_json_from_markdown(self):
        """LLM 返回带 Markdown 标记时能提取 JSON 部分。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成思维导图",
            kp_id="kp_01",
        )

        raw_response = """以下是思维导图：
```json
{"name": "测试", "children": []}
```"""

        with patch("backend.agents.mindmap_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.mindmap_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.return_value = raw_response

                result = await mindmap_agent.run(state)

                parsed = json.loads(result.draft_content)
                assert parsed["name"] == "测试"

    @pytest.mark.asyncio
    async def test_run_handles_chat_failure(self):
        """LLM 失败时 draft_content 包含错误信息。"""
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="生成思维导图",
            kp_id="kp_01",
        )

        with patch("backend.agents.mindmap_agent.retrieve_by_kp", new_callable=AsyncMock) as mock_retrieve:
            mock_retrieve.return_value = []

            with patch("backend.agents.mindmap_agent.chat_completion", new_callable=AsyncMock) as mock_chat:
                mock_chat.side_effect = Exception("LLM error")

                result = await mindmap_agent.run(state)

                assert "思维导图生成失败" in result.draft_content
