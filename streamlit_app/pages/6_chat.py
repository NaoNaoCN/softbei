"""
streamlit_app/pages/6_chat.py
智能对话页：支持画像引导式对话和自由聊天。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL, init_session_state

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


# ----------------------------------------------------------
# Session 初始化
# ----------------------------------------------------------
if not st.session_state.session_id:
    sid = create_chat_session()
    if sid:
        st.session_state.session_id = sid
    else:
        st.error("无法创建对话会话，请检查后端服务。")
        st.stop()

# ----------------------------------------------------------
# Onboarding 指示器
# ----------------------------------------------------------
if st.session_state.is_onboarding:
    st.info("🎯 正在了解你的学习情况，请回答几个问题帮助我为你定制学习方案。")

# ----------------------------------------------------------
# 聊天历史渲染
# ----------------------------------------------------------
for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# ----------------------------------------------------------
# 输入处理
# ----------------------------------------------------------
if prompt := st.chat_input("输入消息..."):
    # 显示用户消息
    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 调用后端
    with st.chat_message("assistant"):
        with st.spinner("思考中..."):
            result = send_message(st.session_state.session_id, prompt)

        if result and result.get("content"):
            reply = result["content"]
            st.markdown(reply)
            st.session_state.chat_history.append({"role": "assistant", "content": reply})

            # 画像完成检测
            if result.get("profile_complete") and st.session_state.is_onboarding:
                st.session_state.is_onboarding = False
                st.session_state.profile = fetch_profile()
                st.toast("🎉 画像建立完成！现在可以开始生成个性化学习资源了。", icon="✅")
        else:
            st.error("未收到有效回复，请稍后重试。")
