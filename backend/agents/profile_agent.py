"""
backend/agents/profile_agent.py
ProfileAgent：从对话中提取并更新学生画像，判断字段完整性，决定是否放行到 planner。
"""

from __future__ import annotations

import json
import uuid

from langgraph.graph import END
from langchain_core.runnables import RunnableConfig
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schemas import AgentState, StudentProfileIn, StudentProfileOut
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion

# 提取画像字段的 prompt
_EXTRACT_PROMPT = """你是一个学生画像分析助手。
从学生的消息中提取以下字段，以 JSON 格式返回，无法提取的字段设为 null：
{
  "major": "学生专业",
  "learning_goal": "学习目标",
  "cognitive_style": "visual|text|practice",
  "daily_time_minutes": 整数,
  "knowledge_mastered": ["已掌握知识点"],
  "knowledge_weak": ["薄弱知识点"],
  "error_prone": ["容易出错的知识点"],
  "current_progress": "当前学习进度描述"
}
只返回 JSON，不要包含其他内容。"""

# 判断消息是否包含资源请求意图的 prompt
_INTENT_PROMPT = """判断学生消息是否包含"想要学习某个具体知识点或请求生成学习资源"的意图。
只回答 yes 或 no。"""

# 画像初始化阶段的追问 prompt
_ONBOARDING_CLARIFY_PROMPT = """你是一个友好的学习助手，正在帮助新用户建立学习画像。
当前已知画像信息：{known_fields}
还缺少的关键信息：{missing_fields}

请用自然、友好的语气，针对缺失信息提出 1-2 个问题，引导用户补充。
不要列清单，像朋友聊天一样。"""

# 有资源请求但画像不足时的追问 prompt
_RESOURCE_CLARIFY_PROMPT = """用户想要学习"{topic}"，但我还需要了解更多信息才能生成个性化资源。
当前已知画像：{known_fields}
缺少的必要信息：{missing_fields}

请用自然语气，在提到"我来帮你生成资料"的同时，追问缺失的信息。控制在 2-3 句话内。"""


def _profile_to_known_fields(profile) -> dict:
    """将 StudentProfileOut 转为非空字段字典。"""
    if profile is None:
        return {}
    data = profile.model_dump(exclude_none=True)
    return {k: v for k, v in data.items() if v not in ([], "", None)}


def _merge_profile_in_memory(state: AgentState, updates: dict) -> AgentState:
    """将提取的字段合并到 state.profile（内存级别，db 不可用时回退）。"""
    if state.profile is not None:
        existing = state.profile.model_dump()
        for k, v in updates.items():
            if v is not None:
                if isinstance(v, list) and isinstance(existing.get(k), list):
                    existing[k] = list(set(existing[k] + v))
                else:
                    existing[k] = v
        state = state.model_copy(update={"profile": StudentProfileIn(**existing)})
    else:
        # profile 为 None 时，从 updates 创建新画像
        profile_data = {k: v for k, v in updates.items() if v is not None}
        if profile_data:
            state = state.model_copy(update={"profile": StudentProfileIn(**profile_data)})
    return state


def _check_profile_complete(state: AgentState) -> bool:
    """
    判断当前画像是否满足资源生成的最小要求。
    kp_id 由 planner 推断，此处检查 profile 本身是否有足够上下文让 planner 工作。
    最低要求：learning_goal 或 knowledge_weak 至少有一个非空。
    """
    if state.profile is None:
        return False
    p = state.profile
    has_goal = bool(p.learning_goal)
    has_weak = bool(p.knowledge_weak)
    has_mastered = bool(p.knowledge_mastered)
    return has_goal or has_weak or has_mastered


