"""
backend/agents/planner_agent.py
PlannerAgent：解析用户意图，决定生成哪种资源类型并确定目标知识点。
"""

from __future__ import annotations

import json

from backend.config import config
from backend.models.schemas import AgentState, ResourceType
from backend.agents.utils import parse_json_llm_response
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion
from langchain_core.runnables import RunnableConfig
from loguru import logger  # noqa: F401


SYSTEM_PROMPT = """你是一个学习计划分析助手。
根据学生的问题和画像，判断：
1. 学生想要生成什么类型的学习资源：
   - doc: 学习文档（默认，当学生想学习某个知识点时）
   - mindmap: 思维导图（当学生想要知识结构概览时）
   - quiz: 测验题目（当学生想测试自己时）
   - code: 代码示例（当学生想看代码实现时）
   - summary: 知识总结（当学生想要复习总结时）
   - kg: 知识图谱构建（当学生想构建知识图谱、分析知识结构时）
2. 目标知识点名称（从学生消息中提取）
3. 如果学生明确要求多种资源（如"帮我生成文档和测验"），将主资源放在 resource_type，其余放在 extra_types 数组中

{kp_list_section}

以 JSON 格式返回：{{"resource_type": "doc", "kp_id": "知识点名称", "extra_types": []}}
resource_type 不能为 null，如果无法判断具体类型，默认使用 "doc"。
kp_id 使用学生提到的知识点名称，如"多层感知机"、"反向传播"等。
extra_types 仅当学生明确要求多种资源时才填写，否则为空数组。例如学生说"生成文档和测验题"，则 resource_type="doc", extra_types=["quiz"]。
只返回 JSON，不要包含其他内容。"""


_INTENT_CLASSIFY_PROMPT = """判断学生的消息属于哪种类型：
1. "generate" — 学生想要生成新的学习资源（学习某个知识点、生成文档/思维导图/测验/代码/总结/知识图谱）
2. "clarify" — 学生在对之前的对话内容进行追问、请求解释、要求展开某个部分、询问细节

判断依据：
- 如果消息中包含"你提到的"、"上面的"、"刚才的"、"第X部分"、"详细解释"、"展开说说"等指代之前回答的表述 → clarify
- 如果消息是一个新的知识点学习请求或资源生成请求 → generate
- 如果不确定，默认 generate

只返回 JSON：{{"intent": "generate"}} 或 {{"intent": "clarify"}}
不要包含其他内容。"""


