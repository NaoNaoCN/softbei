"""
streamlit_app/app.py
Streamlit 多页应用入口。定义全局配置、侧边栏导航和会话状态初始化。
"""

import httpx
import streamlit as st

# ----------------------------------------------------------
# 页面配置（必须是第一个 st 调用）
# ----------------------------------------------------------
st.set_page_config(
    page_title="个性化学习助手",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------
# 全局 API 配置
# ----------------------------------------------------------
API_BASE_URL: str = "http://localhost:8000"

# ----------------------------------------------------------
# 会话状态初始化
# ----------------------------------------------------------

def init_session_state() -> None:
    """初始化所有全局会话变量（仅首次运行时设置默认值）。"""
    defaults = {
        "user_id": None,          # 当前登录用户 UUID 字符串
        "access_token": None,     # JWT Token
        "session_id": None,       # 当前对话会话 ID
        "profile": None,          # 缓存的学生画像 dict
        "chat_history": [],       # [{"role": "user"/"assistant", "content": "..."}]
        "current_kp_id": None,    # 当前选中的知识点 ID
        "is_onboarding": False,   # 是否处于画像初始化引导阶段
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _fetch_profile(user_id: str) -> dict | None:
    try:
        resp = httpx.get(f"{API_BASE_URL}/profile", params={"user_id": user_id}, timeout=5)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def _profile_is_empty(profile: dict | None) -> bool:
    if not profile:
        return True
    return not any([
        profile.get("learning_goal"),
        profile.get("knowledge_mastered"),
        profile.get("knowledge_weak"),
    ])


init_session_state()

# ----------------------------------------------------------
# 侧边栏
# ----------------------------------------------------------

with st.sidebar:
    st.title("🎓 个性化学习助手")
    st.markdown("---")

    if st.session_state.user_id:
        st.success(f"已登录：{st.session_state.user_id[:8]}...")

        # 检测画像是否为空，引导用户进入 onboarding 对话
        if st.session_state.profile is None:
            st.session_state.profile = _fetch_profile(st.session_state.user_id)

        if _profile_is_empty(st.session_state.profile):
            st.session_state.is_onboarding = True
            st.info("👋 先来聊聊你的学习情况吧")
            if st.button("开始建立画像 →"):
                # 预置引导消息，跳转到主页对话区
                if not st.session_state.chat_history:
                    st.session_state.chat_history = [{
                        "role": "assistant",
                        "content": (
                            "你好！我是你的学习助手。请简单介绍一下你的专业、"
                            "学习目标，以及目前对哪些知识点比较熟悉？"
                        ),
                    }]
                st.switch_page("app.py")
        else:
            st.session_state.is_onboarding = False

        if st.button("退出登录"):
            for key in ["user_id", "access_token", "session_id", "profile",
                        "chat_history", "is_onboarding"]:
                st.session_state[key] = None if key != "chat_history" else []
            st.rerun()
    else:
        st.warning("请先登录")

    st.markdown("---")
    st.caption("v0.1.0 | A3 软件杯项目")

# ----------------------------------------------------------
# 主页内容
# ----------------------------------------------------------

# ----------------------------------------------------------
# 主页内容
# ----------------------------------------------------------

st.title("欢迎使用个性化学习助手")

if not st.session_state.user_id:
    st.markdown(
        """
        本系统基于多智能体技术，为您提供：
        - 🧠 **智能学习资源生成**（文档 / 思维导图 / 代码 / 测验 / 总结）
        - 📊 **个性化画像分析**，精准匹配学习内容
        - 🗺️ **知识图谱可视化**，掌握知识全貌
        - 📚 **学习路径规划**，高效达成学习目标

        请通过左侧导航栏选择功能页面。
        """
    )
    st.info("请先在侧边栏登录以使用完整功能。")
else:
    # 渲染对话历史（onboarding 引导消息或普通对话）
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    user_input = st.chat_input("输入消息…")
    if user_input:
        st.session_state.chat_history.append({"role": "user", "content": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)
        # 实际调用由各功能页面处理；主页仅作 onboarding 入口展示
        st.info("请前往对话页面继续交互，或使用左侧导航栏选择功能。")