async def run(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    ProfileAgent 节点入口。

    1. 调用 LLM 从 user_message 提取画像字段，增量合并到 DB
    2. 判断消息意图（纯介绍 vs 资源请求）
    3. 判断画像完整性，写入 profile_complete 和 clarify_message
    """
    # 从 config 中获取 db（LangGraph 通过 config 传递上下文）
    db = None
    if config and "configurable" in config:
        db = config["configurable"].get("db")

    # -- 1. 提取画像字段 --
    extract_messages = [
        {"role": "system", "content": _EXTRACT_PROMPT},
        {"role": "user", "content": state.user_message},
    ]
    try:
        raw = await chat_completion(extract_messages, temperature=0.1)
        # 处理 markdown 代码块包裹的 JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        updates = json.loads(cleaned)
    except (json.JSONDecodeError, Exception) as e:
        import logging
        logging.getLogger(__name__).error(f"画像提取失败: {e}, raw={raw if 'raw' in dir() else 'N/A'}")
        updates = {}

    # -- 2. 合并到数据库 --
    user_uuid = uuid.UUID(state.user_id)
    import logging
    _logger = logging.getLogger(__name__)
    _logger.warning(f"[ProfileAgent] db={db}, config_keys={list(config.keys()) if config else 'None'}")
    if db is not None:
        try:
            state = state.model_copy(update={"profile": await profile_svc.merge_chat_updates(user_uuid, updates, db)})
        except Exception as e:
            _logger.error(f"DB 合并画像失败: {e}")
            # 数据库更新失败时，回退到内存级别合并
            state = _merge_profile_in_memory(state, updates)
    else:
        # 无 db 时使用内存合并
        state = _merge_profile_in_memory(state, updates)

    # -- 3. 判断消息意图 --
    intent_messages = [
        {"role": "system", "content": _INTENT_PROMPT},
        {"role": "user", "content": state.user_message},
    ]
    try:
        intent_raw = await chat_completion(intent_messages, temperature=0.0)
        is_resource_request = intent_raw.strip().lower().startswith("yes")
    except Exception:
        is_resource_request = False

    # -- 4. 判断画像完整性 --
    complete = _check_profile_complete(state)
    state = state.model_copy(update={"profile_complete": complete})

    import logging
    _log = logging.getLogger(__name__)
    _log.warning(f"[ProfileAgent] updates={updates}")
    _log.warning(f"[ProfileAgent] profile={state.profile}")
    _log.warning(f"[ProfileAgent] complete={complete}, is_resource_request={is_resource_request}")

    # -- 5. 若需要追问，生成 clarify_message --
    if not complete or (is_resource_request and not complete):
        known = _profile_to_known_fields(state.profile)
        missing = []
        if not (state.profile and state.profile.learning_goal):
            missing.append("学习目标")
        if not (state.profile and (state.profile.knowledge_weak or state.profile.knowledge_mastered)):
            missing.append("知识基础（已掌握/薄弱知识点）")
        if not (state.profile and state.profile.cognitive_style):
            missing.append("学习偏好（图文/代码/文字）")

        if is_resource_request:
            # 提取用户想学的主题
            topic = state.user_message[:50]
            clarify_prompt = _RESOURCE_CLARIFY_PROMPT.format(
                topic=topic,
                known_fields=json.dumps(known, ensure_ascii=False),
                missing_fields="、".join(missing),
            )
        else:
            clarify_prompt = _ONBOARDING_CLARIFY_PROMPT.format(
                known_fields=json.dumps(known, ensure_ascii=False),
                missing_fields="、".join(missing) if missing else "暂无",
            )

        try:
            clarify_msg = await chat_completion(
                [{"role": "user", "content": clarify_prompt}], temperature=0.7
            )
        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"LLM 调用失败: {e}")
            clarify_msg = "能告诉我你的学习目标和目前的知识基础吗？"

        state = state.model_copy(update={
            "clarify_message": clarify_msg,
            "final_content": clarify_msg,
        })

    return state


def route_after_profile(state: AgentState) -> str:
    """
    profile_agent 出口路由函数。

    - 情况A（纯介绍，无资源请求）或 情况B（有请求但画像不足）→ END
    - 情况C（画像足够）→ "planner_agent"
    """
    if state.profile_complete:
        return "planner_agent"
    return END
