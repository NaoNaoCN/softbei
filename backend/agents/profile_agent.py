"""
backend/agents/profile_agent.py
ProfileAgent：从对话中提取并更新学生画像信息。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


SYSTEM_PROMPT = """你是一个学生画像分析助手。
你的任务是从学生的自我描述或对话中，提取以下信息并以 JSON 格式返回：
- major: 学生专业
- learning_goal: 学习目标
- cognitive_style: 认知风格（visual/text/practice）
- daily_time_minutes: 每日学习时间（分钟）
- knowledge_mastered: 已掌握的知识点列表
- knowledge_weak: 薄弱知识点列表
- error_prone: 容易出错的知识点列表
- current_progress: 当前学习进度描述

只返回 JSON，不要包含其他内容。若某字段无法从对话中提取，设为 null。
"""


async def run(state: AgentState) -> AgentState:
    """
    ProfileAgent 节点入口。

    职责：
    1. 调用 LLM 分析 user_message，提取画像字段
    2. 调用 profile_service.merge_chat_updates 更新数据库
    3. 将最新 profile 写回 state

    :param state: 当前 LangGraph 全局状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. messages = [{"role": "system", "content": SYSTEM_PROMPT},
    #                {"role": "user", "content": state.user_message}]
    # 2. raw_json = await chat_completion(messages, temperature=0.3)
    # 3. updates = json.loads(raw_json)
    # 4. state.profile = await merge_chat_updates(UUID(state.user_id), updates, db)
    raise NotImplementedError


def should_update_profile(state: AgentState) -> bool:
    """
    路由判断：是否需要触发画像更新。
    若消息中包含自我介绍、学习目标等关键词，则返回 True。
    """
    # TODO: 关键词匹配或 LLM 分类
    raise NotImplementedError
