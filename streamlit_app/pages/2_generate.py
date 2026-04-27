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
        resp = httpx.get(f"{API_BASE_URL}/kg/graph", params={"root_id": root_id, "depth": depth}, timeout=10.0)
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


def chat_generate(user_id: str, session_id: str, message: str, stream: bool = False) -> dict | None:
    """对话式生成资源（调用 /chat 接口）。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/chat/{session_id}",
            params={"user_id": user_id, "stream": stream},
            json={"content": message},
            timeout=60.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def create_chat_session(user_id: str) -> str | None:
    """创建新的对话会话。"""
    try:
        resp = httpx.post(f"{API_BASE_URL}/chat/sessions", params={"user_id": user_id}, timeout=10.0)
        if resp.status_code == 200:
            return resp.json().get("session_id")
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

# 初始化会话
if not st.session_state.get("session_id"):
    session_id = create_chat_session(user_id)
    if session_id:
        st.session_state["session_id"] = session_id

# 模式选择
tab_chat, tab_direct = st.tabs(["💬 对话式生成", "📋 直接生成"])

# ----------------------------------------------------------
# 对话式生成模式
# ----------------------------------------------------------
with tab_chat:
    st.markdown("""
    通过自然语言与 AI 对话，描述您想生成的学习资源。
    例如：「帮我生成一份关于梯度下降的思维导图」
    """)

    # 聊天历史
    if "chat_messages" not in st.session_state:
        st.session_state["chat_messages"] = []

    chat_container = st.container(border=True)
    with chat_container:
        for msg in st.session_state["chat_messages"]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "user":
                st.markdown(f"**👤 您**：{content}")
            else:
                st.markdown(f"**🤖 AI**：{content}")
            st.markdown("---")

    # 输入框
    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_area(
            "输入您的学习需求...",
            placeholder="例如：帮我生成一份关于机器学习概述的学习文档",
            height=80,
        )
        col_send, col_clear = st.columns([1, 4])
        with col_send:
            submitted = st.form_submit_button("🚀 发送", type="primary")
        with col_clear:
            if st.form_submit_button("🗑️ 清空"):
                st.session_state["chat_messages"] = []
                st.rerun()

    if submitted and user_input:
        # 添加用户消息
        st.session_state["chat_messages"].append({"role": "user", "content": user_input})

        # 调用 chat 接口
        session_id = st.session_state.get("session_id") or create_chat_session(user_id)
        if session_id:
            st.session_state["session_id"] = session_id

            with st.spinner("AI 正在分析您的需求..."):
                result = chat_generate(user_id, session_id, user_input)

            if result:
                content = result.get("content", "抱歉，生成过程中出现问题。")
                metadata = result.get("metadata", {})
                recommendations = metadata.get("recommendations", [])

                # 添加 AI 响应
                st.session_state["chat_messages"].append({"role": "assistant", "content": content})

                # 显示推荐
                if recommendations:
                    st.success("📌 AI 为您推荐的下一步学习内容：")
                    for rec in recommendations[:3]:
                        kp_name = rec.get("kp_name", rec.get("kp_id", "未知"))
                        reason = rec.get("reason", "")
                        col_r1, col_r2 = st.columns([3, 1])
                        with col_r1:
                            st.write(f"- **{kp_name}**：{reason}")
                        with col_r2:
                            if st.button(f"生成", key=f"rec_{kp_name}"):
                                st.session_state["current_kp_id"] = rec.get("kp_id")
                                st.switch_page("pages/2_generate.py")
            else:
                st.session_state["chat_messages"].append({
                    "role": "assistant",
                    "content": "抱歉，无法连接到后端服务，请确保后端已启动。"
                })

        st.rerun()

# ----------------------------------------------------------
# 直接生成模式
# ----------------------------------------------------------
with tab_direct:
    col_form, col_result = st.columns([1, 2])

    with col_form:
        st.subheader("生成配置")

        # 获取知识点
        nodes = fetch_kg_nodes()
        kp_options = {n["name"]: n["id"] for n in nodes if n.get("type") in ("KnowledgePoint", "SubPoint", "Concept")}

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
