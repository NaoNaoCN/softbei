"""
streamlit_app/pages/3_pathway.py
学习路径页：展示知识图谱和个性化学习路径，支持节点点击跳转生成页。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL

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
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params=params, timeout=15.0)
        if resp.status_code == 200:
            return resp.json()
    except httpx.ConnectError:
        st.warning("无法连接到后端服务，请确保后端已启动。")
    except Exception as e:
        st.error(f"获取知识图谱失败：{e}")
    return None


def fetch_pathways(user_id: str) -> list[dict]:
    """获取用户的学习路径列表。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/pathways", params={"user_id": user_id}, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def fetch_learning_records(user_id: str, limit: int = 10) -> list[dict]:
    """获取学习记录。"""
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/records",
            params={"user_id": user_id, "limit": limit},
            timeout=10.0,
        )
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

tab_graph, tab_path, tab_records = st.tabs(["知识图谱", "我的学习路径", "学习记录"])

with tab_graph:
    col_depth, col_root, col_refresh = st.columns([1, 2, 1])
    with col_depth:
        depth = st.selectbox("展开深度", [1, 2, 3, 4, 5], index=2)
    with col_root:
        # 获取所有节点作为根节点选项
        graph_data = fetch_kg_graph(depth=1)
        root_options = ["全部"]
        if graph_data and "nodes" in graph_data:
            for node in graph_data["nodes"]:
                if node.get("type") in ("Course", "Chapter"):
                    root_options.append(node.get("name", node["id"]))
        selected_root_name = st.selectbox("选择根节点", root_options)
    with col_refresh:
        st.write("")
        if st.button("🔄 刷新", key="refresh_graph"):
            st.rerun()

    # 根据选择确定 root_id
    root_id = None
    if selected_root_name != "全部" and graph_data:
        for node in graph_data.get("nodes", []):
            if node.get("name") == selected_root_name:
                root_id = node.get("id")
                break

    full_graph = fetch_kg_graph(root_id=root_id, depth=depth)
    if full_graph:
        from streamlit_app.components.mindmap import render_kg_graph
        render_kg_graph(full_graph)

        # 展示节点列表供点击
        st.markdown("---")
        st.subheader("📚 知识点列表")
        nodes = full_graph.get("nodes", [])
        kp_nodes = [n for n in nodes if n.get("type") in ("KnowledgePoint", "SubPoint", "Concept")]
        if kp_nodes:
            cols = st.columns(3)
            for i, node in enumerate(kp_nodes):
                with cols[i % 3]:
                    node_name = node.get("name", node.get("id", "未知"))
                    node_type = node.get("type", "")
                    type_icon = {"KnowledgePoint": "📌", "SubPoint": "📍", "Concept": "💡"}.get(node_type, "📦")
                    if st.button(f"{type_icon} {node_name}", key=f"kp_{node['id']}"):
                        st.session_state["current_kp_id"] = node["id"]
                        st.session_state["current_kp_name"] = node_name
                        st.switch_page("pages/2_generate.py")
        else:
            st.info("暂无知识点数据。")
    else:
        st.info("暂无知识图谱数据，请先导入知识库。")

with tab_path:
    st.markdown("个性化学习路径由系统根据您的画像自动生成。")
    pathways = fetch_pathways(user_id)

    if not pathways:
        st.info("暂无学习路径。您可以通过生成资源或与 AI 对话来创建学习路径。")
        # 提供快速生成入口
        if st.button("➕ 创建学习路径"):
            st.switch_page("pages/2_generate.py")
    else:
        for path in pathways:
            path_name = path.get("name", f"路径 {path.get('id', '')[:8]}")
            items = path.get("items", [])
            completed = sum(1 for item in items if item.get("is_completed"))
            progress = completed / len(items) * 100 if items else 0

            with st.expander(f"📌 {path_name}（{completed}/{len(items)} 完成）"):
                st.progress(progress / 100, text=f"完成进度：{progress:.0f}%")

                if items:
                    for item in items:
                        icon = "✅" if item.get("is_completed") else "⭕"
                        kp_name = item.get("kp_name", item.get("kp_id", "未知"))
                        order = item.get("order_index", 0)
                        col1, col2, col3 = st.columns([4, 1, 1])
                        with col1:
                            st.write(f"{icon} **{order}. {kp_name}**")
                        with col2:
                            if not item.get("is_completed"):
                                if st.button("📖 学习", key=f"learn_{item.get('kp_id')}_{order}"):
                                    st.session_state["current_kp_id"] = item.get("kp_id")
                                    st.session_state["current_kp_name"] = kp_name
                                    st.switch_page("pages/2_generate.py")
                        with col3:
                            if st.button("📝 测验", key=f"quiz_{item.get('kp_id')}_{order}"):
                                st.session_state["current_kp_id"] = item.get("kp_id")
                                st.switch_page("pages/5_evaluate.py")
                else:
                    st.info("该路径暂无知识点。")

with tab_records:
    st.subheader("最近学习记录")
    records = fetch_learning_records(user_id, limit=20)

    if not records:
        st.info("暂无学习记录。开始学习后将自动记录您的学习行为。")
    else:
        # 统计信息
        col_stat1, col_stat2, col_stat3 = st.columns(3)
        total_duration = sum(r.get("duration_seconds", 0) for r in records)
        with col_stat1:
            st.metric("学习次数", len(records))
        with col_stat2:
            minutes = total_duration // 60
            st.metric("累计时长", f"{minutes} 分钟")
        with col_stat3:
            resource_ids = set(r.get("resource_id") for r in records if r.get("resource_id"))
            st.metric("涉及资源", len(resource_ids))

        st.markdown("---")
        st.subheader("详细记录")
        for record in records:
            action = record.get("action", "unknown")
            action_icon = {"view": "👁️", "generate": "✨", "quiz": "📝", "complete": "✅"}.get(action, "📦")
            resource_id = record.get("resource_id", "")[:8]
            duration = record.get("duration_seconds", 0)
            created_at = record.get("created_at", "")[:16] if record.get("created_at") else "未知"

            col_rec1, col_rec2, col_rec3 = st.columns([3, 1, 1])
            with col_rec1:
                st.write(f"{action_icon} {action} | 资源ID: ...{resource_id}")
            with col_rec2:
                st.write(f"⏱️ {duration}秒")
            with col_rec3:
                st.write(f"🕐 {created_at}")
