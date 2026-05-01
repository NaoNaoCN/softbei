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

            # 推荐处理：存入 session_state，下次渲染时显示
            recommendations = result.get("metadata", {}).get("recommendations", [])
            if recommendations:
                st.session_state["last_recommendations"] = recommendations
                st.session_state["last_kp_name"] = result.get("metadata", {}).get("kp_name", "学习路径")
            else:
                st.session_state.pop("last_recommendations", None)
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
