"""
backend/agents/utils.py
Agent 公共工具函数。
"""

from __future__ import annotations

from backend.models.schemas import AgentState


async def resolve_kp_name(state: AgentState, config: dict | None = None) -> str:
    """
    从 state.kp_id 解析出知识点名称。

    优先从 DB 查 KGNode.name，查不到则直接用 kp_id 原值
    （对话式生成时 kp_id 本身就是用户输入的名称）。
    """
    kp_id = state.kp_id
    if not kp_id:
        return "未知知识点"
    print(f"[resolve_kp_name] Resolving kp_name for kp_id = {kp_id}")

    # 如果 kp_id 不像是哈希 ID（不以 kp_ 开头），说明本身就是名称
    if not kp_id.startswith("kp_"):
        return kp_id

    # 尝试从 DB 查名称
    db = None
    if config and "configurable" in config:
        db = config["configurable"].get("db")

    if db:
        try:
            from backend.db.crud import select_one
            from backend.db.models import KGNode
            node = await select_one(db, KGNode, filters={"id": kp_id})
            if node:
                print(f"[resolve_kp_name] Found kp_name in DB: {node.name}")
                return node.name
            print(f"[resolve_kp_name] No DB record found for kp_id {kp_id}, using kp_id as name")
        except Exception:
            print(f"[resolve_kp_name] Error querying DB for kp_id {kp_id}, using kp_id as name")
            pass
    else:
        print(f"[resolve_kp_name] No DB available in config, using kp_id as name")

    return kp_id
