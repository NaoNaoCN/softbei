"""
backend/agents/recommend_agent.py
RecommendAgent：基于学生画像和学习历史推荐下一步学习知识点。
"""

from __future__ import annotations

import json
import logging

from backend.models.schemas import AgentState
from backend.services import profile as profile_svc
from backend.services.llm import chat_completion
from backend.db.crud import select as db_select
from langchain_core.runnables import RunnableConfig

_logger = logging.getLogger(__name__)


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


async def run(state: AgentState, config: RunnableConfig) -> AgentState:
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
    _logger.warning("[RecommendAgent] 开始推荐，available_kps=%d goal=%s", len(available_kps), goal or "未设定")

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
        # 去除 LLM 可能返回的 markdown 代码块包裹
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
            cleaned = cleaned.rsplit("```", 1)[0].strip()
        recommendations = json.loads(cleaned)
        _logger.warning("[RecommendAgent] 推荐生成成功，共 %d 条", len(recommendations) if isinstance(recommendations, list) else 0)

        # 确保是列表
        if not isinstance(recommendations, list):
            recommendations = []

        # 更新 state
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = recommendations
        new_metadata["kp_name"] = state.kp_id or ""  # 供前端构造路径名

        # 生成人类可读的推荐文本
        lines = []
        for i, rec in enumerate(recommendations, 1):
            name = rec.get("kp_name", "未知知识点")
            reason = rec.get("reason", "")
            lines.append(f"**{i}. {name}**")
            if reason:
                lines.append(f"   {reason}\n")
        readable = "\n".join(lines)
        new_metadata["recommendations_text"] = readable

        # 只在没有已生成内容时才写入 final_content
        if state.final_content:
            # 已有资源内容，推荐追加到末尾
            state = state.model_copy(update={
                "metadata": new_metadata,
                "final_content": state.final_content + "\n\n---\n\n**推荐下一步学习：**\n" + readable,
            })
        else:
            state = state.model_copy(update={
                "metadata": new_metadata,
                "final_content": "根据你的学习画像，推荐以下学习路径：\n\n" + readable,
            })
    except json.JSONDecodeError as e:
        _logger.warning("[RecommendAgent] JSON 解析失败: %s，raw_preview=%.200s", e, raw if 'raw' in dir() else '')
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = []
        state = state.model_copy(update={"metadata": new_metadata})
    except Exception as e:
        _logger.error("[RecommendAgent] 推荐生成失败: %s", e)
        new_metadata = dict(state.metadata) if state.metadata else {}
        new_metadata["recommendations"] = []
        state = state.model_copy(update={"metadata": new_metadata})

    return state
