"""
tests/test_schemas.py
Pydantic schema 基础校验测试（无需外部服务，可立即运行）。
"""

import uuid

import pytest

from backend.models.schemas import (
    AgentState,
    GenerateRequest,
    KGNodeType,
    QuestionType,
    ResourceType,
    StudentProfileIn,
    TaskStatus,
)


class TestStudentProfileIn:
    def test_valid_profile(self):
        p = StudentProfileIn(
            major="计算机科学",
            learning_goal="掌握深度学习基础",
            cognitive_style="visual",
            daily_time_minutes=60,
            knowledge_mastered=["线性代数", "概率论"],
            knowledge_weak=["反向传播"],
        )
        assert p.major == "计算机科学"
        assert p.daily_time_minutes == 60

    def test_daily_time_bounds(self):
        with pytest.raises(Exception):
            StudentProfileIn(daily_time_minutes=5)  # < 10
        with pytest.raises(Exception):
            StudentProfileIn(daily_time_minutes=999)  # > 480


class TestGenerateRequest:
    def test_valid_request(self):
        req = GenerateRequest(kp_id="kp_03_01", resource_type=ResourceType.doc)
        assert req.resource_type == ResourceType.doc

    def test_all_resource_types(self):
        for rt in ResourceType:
            req = GenerateRequest(kp_id="kp_01", resource_type=rt)
            assert req.resource_type == rt


class TestAgentState:
    def test_default_state(self):
        state = AgentState(
            user_id=str(uuid.uuid4()),
            session_id=str(uuid.uuid4()),
            user_message="你好",
        )
        assert state.safety_passed is True
        assert state.retrieved_docs == []
        assert state.metadata == {}

    def test_state_with_profile(self):
        profile = StudentProfileIn(major="AI", learning_goal="学习 Transformer")
        state = AgentState(
            user_id="user-1",
            session_id="session-1",
            user_message="生成思维导图",
            resource_type=ResourceType.mindmap,
            kp_id="kp_03_03",
        )
        assert state.resource_type == ResourceType.mindmap


class TestEnums:
    def test_task_status_values(self):
        assert set(TaskStatus) == {"pending", "running", "done", "failed"}

    def test_kg_node_types(self):
        expected = {"Course", "Chapter", "KnowledgePoint", "SubPoint", "Concept"}
        assert set(KGNodeType) == expected

    def test_question_types(self):
        assert "single" in QuestionType.__members__.values()
