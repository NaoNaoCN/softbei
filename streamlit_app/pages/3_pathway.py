"""
streamlit_app/pages/3_pathway.py
学习路径页：展示知识图谱和个性化学习路径，支持节点点击跳转生成页。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.mindmap import render_kg_graph

st.set_page_config(page_title="学习路径", page_icon="🗺️", layout="wide")
st.title("🗺️ 学习路径 & 知识图谱")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_kg_graph(root_id: str | None = None, depth: int = 3) -> dict | None:
    """获取知识图谱数据。"""
    try:
        params = {"depth": depth}
        if root_id:
            params["root_id"] = root_id
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params=params)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_pathways(user_id: str) -> list[dict]:
    """获取用户的学习路径列表。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/pathways", params={"user_id": user_id})
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

tab_graph, tab_path = st.tabs(["知识图谱", "我的学习路径"])

with tab_graph:
    depth = st.slider("展开深度", 1, 5, 3)
    graph_data = fetch_kg_graph(depth=depth)
    if graph_data:
        render_kg_graph(graph_data)
    else:
        st.info("暂无知识图谱数据，请先导入知识库。")

with tab_path:
    pathways = fetch_pathways(user_id)
    if not pathways:
        st.info("暂无学习路径，Agent 将在对话后自动生成。")
    for path in pathways:
        with st.expander(f"📌 {path['name']}", expanded=True):
            items = path.get("items", [])
            for item in items:
                icon = "✅" if item["is_completed"] else "⭕"
                col1, col2 = st.columns([4, 1])
                with col1:
                    st.write(f"{icon} {item['order_index']}. {item['kp_name']}")
                with col2:
                    if st.button("生成资源", key=f"gen_{item['kp_id']}"):
                        st.session_state["current_kp_id"] = item["kp_id"]
                        st.switch_page("pages/2_generate.py")
