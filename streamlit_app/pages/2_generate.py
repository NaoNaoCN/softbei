"""
streamlit_app/pages/2_generate.py
资源生成页：支持对话式生成和直接生成两种模式。
"""

import time

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL, init_session_state
from streamlit_app.components.mindmap import render_mindmap
from streamlit_app.components.quiz_card import render_quiz_card
from streamlit_app.components.resource_card import render_resource_card

init_session_state()

st.set_page_config(page_title="生成资源", page_icon="✨", layout="wide")
st.title("✨ 生成学习资源")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_kg_nodes(root_id: str | None = None, depth: int = 2) -> list[dict]:
    """获取知识图谱节点列表供下拉选择。"""
    try:
        params: dict = {"depth": depth}
        if root_id:
            params["root_id"] = root_id
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params=params, timeout=10.0)
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
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("task_id")
    except Exception:
        pass
    return None


def poll_task_status(task_id: str) -> dict | None:
    """轮询任务状态。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/generate/{task_id}/status", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_resource(resource_id: str) -> dict | None:
    """获取已生成资源详情。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/resources/{resource_id}", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _create_pathway_from_recs(user_id: str, kp_name: str, recommendations: list[dict]) -> bool:
    """将 AI 推荐列表保存为一条新学习路径，返回是否成功。"""
    try:
        # 创建路径
        resp = httpx.post(
            f"{API_BASE_URL}/pathways",
            json={"name": f"AI 推荐 - {kp_name}"},
            params={"user_id": user_id},
            timeout=10.0,
        )
        if resp.status_code != 200:
            return False
        path_id = resp.json().get("id")
        if not path_id:
            return False

        # 逐条添加推荐节点
        for i, rec in enumerate(recommendations):
            kp_id = rec.get("kp_id")
            if not kp_id:
                continue
            try:
                httpx.post(
                    f"{API_BASE_URL}/pathways/{path_id}/items",
                    json={"kp_id": kp_id, "order_index": i},
                    params={"user_id": user_id},
                    timeout=10.0,
                )
            except Exception:
                pass  # 静默跳过不存在的 kp_id
        return True
    except Exception:
        return False


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

# 模式选择
tab_chat, tab_direct = st.tabs(["💬 对话式生成", "📋 直接生成"])

# ----------------------------------------------------------
# 对话式生成模式
# ----------------------------------------------------------
with tab_chat:
    st.markdown("""
    对话式资源生成已整合到「智能对话」页面。
    在对话中描述您的学习需求，AI 将自动生成相应资源。
    """)
    if st.button("💬 前往智能对话", type="primary", use_container_width=False):
        st.switch_page("pages/6_chat.py")

# ----------------------------------------------------------
# 直接生成模式
# ----------------------------------------------------------
with tab_direct:
    col_form, col_result = st.columns([1, 2])

    with col_form:
        st.subheader("生成配置")

        # 获取知识点
        nodes = fetch_kg_nodes(depth=5)
        kp_options = {n["name"]: n["id"] for n in nodes if n.get("type") in ("Chapter", "KnowledgePoint", "SubPoint", "Concept")}

        # 如果有预设的知识点，优先选中
        default_kp = st.session_state.get("current_kp_name", "")
        if default_kp and default_kp in kp_options:
            default_index = list(kp_options.keys()).index(default_kp)
        else:
            default_index = 0

        selected_kp_name = st.selectbox(
            "选择知识点",
            list(kp_options.keys()) if kp_options else ["暂无知识点，请先导入知识库"],
            index=default_index,
        )
        selected_kp_id = kp_options.get(selected_kp_name, "")

        # 清除预设
        if st.session_state.get("current_kp_id"):
            st.session_state["current_kp_id"] = None
            st.session_state["current_kp_name"] = None

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

        # 生成选项
        with st.expander("⚙️ 高级选项"):
            temperature = st.slider("创意度", 0.0, 1.0, 0.7)
            st.caption("较低的值会使生成结果更确定性，较高的值会更有创意。")

        generate_btn = st.button(
            "🚀 开始生成",
            type="primary",
            disabled=not selected_kp_id,
            use_container_width=True,
        )

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
                        st.error("无法获取任务状态，请检查后端服务。")
                        break

                    progress = task.get("progress", 0)
                    task_status = task.get("status")
                    progress_bar.progress(
                        progress / 100,
                        text=f"进度：{progress}% | 状态：{task_status}"
                    )

                    if task_status == "done":
                        progress_bar.progress(1.0, text="✅ 生成完成！")
                        result_id = task.get("result_id")

                        if result_id:
                            resource = fetch_resource(result_id)
                            if resource:
                                st.success(f"资源已生成：{resource.get('title', '无标题')}")

                                # 根据类型渲染
                                if resource_type == "mindmap":
                                    tree = resource.get("content_json") or {}
                                    render_mindmap(tree, height=500)
                                elif resource_type == "quiz":
                                    items = (resource.get("content_json") or {}).get("items", [])
                                    for i, item in enumerate(items, 1):
                                        st.markdown(f"### 第 {i} 题")
                                        render_quiz_card(item, show_answer=False)
                                    if len(items) > 3:
                                        st.info(f"共 {len(items)} 道题，可前往「学习评估」页面完整作答。")
                                else:
                                    render_resource_card(resource, expandable=False)

                                # 提供后续操作
                                st.markdown("---")
                                col_next1, col_next2 = st.columns(2)
                                with col_next1:
                                    if st.button("📚 查看资源库", use_container_width=True):
                                        st.switch_page("pages/4_library.py")
                                with col_next2:
                                    if resource_type == "quiz":
                                        if st.button("📝 开始测验", use_container_width=True):
                                            st.session_state["current_kp_id"] = selected_kp_id
                                            st.switch_page("pages/5_evaluate.py")
                        break

                    elif task_status == "failed":
                        st.error(f"❌ 生成失败：{task.get('error_msg', '未知错误')}")
                        break

                    time.sleep(1)
            else:
                st.error("无法启动生成任务，请检查后端服务是否正常。")

        elif not generate_btn:
            st.info("👈 请在左侧选择知识点和资源类型，然后点击「开始生成」")

# ----------------------------------------------------------
# 底部说明
# ----------------------------------------------------------
st.markdown("---")
st.caption("💡 提示：对话式生成会自动分析您的需求并选择合适的资源类型；直接生成让您更精确地控制生成内容。")
