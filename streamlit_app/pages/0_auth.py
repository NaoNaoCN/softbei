"""
streamlit_app/pages/0_auth.py
认证页：用户注册和登录。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL

st.set_page_config(page_title="登录/注册", page_icon="🔐")
st.title("🔐 登录 / 注册")


def register(username: str, password: str) -> tuple[bool, str]:
    """注册用户。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/auth/register",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return True, "注册成功，请登录。"
        elif resp.status_code == 400:
            return False, "用户名已存在。"
        else:
            return False, f"注册失败：{resp.status_code}"
    except httpx.ConnectError:
        return False, "无法连接到后端服务，请确保后端已启动。"
    except Exception as e:
        return False, f"注册异常：{e}"


def login(username: str, password: str) -> tuple[bool, str]:
    """登录用户，返回 (成功标志, 用户ID或错误信息)。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/auth/login",
            json={"username": username, "password": password},
            timeout=10.0,
        )
        if resp.status_code == 200:
            data = resp.json()
            return True, data.get("user_id", "")
        elif resp.status_code == 401:
            return False, "用户名或密码错误。"
        else:
            return False, f"登录失败：{resp.status_code}"
    except httpx.ConnectError:
        return False, "无法连接到后端服务，请确保后端已启动。"
    except Exception as e:
        return False, f"登录异常：{e}"


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if st.session_state.get("user_id"):
    st.success(f"当前已登录：{st.session_state.get('username') or st.session_state['user_id'][:8]}")
    if st.button("退出登录"):
        for key in ["user_id", "access_token", "session_id", "profile"]:
            st.session_state[key] = None
        st.session_state["chat_messages"] = []
        st.rerun()
    st.stop()

tab_login, tab_register = st.tabs(["登录", "注册"])

with tab_login:
    with st.form("login_form", clear_on_submit=True):
        st.markdown("请输入用户名和密码登录系统。")
        login_username = st.text_input("用户名", placeholder="请输入用户名")
        login_password = st.text_input("密码", type="password", placeholder="请输入密码")
        submitted = st.form_submit_button("登录", type="primary")

        if submitted:
            if not login_username or not login_password:
                st.warning("请填写用户名和密码。")
            else:
                success, result = login(login_username, login_password)
                if success:
                    st.session_state["user_id"] = result
                    st.session_state["username"] = login_username
                    st.success("登录成功！")
                    st.rerun()
                else:
                    st.error(result)

with tab_register:
    with st.form("register_form", clear_on_submit=True):
        st.markdown("创建一个新账户。")
        reg_username = st.text_input("用户名", placeholder="请输入用户名")
        reg_password = st.text_input("密码", type="password", placeholder="请输入密码（至少6位）")
        reg_password_confirm = st.text_input("确认密码", type="password", placeholder="请再次输入密码")

        col_info, col_btn = st.columns([3, 1])
        with col_info:
            st.caption("注册即表示您同意我们的服务条款。")
        with col_btn:
            submitted = st.form_submit_button("注册", type="primary")

        if submitted:
            if not reg_username or not reg_password:
                st.warning("请填写用户名和密码。")
            elif len(reg_password) < 6:
                st.warning("密码长度至少为6位。")
            elif reg_password != reg_password_confirm:
                st.warning("两次输入的密码不一致。")
            else:
                success, msg = register(reg_username, reg_password)
                if success:
                    st.success(msg)
                else:
                    st.error(msg)
