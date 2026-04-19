"""
streamlit_app/pages/1_profile.py
学生画像页：展示当前画像，支持手动编辑和对话式更新。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL

st.set_page_config(page_title="我的画像", page_icon="🧠")
st.title("🧠 我的学习画像")


def fetch_profile(user_id: str) -> dict | None:
    """从后端获取当前画像。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/profile", params={"user_id": user_id})
        if resp.status_code == 200:
            return resp.json()
        return None
    except Exception:
        return None


def save_profile(user_id: str, data: dict) -> bool:
    """将编辑后的画像提交到后端。"""
    try:
        resp = httpx.put(
            f"{API_BASE_URL}/profile",
            params={"user_id": user_id},
            json=data,
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

# 加载画像
if st.button("刷新画像") or st.session_state.get("profile") is None:
    st.session_state["profile"] = fetch_profile(user_id)

profile = st.session_state.get("profile") or {}

tab_view, tab_edit = st.tabs(["查看画像", "编辑画像"])

with tab_view:
    if profile:
        col1, col2 = st.columns(2)
        with col1:
            st.metric("专业", profile.get("major", "未设置"))
            st.metric("每日学习时间", f"{profile.get('daily_time_minutes', 0)} 分钟")
            st.metric("认知风格", profile.get("cognitive_style", "未设置"))
        with col2:
            st.metric("版本", profile.get("version", 1))
        st.markdown("**学习目标**")
        st.info(profile.get("learning_goal") or "暂未设置学习目标")
        st.markdown("**已掌握知识点**")
        mastered = profile.get("knowledge_mastered", [])
        st.write(", ".join(mastered) if mastered else "暂无")
        st.markdown("**薄弱知识点**")
        weak = profile.get("knowledge_weak", [])
        st.write(", ".join(weak) if weak else "暂无")
    else:
        st.info("尚未建立画像，请在"编辑画像"标签页填写信息。")

with tab_edit:
    with st.form("profile_form"):
        major = st.text_input("专业", value=profile.get("major", ""))
        learning_goal = st.text_area("学习目标", value=profile.get("learning_goal", ""), height=80)
        cognitive_style = st.selectbox(
            "认知风格",
            ["visual", "text", "practice"],
            index=["visual", "text", "practice"].index(profile.get("cognitive_style", "text")),
        )
        daily_time = st.slider("每日学习时间（分钟）", 10, 480, profile.get("daily_time_minutes", 60))
        mastered_input = st.text_input(
            "已掌握知识点（逗号分隔）",
            value=", ".join(profile.get("knowledge_mastered", [])),
        )
        weak_input = st.text_input(
            "薄弱知识点（逗号分隔）",
            value=", ".join(profile.get("knowledge_weak", [])),
        )
        submitted = st.form_submit_button("保存画像")

    if submitted:
        payload = {
            "major": major or None,
            "learning_goal": learning_goal or None,
            "cognitive_style": cognitive_style,
            "daily_time_minutes": daily_time,
            "knowledge_mastered": [k.strip() for k in mastered_input.split(",") if k.strip()],
            "knowledge_weak": [k.strip() for k in weak_input.split(",") if k.strip()],
        }
        if save_profile(user_id, payload):
            st.success("画像已保存！")
            st.session_state["profile"] = None  # 强制刷新
            st.rerun()
        else:
            st.error("保存失败，请检查后端服务。")
