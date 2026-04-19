"""
streamlit_app/app.py
Streamlit 多页应用入口。定义全局配置、侧边栏导航和会话状态初始化。
"""

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
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


init_session_state()

# ----------------------------------------------------------
# 侧边栏
# ----------------------------------------------------------

with st.sidebar:
    st.title("🎓 个性化学习助手")
    st.markdown("---")

    if st.session_state.user_id:
        st.success(f"已登录：{st.session_state.user_id[:8]}...")
        if st.button("退出登录"):
            for key in ["user_id", "access_token", "session_id", "profile", "chat_history"]:
                st.session_state[key] = None
            st.rerun()
    else:
        st.warning("请先登录")

    st.markdown("---")
    st.caption("v0.1.0 | A3 软件杯项目")

# ----------------------------------------------------------
# 主页内容
# ----------------------------------------------------------

st.title("欢迎使用个性化学习助手")
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

if not st.session_state.user_id:
    st.info("请先在侧边栏登录以使用完整功能。")
