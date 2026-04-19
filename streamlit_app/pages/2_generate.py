"""
streamlit_app/pages/2_generate.py
资源生成页：选择知识点和资源类型，触发生成并实时展示结果。
"""

import time

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.mindmap import render_mindmap
from streamlit_app.components.quiz_card import render_quiz_card
from streamlit_app.components.resource_card import render_resource_card

st.set_page_config(page_title="生成资源", page_icon="✨", layout="wide")
st.title("✨ 生成学习资源")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_kg_nodes(root_id: str | None = None) -> list[dict]:
    """获取知识图谱节点列表供下拉选择。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params={"root_id": root_id, "depth": 2})
        if resp.status_code == 200:
            return resp.json().get("nodes", [])
    except Exception:
        pass
    return []


def start_generation(user_id: str, kp_id: str, resource_type: str) -> str | None:
    """触发生成任务，返回 task_id。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/generate",
            params={"user_id": user_id},
            json={"kp_id": kp_id, "resource_type": resource_type},
        )
        if resp.status_code == 200:
            return resp.json().get("task_id")
    except Exception:
        pass
    return None


def poll_task_status(task_id: str) -> dict | None:
    """轮询任务状态。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/generate/{task_id}/status")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_resource(resource_id: str) -> dict | None:
    """获取已生成资源详情。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/resources/{resource_id}")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

col_form, col_result = st.columns([1, 2])

with col_form:
    st.subheader("生成配置")

    nodes = fetch_kg_nodes()
    kp_options = {n["name"]: n["id"] for n in nodes if n.get("type") in ("KnowledgePoint", "SubPoint")}
    selected_kp_name = st.selectbox("选择知识点", list(kp_options.keys()) or ["暂无知识点"])
    selected_kp_id = kp_options.get(selected_kp_name, "")

    resource_type = st.radio(
        "资源类型",
        options=["doc", "mindmap", "quiz", "code", "summary"],
        format_func=lambda x: {
            "doc": "📄 学习文档",
            "mindmap": "🗺️ 思维导图",
            "quiz": "📝 测验题目",
            "code": "💻 代码示例",
            "summary": "📋 知识总结",
        }[x],
    )

    generate_btn = st.button("🚀 开始生成", type="primary", disabled=not selected_kp_id)

with col_result:
    st.subheader("生成结果")

    if generate_btn and selected_kp_id:
        task_id = start_generation(user_id, selected_kp_id, resource_type)
        if task_id:
            # 轮询进度
            progress_bar = st.progress(0, text="正在生成中...")
            status_placeholder = st.empty()
            while True:
                task = poll_task_status(task_id)
                if not task:
                    st.error("无法获取任务状态")
                    break
                progress = task.get("progress", 0)
                task_status = task.get("status")
                progress_bar.progress(progress / 100, text=f"进度：{progress}%")
                if task_status == "done":
                    progress_bar.progress(1.0, text="生成完成！")
                    result_id = task.get("result_id")
                    if result_id:
                        resource = fetch_resource(result_id)
                        if resource:
                            if resource_type == "mindmap":
                                render_mindmap(resource.get("content_json") or {})
                            elif resource_type == "quiz":
                                for item in (resource.get("content_json") or {}).get("items", []):
                                    render_quiz_card(item)
                            else:
                                render_resource_card(resource)
                    break
                elif task_status == "failed":
                    st.error(f"生成失败：{task.get('error_msg', '未知错误')}")
                    break
                time.sleep(1)
        else:
            st.error("无法启动生成任务，请检查后端服务。")
