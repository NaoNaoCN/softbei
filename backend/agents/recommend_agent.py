"""
backend/agents/recommend_agent.py
RecommendAgent：基于学生画像和学习历史推荐下一步学习知识点。
"""

from __future__ import annotations

import json

from backend.models.schemas import AgentState
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion
from backend.db.crud import select as db_select


SYSTEM_PROMPT = """你是一位智能学习顾问。
根据学生的当前画像和已学知识点，从知识图谱中推荐 3-5 个下一步应学习的知识点。

学生画像：
{profile}

已学知识点（已掌握）：{mastered}
薄弱知识点：{weak}
学习目标：{goal}

可选知识点（来自知识图谱）：
{available_kps}

以 JSON 数组返回，每项包含：
{{"kp_id": "...", "kp_name": "...", "reason": "推荐原因"}}
"""


async def run(state: AgentState, config: dict | None = None) -> AgentState:
    """
    RecommendAgent 节点入口。

    职责：
    1. 从知识图谱查询与已学知识点相邻的节点
    2. 结合画像调用 LLM 选出最优推荐
    3. 将推荐列表存入 state.metadata["recommendations"]
    """
    # 从 config 获取 db
    db = None
    if config and "configurable" in config:
        db = config["configurable"].get("db")

    # 构建画像上下文
    if state.profile:
        try:
            profile_text = await profile_svc.build_profile_context(state.profile)
        except Exception:
            profile_text = "（暂无画像信息）"
    else:
        profile_text = "（暂无画像信息）"

    # 获取已掌握和薄弱知识点
    mastered = []
    weak = []
    goal = ""
    if state.profile:
        mastered = getattr(state.profile, "knowledge_mastered", []) or []
        weak = getattr(state.profile, "knowledge_weak", []) or []
        goal = getattr(state.profile, "learning_goal", "") or ""

    # 查询可用知识点
    available_kps = []
    if db:
        try:
            from backend.db.models import KGNode
            nodes = await db_select(db, KGNode)
            available_kps = [f"- {n.id}: {n.name}" for n in nodes]
        except Exception:
            available_kps = ["（知识点列表获取失败）"]
    else:
        available_kps = ["（无数据库连接）"]

    kp_list = "\n".join(available_kps) if available_kps else "（无可用知识点）"

    # 构造 prompt
    prompt = SYSTEM_PROMPT.format(
        profile=profile_text,
        mastered=", ".join(mastered) if mastered else "无",
        weak=", ".join(weak) if weak else "无",
        goal=goal or "未设定",
        available_kps=kp_list,
    )

    try:
        raw = await chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=2000,
        )
        recommendations = json.loads(raw)

        # 确保是列表
        if not isinstance(recommendations, list):
            recommendations = []

        # 更新 state
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = recommendations
        state = state.model_copy(update={
            "metadata": new_metadata,
            "final_content": json.dumps(recommendations, ensure_ascii=False),
        })
    except json.JSONDecodeError:
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = []
        state = state.model_copy(update={
            "metadata": new_metadata,
            "final_content": "[]",
        })
    except Exception as e:
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = []
        state = state.model_copy(update={
            "metadata": new_metadata,
            "final_content": f"推荐生成失败：{e}",
        })

    return state