async def run(state: AgentState, config: RunnableConfig) -> AgentState:
    """
    PlannerAgent 节点入口。

    职责：
    1. 结合 user_message 和 profile 分析意图
    2. 确定 resource_type 和 kp_id
    3. 写入 state 供后续 Agent 使用

    如果 state 中已预设了 resource_type 和 kp_id（直接生成模式），跳过 LLM 分析。
    """
    # 如果已经预设了 resource_type 和 kp_id，直接跳过
    if state.resource_type and state.kp_id:
        logger.info(
            f"[PlannerAgent] 跳过分析（已预设 resource_type={state.resource_type}, kp_id={state.kp_id}）"
        )
        return state
    # 从 config 中获取 db
    db = None
    if config and "configurable" in config:
        db = config["configurable"].get("db")

    # -- 1. 构建画像上下文 --
    profile_ctx = ""
    if state.profile:
        profile_ctx = await profile_svc.build_profile_context(state.profile)
    logger.info(f"[PlannerAgent] profile_ctx={profile_ctx}")  # 调试输出

    # -- 1.5 意图分类：generate vs clarify --
    lookback = config.agents.planner.history_lookback_messages
    if state.chat_history:
        # 只有有历史时才需要判断是否为追问
        history_summary = "\n".join(
            f"{m['role']}: {m['content'][:100]}" for m in state.chat_history[-lookback:]
        )
        classify_prompt = _INTENT_CLASSIFY_PROMPT
        classify_messages = [
            {"role": "system", "content": classify_prompt},
        ]
        classify_messages.extend(state.chat_history[-lookback:])
        classify_messages.append({"role": "user", "content": state.user_message})
        try:
            classify_raw = await chat_completion(classify_messages, temperature=config.agents.planner.intent_temperature)
            cleaned_classify = parse_json_llm_response(classify_raw)
            classify_result = json.loads(cleaned_classify)
            intent = classify_result.get("intent", "generate")
            if intent == "clarify":
                logger.info(f"[PlannerAgent] 意图分类: clarify，路由到 clarify_agent")
                state = state.model_copy(update={"intent_type": "clarify"})
                return state
        except Exception as e:
            logger.warning(f"[PlannerAgent] 意图分类失败: {e}，默认 generate")

    state = state.model_copy(update={"intent_type": "generate"})

    # -- 2. 获取可用知识点列表（按用户过滤 + 上限保护）--
    kp_list = ""
    if db:
        try:
            from sqlalchemy import or_, select as sa_select
            from backend.db.models import KGNode
            # 只查当前用户的知识点 + 公共知识点，上限 500 条防止无界增长
            result = await db.execute(
                sa_select(KGNode)
                .where(
                    or_(
                        KGNode.user_id == state.user_id,
                        KGNode.user_id.is_(None),
                    )
                )
                .limit(500)
            )
            nodes = result.scalars().all()
            kp_list = "\n".join([f"- {n.id}: {n.name}" for n in nodes])
        except Exception:
            kp_list = "（知识点列表获取失败）"

    # -- 3. 调用 LLM 分析意图 --
    logger.info(f"[PlannerAgent] Analyzing intent.")
    kp_section = ""
    if kp_list:
        kp_section = f"可用知识点（优先从中选择）：\n{kp_list}"
    prompt = SYSTEM_PROMPT.format(kp_list_section=kp_section)
    messages = [
        {"role": "system", "content": prompt},
    ]
    # 注入对话历史，帮助理解"再来一个"、"换成代码"等指代
    messages.extend(state.chat_history)
    messages.append(
        {"role": "user", "content": f"学生画像：{profile_ctx}\n\n学生需求：{state.user_message}"}
    )

    try:
        raw = await chat_completion(messages, temperature=config.agents.planner.classify_temperature)
        # 处理 markdown 代码块包裹的 JSON
        cleaned = parse_json_llm_response(raw)
        result = json.loads(cleaned)
        resource_type_str = result.get("resource_type")
        kp_id = result.get("kp_id")

        # 设置 resource_type
        if resource_type_str:
            try:
                state = state.model_copy(update={"resource_type": ResourceType(resource_type_str)})
            except ValueError:
                state = state.model_copy(update={"resource_type": None})

        # 设置 kp_id
        if kp_id:
            state = state.model_copy(update={"kp_id": kp_id})

        # 解析 extra_types（多资源意图）
        extra_types_raw = result.get("extra_types", [])
        if extra_types_raw and isinstance(extra_types_raw, list):
            valid_extra = []
            for et in extra_types_raw:
                try:
                    ResourceType(et)
                    valid_extra.append(et)
                except ValueError:
                    pass
            if valid_extra:
                metadata = dict(state.metadata)
                metadata["extra_resource_types"] = valid_extra
                state = state.model_copy(update={"metadata": metadata})
                logger.info(f"[PlannerAgent] 检测到多资源意图: extra_types={valid_extra}")
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"[PlannerAgent] LLM 解析失败: {e}, raw={raw if 'raw' in dir() else 'N/A'}")
        # 解析失败时默认生成文档
        state = state.model_copy(update={"resource_type": ResourceType.doc})

    # 确保 resource_type 有值
    if not state.resource_type:
        state = state.model_copy(update={"resource_type": ResourceType.doc})

    # 确保 kp_id 有值（从用户消息中截取）
    if not state.kp_id:
        state = state.model_copy(update={"kp_id": state.user_message[:config.agents.planner.fallback_kp_id_length]})

    logger.info(f"[PlannerAgent] resource_type={state.resource_type}, kp_id={state.kp_id}")

    return state


