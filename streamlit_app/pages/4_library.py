"""
streamlit_app/pages/4_library.py
资源库页：浏览、搜索、筛选已生成的学习资源。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.resource_card import render_resource_card

st.set_page_config(page_title="资源库", page_icon="📚")
st.title("📚 我的资源库")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_resources(
    user_id: str,
    resource_type: str | None = None,
    kp_id: str | None = None,
    skip: int = 0,
    limit: int = 20,
) -> list[dict]:
    """获取资源列表。"""
    try:
        params = {"user_id": user_id, "skip": skip, "limit": limit}
        if resource_type and resource_type != "全部":
            params["resource_type"] = resource_type
        if kp_id:
            params["kp_id"] = kp_id
        resp = httpx.get(f"{API_BASE_URL}/resources", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def delete_resource(resource_id: str) -> bool:
    """删除资源。"""
    try:
        resp = httpx.delete(f"{API_BASE_URL}/resources/{resource_id}")
        return resp.status_code == 200
    except Exception:
        return False


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

# 筛选区
col_filter1, col_filter2, col_refresh = st.columns([2, 2, 1])
with col_filter1:
    type_filter = st.selectbox(
        "资源类型",
        ["全部", "doc", "mindmap", "quiz", "code", "summary"],
        format_func=lambda x: {
            "全部": "🗂️ 全部",
            "doc": "📄 文档",
            "mindmap": "🗺️ 思维导图",
            "quiz": "📝 测验",
            "code": "💻 代码",
            "summary": "📋 总结",
        }.get(x, x),
    )
with col_refresh:
    st.write("")  # 占位对齐
    refresh = st.button("🔄 刷新")

# 分页状态
if "lib_skip" not in st.session_state:
    st.session_state["lib_skip"] = 0

resources = fetch_resources(
    user_id,
    resource_type=type_filter if type_filter != "全部" else None,
    skip=st.session_state["lib_skip"],
)

if not resources:
    st.info("暂无资源。请前往"生成资源"页面创建学习材料。")
else:
    cols = st.columns(2)
    for i, res in enumerate(resources):
        with cols[i % 2]:
            render_resource_card(res)
            if st.button("🗑️ 删除", key=f"del_{res['id']}"):
                if delete_resource(res["id"]):
                    st.success("已删除")
                    st.rerun()

# 分页按钮
col_prev, col_next = st.columns(2)
with col_prev:
    if st.session_state["lib_skip"] > 0:
        if st.button("← 上一页"):
            st.session_state["lib_skip"] = max(0, st.session_state["lib_skip"] - 20)
            st.rerun()
with col_next:
    if len(resources) == 20:
        if st.button("下一页 →"):
            st.session_state["lib_skip"] += 20
            st.rerun()
