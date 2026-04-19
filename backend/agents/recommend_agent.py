"""
backend/agents/recommend_agent.py
RecommendAgent：基于学生画像和学习历史推荐下一步学习知识点。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


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


async def run(state: AgentState) -> AgentState:
    """
    RecommendAgent 节点入口。

    职责：
    1. 从知识图谱查询与已学知识点相邻的节点
    2. 结合画像调用 LLM 选出最优推荐
    3. 将推荐列表存入 state.metadata["recommendations"]

    :param state: 当前状态
    :return:      更新后的状态
    """
    # TODO:
    # 1. 查询 kg_edge 获取候选知识点
    # 2. 格式化 profile 上下文
    # 3. 调用 LLM 生成推荐 JSON
    # 4. state.metadata["recommendations"] = recommendations
    raise NotImplementedError