def route_by_resource_type(state: AgentState) -> str:
    """
    LangGraph 条件路由：根据 intent_type 和 resource_type 决定下一个 Agent 节点名称。
    返回值需与 graph.py 中注册的节点名对应。
    """
    # 追问/澄清意图 → clarify_agent
    if state.intent_type == "clarify":
        return "clarify_agent"

    mapping = {
        ResourceType.doc: "doc_agent",
        ResourceType.mindmap: "mindmap_agent",
        ResourceType.quiz: "quiz_agent",
        ResourceType.code: "code_agent",
        ResourceType.summary: "summary_agent",
        ResourceType.kg: "kg_agent",
    }
    if state.resource_type and state.resource_type in mapping:
        return mapping[state.resource_type]
    return "recommend_agent"  # 默认推荐


SMART_PLAN_PROMPT = """你是一个学习资源规划助手。根据学生画像和目标知识点，推荐最适合的 2-3 种资源类型组合。

可选资源类型：
- doc: 学习文档（适合初学、系统学习）
- mindmap: 思维导图（适合梳理知识结构、复习）
- quiz: 测验题目（适合检验掌握程度、备考）
- code: 代码示例（适合编程类知识点）
- summary: 知识总结（适合快速回顾、考前复习）

规则：
- 根据学生的认知风格、学习目标、薄弱点来推荐
- 编程相关知识点优先推荐 code
- 薄弱知识点优先推荐 quiz + doc
- 复习阶段优先推荐 summary + mindmap
- 返回 2-3 种最合适的类型

以 JSON 数组格式返回，如：["doc", "quiz", "code"]
只返回 JSON 数组，不要包含其他内容。"""


async def plan_resource_types(
    user_id: int,
    kp_id: str,
    db=None,
) -> list[ResourceType]:
    """
    独立调用 planner LLM，根据用户画像和知识点推荐资源类型组合。
    不依赖 LangGraph 图执行。
    """
    # 获取用户画像
    profile_ctx = ""
    if db:
        try:
            profile = await profile_svc.get_profile(int(user_id), db)
            if profile:
                profile_ctx = f"专业: {profile.major or '未知'}, 目标: {profile.learning_goal or '未知'}, 认知风格: {profile.cognitive_style or '未知'}, 薄弱点: {profile.knowledge_weak or []}"
        except Exception:
            pass

    # 获取知识点名称
    kp_name = kp_id
    if db and kp_id.startswith("kp_"):
        try:
            from backend.db.crud import select_one as db_select_one
            from backend.db.models import KGNode
            node = await db_select_one(db, KGNode, filters={"id": kp_id})
            if node:
                kp_name = node.name
        except Exception:
            pass

    messages = [
        {"role": "system", "content": SMART_PLAN_PROMPT},
        {"role": "user", "content": f"学生画像：{profile_ctx}\n目标知识点：{kp_name}"},
    ]

    try:
        raw = await chat_completion(messages, temperature=config.agents.planner.smart_plan_temperature)
        cleaned = parse_json_llm_response(raw)
        result = json.loads(cleaned)
        if isinstance(result, list):
            types = []
            for rt_str in result:
                try:
                    types.append(ResourceType(rt_str))
                except ValueError:
                    continue
            if types:
                return types
    except Exception as e:
        logger.warning(f"[plan_resource_types] LLM 解析失败: {e}")

    # 默认推荐
    default_types = []
    for rt_str in config.agents.planner.smart_plan_default_types:
        try:
            default_types.append(ResourceType(rt_str))
        except ValueError:
            pass
    return default_types or [ResourceType.doc, ResourceType.quiz]
