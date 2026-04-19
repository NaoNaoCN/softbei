"""
streamlit_app/pages/5_evaluate.py
学习评估页：完成测验、查看成绩历史、了解薄弱点。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.quiz_card import render_quiz_card

st.set_page_config(page_title="学习评估", page_icon="📝")
st.title("📝 学习评估")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_quiz_items(resource_id: str) -> list[dict]:
    """获取某资源的题目列表。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/resources/{resource_id}/quiz")
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def submit_answer(user_id: str, quiz_item_id: str, user_answer) -> dict | None:
    """提交答案，返回批改结果。"""
    try:
        resp = httpx.post(
            f"{API_BASE_URL}/quiz/submit",
            params={"user_id": user_id},
            json={"quiz_item_id": quiz_item_id, "user_answer": user_answer},
        )
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

resource_id = st.text_input("输入测验资源 ID（或从资源库进入）")

if resource_id:
    items = fetch_quiz_items(resource_id)
    if not items:
        st.warning("未找到题目，请确认资源 ID 正确。")
    else:
        st.markdown(f"共 **{len(items)}** 道题目")
        for i, item in enumerate(items, 1):
            st.markdown(f"#### 第 {i} 题")
            answer = render_quiz_card(item, show_answer=False, interactive=True)

            if st.button(f"提交第 {i} 题", key=f"submit_{item['id']}"):
                result = submit_answer(user_id, item["id"], answer)
                if result:
                    if result.get("is_correct"):
                        st.success(f"✅ 正确！得分：{result['score']}")
                    else:
                        st.error(f"❌ 错误。正确答案：{item.get('answer')}")
                        if item.get("explanation"):
                            st.info(f"解析：{item['explanation']}")
                else:
                    st.error("提交失败，请检查网络连接。")
