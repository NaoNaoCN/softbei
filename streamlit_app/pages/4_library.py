"""
streamlit_app/pages/4_library.py
资源库页：浏览、搜索、筛选已生成的学习资源，支持预览和删除。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.resource_card import render_resource_card
from streamlit_app.components.mindmap import render_mindmap
from streamlit_app.components.quiz_card import render_quiz_card

st.set_page_config(page_title="资源库", page_icon="📚", layout="wide")
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
        resp = httpx.get(f"{API_BASE_URL}/resources", params=params, timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except httpx.ConnectError:
        st.warning("无法连接到后端服务。")
    except Exception as e:
        st.error(f"获取资源失败：{e}")
    return []


def fetch_resource(resource_id: str) -> dict | None:
    """获取单个资源详情。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/resources/{resource_id}", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def delete_resource(resource_id: str) -> bool:
    """删除资源。"""
    try:
        resp = httpx.delete(f"{API_BASE_URL}/resources/{resource_id}", timeout=10.0)
        return resp.status_code == 200
    except Exception:
        return False


def get_resource_stats(user_id: str) -> dict:
    """获取资源统计信息。"""
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/resources/stats",
            params={"user_id": user_id},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return {}


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

# 初始化状态
if "lib_view_mode" not in st.session_state:
    st.session_state["lib_view_mode"] = "grid"  # grid or list
if "lib_preview_id" not in st.session_state:
    st.session_state["lib_preview_id"] = None

# 筛选区
st.subheader("筛选条件")
col_filter1, col_filter2, col_filter3, col_view = st.columns([2, 2, 2, 1])

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

with col_filter3:
    kp_filter = st.text_input("知识点ID（可选）", placeholder="输入知识点ID筛选")

refresh = st.button("🔄 刷新")

# 分页状态
if "lib_skip" not in st.session_state:
    st.session_state["lib_skip"] = 0

# 获取资源列表
resources = fetch_resources(
    user_id,
    resource_type=type_filter if type_filter != "全部" else None,
    kp_id=kp_filter if kp_filter else None,
    skip=st.session_state["lib_skip"],
)

# 统计信息
stats = get_resource_stats(user_id)
col_stat1, col_stat2, col_stat3, col_stat4, col_stat5 = st.columns(5)
with col_stat1:
    st.metric("📄 文档", stats.get("doc", 0))
with col_stat2:
    st.metric("🗺️ 思维导图", stats.get("mindmap", 0))
with col_stat3:
    st.metric("📝 测验", stats.get("quiz", 0))
with col_stat4:
    st.metric("💻 代码", stats.get("code", 0))
with col_stat5:
    st.metric("📋 总结", stats.get("summary", 0))

st.markdown("---")

# 预览区域
if st.session_state["lib_preview_id"]:
    preview_resource = fetch_resource(st.session_state["lib_preview_id"])
    if preview_resource:
        st.subheader(f"📖 预览：{preview_resource.get('title', '无标题')}")

        r_type = preview_resource.get("resource_type", "doc")

        if r_type == "mindmap":
            tree = preview_resource.get("content_json") or {}
            render_mindmap(tree, height=500)
        elif r_type == "quiz":
            items = (preview_resource.get("content_json") or {}).get("items", [])
            for i, item in enumerate(items, 1):
                st.markdown(f"### 第 {i} 题")
                render_quiz_card(item, show_answer=False, interactive=False)
        else:
            render_resource_card(preview_resource, expandable=False)

        if st.button("🔽 关闭预览"):
            st.session_state["lib_preview_id"] = None
            st.rerun()

        st.markdown("---")

# 资源列表
if not resources:
    st.info("暂无资源。请前往「生成资源」页面创建学习材料。")
    if st.button("➕ 去创建资源"):
        st.switch_page("pages/2_generate.py")
else:
    st.subheader(f"资源列表（共 {len(resources)} 项）")

    # 列表/网格视图切换
    col_list, col_grid, col_space = st.columns([1, 1, 4])
    with col_list:
        if st.button("📋 列表视图", disabled=st.session_state["lib_view_mode"] == "list"):
            st.session_state["lib_view_mode"] = "list"
            st.rerun()
    with col_grid:
        if st.button("🔲 网格视图", disabled=st.session_state["lib_view_mode"] == "grid"):
            st.session_state["lib_view_mode"] = "grid"
            st.rerun()

    st.markdown("---")

    if st.session_state["lib_view_mode"] == "list":
        # 列表视图
        for res in resources:
            r_type = res.get("resource_type", "doc")
            icon = {"doc": "📄", "mindmap": "🗺️", "quiz": "📝", "code": "💻", "summary": "📋"}.get(r_type, "📦")
            title = res.get("title", "无标题")[:50]
            created_at = res.get("created_at", "")[:10] if res.get("created_at") else "未知"
            res_id = res.get("id", "")

            with st.container(border=True):
                col_l1, col_l2, col_l3, col_l4, col_l5 = st.columns([4, 2, 1, 1, 1])
                with col_l1:
                    st.write(f"{icon} **{title}**")
                with col_l2:
                    st.caption(f"🕐 {created_at}")
                with col_l3:
                    if st.button("👁️ 预览", key=f"view_{res_id}"):
                        st.session_state["lib_preview_id"] = res_id
                        st.rerun()
                with col_l4:
                    if st.button("📝 测验", key=f"quiz_{res_id}", disabled=r_type != "quiz"):
                        st.session_state["current_kp_id"] = res.get("kp_id")
                        st.switch_page("pages/5_evaluate.py")
                with col_l5:
                    if st.button("🗑️", key=f"del_{res_id}"):
                        if delete_resource(res_id):
                            st.success("已删除")
                            st.rerun()
                        else:
                            st.error("删除失败")
    else:
        # 网格视图（2列）
        cols = st.columns(2)
        for i, res in enumerate(resources):
            with cols[i % 2]:
                r_type = res.get("resource_type", "doc")
                icon = {"doc": "📄", "mindmap": "🗺️", "quiz": "📝", "code": "💻", "summary": "📋"}.get(r_type, "📦")
                title = res.get("title", "无标题")

                with st.container(border=True):
                    st.markdown(f"### {icon} {title}")

                    col_g1, col_g2, col_g3 = st.columns(3)
                    with col_g1:
                        if st.button("👁️ 预览", key=f"view_g_{res['id']}", use_container_width=True):
                            st.session_state["lib_preview_id"] = res["id"]
                            st.rerun()
                    with col_g2:
                        if r_type == "quiz":
                            if st.button("📝 测验", key=f"quiz_g_{res['id']}", use_container_width=True):
                                st.session_state["current_kp_id"] = res.get("kp_id")
                                st.switch_page("pages/5_evaluate.py")
                        else:
                            st.button("📝 测验", disabled=True, use_container_width=True)
                    with col_g3:
                        if st.button("🗑️ 删除", key=f"del_g_{res['id']}", use_container_width=True):
                            if delete_resource(res["id"]):
                                st.success("已删除")
                                st.rerun()
                            else:
                                st.error("删除失败")

# 分页按钮
st.markdown("---")
col_prev, col_page, col_next = st.columns([2, 1, 2])
with col_prev:
    if st.session_state["lib_skip"] > 0:
        if st.button("← 上一页"):
            st.session_state["lib_skip"] = max(0, st.session_state["lib_skip"] - 20)
            st.rerun()
with col_page:
    st.write(f"第 {st.session_state['lib_skip'] // 20 + 1} 页")
with col_next:
    if len(resources) == 20:
        if st.button("下一页 →"):
            st.session_state["lib_skip"] += 20
            st.rerun()
