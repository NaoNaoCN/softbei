"""
streamlit_app/pages/3_pathway.py
学习路径页：展示知识图谱和个性化学习路径，支持节点点击跳转生成页。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL, init_session_state

init_session_state()

st.set_page_config(page_title="学习路径", page_icon="🗺️", layout="wide")
st.title("🗺️ 学习路径 & 知识图谱")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_kg_graph(root_id: str | None = None, depth: int = 3, doc_id: str | None = None) -> dict | None:
    """获取知识图谱数据。"""
    try:
        params = {"depth": depth}
        if root_id:
            params["root_id"] = root_id
        if doc_id:
            params["doc_id"] = doc_id
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params=params, timeout=15.0)
        if resp.status_code == 200:
            return resp.json()
    except httpx.ConnectError:
        st.warning("无法连接到后端服务，请确保后端已启动。")
    except Exception as e:
        st.error(f"获取知识图谱失败：{e}")
    return None


def fetch_documents(user_id: str) -> list[dict]:
    """获取用户导入的文档列表。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/documents", params={"user_id": user_id}, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


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


def mark_item_completed(path_id: str, item_id: str, user_id: str) -> bool:
    """标记路径节点为已完成。"""
    try:
        resp = httpx.put(
            f"{API_BASE_URL}/pathways/{path_id}/items/{item_id}",
            json={"is_completed": True},
            params={"user_id": user_id},
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def add_item_to_pathway(path_id: str, user_id: str, kp_id: str, order_index: int) -> bool:
    """向路径追加知识点。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/pathways/{path_id}/items",
            json={"kp_id": kp_id, "order_index": order_index},
            params={"user_id": user_id},
            timeout=10.0,
        )
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

tab_graph, tab_path, tab_records = st.tabs(["知识图谱", "我的学习路径", "学习记录"])

with tab_graph:
    # 文档选择器
    docs = fetch_documents(user_id)
    doc_options = {"全部文档": None}
    for doc in docs:
        doc_title = doc.get("title", "无标题")
        doc_kp_id = doc.get("kp_id", "")
        if doc_kp_id:
            doc_options[doc_title] = doc_kp_id
    selected_doc_label = st.selectbox("选择文档", list(doc_options.keys()))
    selected_doc_id = doc_options.get(selected_doc_label)

    # 筛选控制栏
    col_depth, col_root, col_type_filter, col_search, col_refresh = st.columns([1, 2, 1, 2, 1])
    with col_depth:
        depth = st.selectbox("展开深度", [1, 2, 3, 4, 5], index=2)
    with col_root:
        # 获取所有节点作为根节点选项
        graph_data = fetch_kg_graph(depth=1, doc_id=selected_doc_id)
        root_options = ["全部"]
        if graph_data and "nodes" in graph_data:
            for node in graph_data["nodes"]:
                if node.get("type") in ("Course", "Chapter"):
                    root_options.append(node.get("name", node["id"]))
        selected_root_name = st.selectbox("选择根节点", root_options)
    with col_type_filter:
        type_options = ["全部", "Course", "Chapter", "KnowledgePoint", "SubPoint", "Concept"]
        selected_type = st.selectbox("节点类型", type_options)
    with col_search:
        search_query = st.text_input("搜索知识点", placeholder="输入名称搜索")
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

    full_graph = fetch_kg_graph(root_id=root_id, depth=depth, doc_id=selected_doc_id)
    if full_graph:
        # 按类型筛选
        if selected_type != "全部":
            full_graph["nodes"] = [n for n in full_graph["nodes"] if n.get("type") == selected_type]
            valid_ids = {n["id"] for n in full_graph["nodes"]}
            full_graph["edges"] = [e for e in full_graph["edges"] if e["source_id"] in valid_ids and e["target_id"] in valid_ids]

        # 搜索高亮
        if search_query:
            matching_ids = {n["id"] for n in full_graph["nodes"] if search_query.lower() in n.get("name", "").lower()}
            if matching_ids:
                # 保留匹配节点及其直接关联节点
                related_ids = set()
                for e in full_graph["edges"]:
                    if e["source_id"] in matching_ids:
                        related_ids.add(e["target_id"])
                    if e["target_id"] in matching_ids:
                        related_ids.add(e["source_id"])
                keep_ids = matching_ids | related_ids
                full_graph["nodes"] = [n for n in full_graph["nodes"] if n["id"] in keep_ids]
                full_graph["edges"] = [e for e in full_graph["edges"] if e["source_id"] in keep_ids and e["target_id"] in keep_ids]

        from streamlit_app.components.mindmap import render_kg_graph
        col_graph, col_detail = st.columns([3, 1])
        with col_graph:
            clicked_id = render_kg_graph(full_graph, on_click=True)
        with col_detail:
            # 节点详情侧边栏
            detail_id = clicked_id or st.session_state.get("selected_kg_node")
            if clicked_id:
                st.session_state["selected_kg_node"] = clicked_id
            if detail_id:
                node_info = next((n for n in full_graph["nodes"] if n["id"] == detail_id), None)
                if node_info:
                    type_icon = {"Course": "📘", "Chapter": "📖", "KnowledgePoint": "📌", "SubPoint": "📍", "Concept": "💡"}.get(node_info.get("type", ""), "📦")
                    st.markdown(f"### {type_icon} {node_info['name']}")
                    st.caption(f"类型: {node_info.get('type', '未知')}")
                    st.caption(f"ID: {node_info['id']}")
                    extra = node_info.get("extra", {})
                    if isinstance(extra, dict) and extra.get("description"):
                        st.markdown(f"**描述:** {extra['description']}")
                    # 关联关系
                    related_edges = [e for e in full_graph["edges"] if e["source_id"] == detail_id or e["target_id"] == detail_id]
                    if related_edges:
                        st.markdown("**关联关系:**")
                        for e in related_edges[:10]:
                            other_id = e["target_id"] if e["source_id"] == detail_id else e["source_id"]
                            other_node = next((n for n in full_graph["nodes"] if n["id"] == other_id), None)
                            other_name = other_node["name"] if other_node else other_id
                            direction = "→" if e["source_id"] == detail_id else "←"
                            st.caption(f"{direction} {other_name} ({e.get('relation', '')})")
                    if st.button("📖 生成学习资源", key="gen_from_kg"):
                        st.session_state["current_kp_id"] = detail_id
                        st.session_state["current_kp_name"] = node_info["name"]
                        st.switch_page("pages/2_generate.py")
            else:
                st.info("点击图中节点查看详情")

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
    pathways = fetch_pathways(user_id)

    if not pathways:
        st.info("暂无学习路径。您可以通过生成资源或与 AI 对话来创建学习路径。")
        if st.button("➕ 创建学习路径"):
            st.switch_page("pages/2_generate.py")
    else:
        # ---------- 路径选择器 + 进度 ----------
        path_labels = []
        for p in pathways:
            name = p.get("name", f"路径 {p.get('id', '')[:8]}")
            items = p.get("items", [])
            done = sum(1 for it in items if it.get("is_completed"))
            path_labels.append(f"{name}（{done}/{len(items)}）")

        col_sel, col_prog = st.columns([2, 3])
        with col_sel:
            sel_idx = st.selectbox("选择学习路径", range(len(pathways)), format_func=lambda i: path_labels[i])
        cur_path = pathways[sel_idx]
        cur_items = sorted(cur_path.get("items", []), key=lambda x: x.get("order_index", 0))
        done_count = sum(1 for it in cur_items if it.get("is_completed"))
        progress = done_count / len(cur_items) if cur_items else 0
        with col_prog:
            st.write("")  # 垂直对齐
            st.progress(progress, text=f"完成进度：{done_count}/{len(cur_items)}")

        # ---------- 分类节点 ----------
        completed_ids: set[str] = set()
        current_ids: set[str] = set()
        planned_ids: set[str] = set()
        planned_order: dict[str, int] = {}

        remaining = []
        for it in cur_items:
            kp_id = it.get("kp_id", "")
            if it.get("is_completed"):
                completed_ids.add(kp_id)
            else:
                remaining.append(kp_id)

        if remaining:
            current_ids.add(remaining[0])
            for idx, kp_id in enumerate(remaining[1:6], start=1):
                planned_ids.add(kp_id)
                planned_order[kp_id] = idx

        pathway_highlight = {
            "completed": completed_ids,
            "current": current_ids,
            "planned": planned_ids,
            "planned_order": planned_order,
        }

        # ---------- 获取知识图谱并渲染 ----------
        path_graph = fetch_kg_graph(depth=5)
        if path_graph and path_graph.get("nodes"):
            from streamlit_app.components.mindmap import render_kg_graph

            col_graph, col_detail = st.columns([3, 1])
            with col_graph:
                clicked_id = render_kg_graph(
                    path_graph, on_click=True, pathway_highlight=pathway_highlight,
                )
            with col_detail:
                detail_id = clicked_id or st.session_state.get("pathway_clicked_node")
                if clicked_id:
                    st.session_state["pathway_clicked_node"] = clicked_id
                if detail_id:
                    node_info = next((n for n in path_graph["nodes"] if n["id"] == detail_id), None)
                    if node_info:
                        # 判断节点在路径中的状态
                        if detail_id in completed_ids:
                            st.success("已完成")
                        elif detail_id in current_ids:
                            st.warning("正在学习")
                        elif detail_id in planned_ids:
                            st.info(f"待学习（第 {planned_order.get(detail_id, '?')} 步）")

                        type_icon = {"Course": "📘", "Chapter": "📖", "KnowledgePoint": "📌",
                                     "SubPoint": "📍", "Concept": "💡"}.get(node_info.get("type", ""), "📦")
                        st.markdown(f"### {type_icon} {node_info['name']}")
                        st.caption(f"类型: {node_info.get('type', '未知')}")
                        extra = node_info.get("extra", {})
                        if isinstance(extra, dict) and extra.get("description"):
                            st.markdown(f"**描述:** {extra['description']}")

                        # 操作按钮
                        all_path_ids = completed_ids | current_ids | planned_ids
                        cur_item = next((it for it in cur_items if it.get("kp_id") == detail_id), None)

                        if cur_item and detail_id not in completed_ids:
                            if st.button("✅ 标记完成", key="mark_done", type="primary"):
                                if mark_item_completed(cur_path["id"], cur_item["id"], user_id):
                                    st.success("已标记为完成！")
                                    st.rerun()
                                else:
                                    st.error("操作失败，请重试。")

                        if detail_id not in all_path_ids:
                            if st.button("➕ 添加到路径", key="add_to_path"):
                                if add_item_to_pathway(cur_path["id"], user_id, detail_id, len(cur_items)):
                                    st.success("已添加到学习路径！")
                                    st.rerun()
                                else:
                                    st.error("添加失败，请重试。")

                        if detail_id in all_path_ids and detail_id not in completed_ids:
                            if st.button("📖 开始学习", key="path_learn"):
                                st.session_state["current_kp_id"] = detail_id
                                st.session_state["current_kp_name"] = node_info["name"]
                                st.switch_page("pages/2_generate.py")
                        if detail_id not in all_path_ids:
                            if st.button("📖 生成学习资源", key="path_gen"):
                                st.session_state["current_kp_id"] = detail_id
                                st.session_state["current_kp_name"] = node_info["name"]
                                st.switch_page("pages/2_generate.py")
                else:
                    st.info("点击图中节点查看详情")
        else:
            st.info("暂无知识图谱数据，请先导入知识库。")

        # ---------- 底部步骤卡片 ----------
        st.markdown("---")
        st.subheader("📋 路径步骤")
        if cur_items:
            cols = st.columns(min(len(cur_items), 6))
            for i, item in enumerate(cur_items):
                kp_id = item.get("kp_id", "")
                kp_name = item.get("kp_name", kp_id[:8])
                order = item.get("order_index", i + 1)
                is_done = item.get("is_completed", False)
                is_cur = kp_id in current_ids
                is_plan = kp_id in planned_ids

                with cols[i % min(len(cur_items), 6)]:
                    if is_done:
                        color, icon = "#52c41a", "✅"
                    elif is_cur:
                        color, icon = "#fa8c16", "▶️"
                    elif is_plan:
                        color, icon = "#1890ff", "🔜"
                    else:
                        color, icon = "#999", "⭕"
                    st.markdown(
                        f"<div style='border-left:4px solid {color};padding:6px 10px;margin-bottom:8px;"
                        f"border-radius:4px;background:{'#f6ffed' if is_done else '#fff'}'>"
                        f"<b>{icon} {order}. {kp_name}</b></div>",
                        unsafe_allow_html=True,
                    )
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
