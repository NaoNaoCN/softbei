"""
streamlit_app/pages/6_chat.py
智能对话页：支持画像引导式对话、自由聊天和对话式资源生成。
包含会话列表侧边栏、历史恢复、mindmap/quiz 富内容渲染。
"""

import json as _json

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL, init_session_state
from streamlit_app.components.mindmap import render_mindmap
from streamlit_app.components.quiz_card import render_quiz_card

init_session_state()

st.set_page_config(page_title="智能对话", page_icon="💬", layout="wide")
st.title("💬 智能对话")

# ----------------------------------------------------------
# 登录检查
# ----------------------------------------------------------
if not st.session_state.user_id:
    st.warning("请先登录后使用对话功能。")
    if st.button("🔐 登录 / 注册"):
        st.switch_page("pages/0_auth.py")
    st.stop()

user_id: str = st.session_state.user_id


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def create_chat_session() -> str | None:
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/chat/sessions",
            params={"user_id": user_id},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json().get("id")
        else:
            st.error(f"创建会话失败: {resp.status_code} - {resp.text}")
    except Exception as e:
        st.error(f"请求异常: {e}")
    return None


def send_message(session_id: str, message: str) -> dict | None:
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/chat/{session_id}",
            params={"user_id": user_id, "stream": False},
            json={"content": message},
            timeout=120.0,
        )
        if resp.status_code == 200:
            return resp.json()
        else:
            st.error(f"后端返回错误: {resp.status_code} - {resp.text[:200]}")
    except Exception as e:
        st.error(f"请求异常: {e}")
    return None


def fetch_profile() -> dict | None:
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/profile",
            params={"user_id": user_id},
            timeout=5.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_sessions(user_id: str) -> list[dict]:
    """获取用户的会话列表，按 last_used_at 降序排列。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/chat/sessions", params={"user_id": user_id}, timeout=10.0)
        if resp.status_code == 200:
            sessions = resp.json()
            return sorted(sessions, key=lambda s: s.get("last_used_at") or "", reverse=True)
    except Exception:
        pass
    return []


def load_session_messages(session_id: str) -> list[dict]:
    """从后端加载指定会话的历史消息。"""
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/chat/{session_id}/messages",
            params={"user_id": user_id},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json() or []
    except Exception:
        pass
    return []


def delete_session(session_id: str, user_id: str) -> bool:
    """删除指定会话。"""
    try:
        resp = httpx.delete(
            f"{API_BASE_URL}/chat/sessions/{session_id}",
            params={"user_id": user_id},
            timeout=10.0,
        )
        return resp.status_code == 200
    except Exception:
        return False


def update_session_title(session_id: str, title: str) -> None:
    """更新会话标题。"""
    try:
        httpx.patch(
            f"{API_BASE_URL}/chat/sessions/{session_id}/title",
            json={"title": title, "user_id": user_id},
            timeout=10.0,
        )
    except Exception:
        pass


# ----------------------------------------------------------
# Session 初始化
# ----------------------------------------------------------
if not st.session_state.session_id:
    # 优先恢复最近的历史会话，避免每次进页面都新建一个空会话
    _existing = fetch_sessions(user_id)
    if _existing:
        st.session_state.session_id = _existing[0]["id"]
    else:
        sid = create_chat_session()
        if sid:
            st.session_state.session_id = sid
        else:
            st.error("无法创建对话会话，请检查后端服务。")
            st.stop()

# 刷新页面后从后端恢复历史消息
if st.session_state.session_id and not st.session_state.get("chat_messages"):
    _loaded = load_session_messages(st.session_state.session_id)
    if _loaded:
        st.session_state["chat_messages"] = _loaded

# 确保 chat_messages 已初始化（防止 None 或缺失）
if not isinstance(st.session_state.get("chat_messages"), list):
    st.session_state["chat_messages"] = []

# ----------------------------------------------------------
# Onboarding 指示器
# ----------------------------------------------------------
if st.session_state.is_onboarding:
    st.info("🎯 正在了解你的学习情况，请回答几个问题帮助我为你定制学习方案。")

# ----------------------------------------------------------
# 主布局：左栏会话列表 + 右栏对话区
# ----------------------------------------------------------
col_sidebar, col_chat = st.columns([1, 3])

# ------ 左栏：会话列表 ------
with col_sidebar:
    if st.button("➕ 新建会话", use_container_width=True):
        new_sid = create_chat_session()
        if new_sid:
            st.session_state.session_id = new_sid
            st.session_state["chat_messages"] = []
            st.session_state.pop("last_recommendations", None)
            st.rerun()

    st.markdown("**历史会话**")
    sessions = fetch_sessions(user_id)
    for s in sessions:
        sid = s["id"]
        title = s.get("title") or "新对话"
        is_current = sid == st.session_state.get("session_id")
        label = f"● {title}" if is_current else title
        col_s1, col_s2 = st.columns([4, 1])
        with col_s1:
            if st.button(label, key=f"sess_{sid}", use_container_width=True):
                st.session_state.session_id = sid
                st.session_state["chat_messages"] = load_session_messages(sid)
                st.session_state.pop("last_recommendations", None)
                st.rerun()
        with col_s2:
            if st.button("🗑️", key=f"del_sess_{sid}"):
                delete_session(sid, user_id)
                if is_current:
                    new_sid = create_chat_session()
                    st.session_state.session_id = new_sid
                    st.session_state["chat_messages"] = []
                    st.session_state.pop("last_recommendations", None)
                st.rerun()

# ------ 右栏：对话区 ------
with col_chat:
    # 聊天历史渲染
    for msg in st.session_state["chat_messages"]:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        resource_type = msg.get("resource_type")
        with st.chat_message(role):
            if role == "assistant" and resource_type == "mindmap":
                try:
                    tree = _json.loads(content) if isinstance(content, str) else content
                    render_mindmap(tree, height=450)
                except Exception:
                    st.markdown(content)
            elif role == "assistant" and resource_type == "quiz":
                try:
                    data = _json.loads(content) if isinstance(content, str) else content
                    items = data.get("items", []) if isinstance(data, dict) else []
                    for i, item in enumerate(items, 1):
                        st.markdown(f"**第 {i} 题**")
                        render_quiz_card(item, show_answer=False, interactive=False)
                except Exception:
                    st.markdown(content)
            else:
                st.markdown(content)

    # 输入框
    if prompt := st.chat_input("输入消息..."):
        # 显示用户消息
        st.session_state["chat_messages"].append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 调用后端
        with st.chat_message("assistant"):
            with st.spinner("思考中..."):
                result = send_message(st.session_state.session_id, prompt)

            if result and result.get("content"):
                reply = result["content"]
                resource_type = result.get("resource_type")

                # 渲染 assistant 回复
                if resource_type == "mindmap":
                    try:
                        tree = _json.loads(reply) if isinstance(reply, str) else reply
                        render_mindmap(tree, height=450)
                    except Exception:
                        st.markdown(reply)
                elif resource_type == "quiz":
                    try:
                        data = _json.loads(reply) if isinstance(reply, str) else reply
                        items = data.get("items", []) if isinstance(data, dict) else []
                        for i, item in enumerate(items, 1):
                            st.markdown(f"**第 {i} 题**")
                            render_quiz_card(item, show_answer=False, interactive=False)
                    except Exception:
                        st.markdown(reply)
                else:
                    st.markdown(reply)

                st.session_state["chat_messages"].append({
                    "role": "assistant",
                    "content": reply,
                    "resource_type": resource_type,
                })

                # 画像完成检测
                if result.get("profile_complete") and st.session_state.is_onboarding:
                    st.session_state.is_onboarding = False
                    st.session_state.profile = fetch_profile()
                    st.toast("🎉 画像建立完成！现在可以开始生成个性化学习资源了。", icon="✅")

                # 推荐处理
                recommendations = result.get("metadata", {}).get("recommendations", [])
                if recommendations:
                    st.session_state["last_recommendations"] = recommendations
                    st.session_state["last_kp_name"] = result.get("metadata", {}).get("kp_name", "学习路径")
                else:
                    st.session_state.pop("last_recommendations", None)

                # 第一条完整对话后自动命名会话
                if len(st.session_state["chat_messages"]) == 2:
                    update_session_title(st.session_state.session_id, prompt[:20])
            else:
                st.error("未收到有效回复，请稍后重试。")

# ----------------------------------------------------------
# 推荐区（每次渲染检查 session_state）
# ----------------------------------------------------------
if st.session_state.get("last_recommendations"):
    recommendations = st.session_state["last_recommendations"]
    st.success("📌 AI 为您推荐的下一步学习内容：")
    for rec in recommendations[:3]:
        rec_kp_name = rec.get("kp_name", rec.get("kp_id", "未知"))
        reason = rec.get("reason", "")
        col_r1, col_r2 = st.columns([3, 1])
        with col_r1:
            st.write(f"- **{rec_kp_name}**：{reason}")
        with col_r2:
            if st.button(f"生成", key=f"rec_{rec_kp_name}"):
                st.session_state["current_kp_id"] = rec.get("kp_id")
                st.session_state["current_kp_name"] = rec_kp_name
                st.switch_page("pages/2_generate.py")

    save_key = f"save_pathway_{len(recommendations)}"
    if st.button("📌 保存为学习路径", key=save_key, type="secondary"):
        _kp_name = st.session_state.get("last_kp_name", "学习路径")
        try:
            resp = httpx.post(
                f"{API_BASE_URL}/pathways",
                json={"name": f"AI 推荐 - {_kp_name}"},
                params={"user_id": user_id},
                timeout=10.0,
            )
            if resp.status_code == 200:
                path_id = resp.json().get("id")
                for i, rec in enumerate(recommendations):
                    kp_id = rec.get("kp_id")
                    if kp_id:
                        try:
                            httpx.post(
                                f"{API_BASE_URL}/pathways/{path_id}/items",
                                json={"kp_id": kp_id, "order_index": i},
                                params={"user_id": user_id},
                                timeout=10.0,
                            )
                        except Exception:
                            pass
                st.success("✅ 学习路径已创建！")
                st.session_state.pop("last_recommendations", None)
                if st.button("前往学习路径页 →", key="goto_pathway"):
                    st.switch_page("pages/3_pathway.py")
            else:
                st.error("创建学习路径失败，请检查后端服务。")
        except Exception as e:
            st.error(f"请求异常: {e}")
