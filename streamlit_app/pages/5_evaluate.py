"""
streamlit_app/pages/5_evaluate.py
学习评估页：完成测验、查看成绩历史、了解薄弱点。
"""

import httpx
import streamlit as st

from streamlit_app.app import API_BASE_URL
from streamlit_app.components.quiz_card import render_quiz_card

st.set_page_config(page_title="学习评估", page_icon="📝", layout="wide")
st.title("📝 学习评估")


# ----------------------------------------------------------
# 辅助函数
# ----------------------------------------------------------

def fetch_resources(
    user_id: str,
    resource_type: str = "quiz",
    limit: int = 50,
) -> list[dict]:
    """获取用户的测验资源列表。"""
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/resources",
            params={"user_id": user_id, "resource_type": resource_type, "limit": limit},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def fetch_quiz_items(resource_id: str) -> list[dict]:
    """获取某资源的题目列表。"""
    try:
        resp = httpx.get(f"{API_BASE_URL}/resources/{resource_id}/quiz", timeout=10.0)
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


def submit_answer(user_id: str, quiz_item_id: str, user_answer) -> dict | None:
    """提交答案，返回批改结果。"""
    try:
        # 处理多选题答案格式
        if isinstance(user_answer, list):
            answer_data = {"quiz_item_id": quiz_item_id, "user_answer": ",".join(user_answer)}
        else:
            answer_data = {"quiz_item_id": quiz_item_id, "user_answer": str(user_answer) if user_answer else ""}

        resp = httpx.post(
            f"{API_BASE_URL}/quiz/submit",
            params={"user_id": user_id},
            json=answer_data,
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return None


def fetch_quiz_attempts(user_id: str, limit: int = 50) -> list[dict]:
    """获取用户的答题历史。"""
    try:
        resp = httpx.get(
            f"{API_BASE_URL}/quiz/attempts",
            params={"user_id": user_id, "limit": limit},
            timeout=10.0,
        )
        if resp.status_code == 200:
            return resp.json()
    except Exception:
        pass
    return []


# ----------------------------------------------------------
# 页面主体
# ----------------------------------------------------------

if not st.session_state.get("user_id"):
    st.warning("请先登录")
    st.stop()

user_id = st.session_state["user_id"]

tab_exam, tab_history, tab_weak = st.tabs(["进行测验", "答题历史", "薄弱分析"])

with tab_exam:
    st.subheader("选择测验资源")

    # 获取用户的测验资源
    quiz_resources = fetch_resources(user_id, resource_type="quiz")

    if not quiz_resources:
        st.info("暂无测验资源，请先在「生成资源」页面创建测验题目。")
        if st.button("去创建测验"):
            st.switch_page("pages/2_generate.py")
    else:
        # 资源选择
        resource_options = {res.get("title", res["id"][:8]): res["id"] for res in quiz_resources}
        resource_options["手动输入资源ID"] = "__manual__"

        selected_title = st.selectbox("选择测验", list(resource_options.keys()))

        if selected_title == "手动输入资源ID":
            resource_id = st.text_input("输入测验资源 ID")
        else:
            resource_id = resource_options[selected_title]

        # 加载测验
        if resource_id and resource_id != "__manual__":
            items = fetch_quiz_items(resource_id)

            if not items:
                st.warning("该资源暂无题目或加载失败。")
            else:
                st.success(f"成功加载 {len(items)} 道题目")
                st.markdown("---")

                # 初始化答题状态
                if "quiz_answers" not in st.session_state:
                    st.session_state["quiz_answers"] = {}
                if "quiz_submitted" not in st.session_state:
                    st.session_state["quiz_submitted"] = False

                # 答题区域
                for i, item in enumerate(items, 1):
                    st.markdown(f"### 第 {i} 题")
                    answer = render_quiz_card(
                        item,
                        show_answer=False,
                        interactive=not st.session_state["quiz_submitted"],
                        key_prefix=f"quiz_{resource_id[:8]}",
                    )
                    st.session_state["quiz_answers"][item["id"]] = answer

                st.markdown("---")

                col_submit, col_reset = st.columns(2)
                with col_submit:
                    if st.button("📤 提交全部答案", type="primary", disabled=st.session_state["quiz_submitted"]):
                        all_correct = 0
                        for item_id, user_answer in st.session_state["quiz_answers"].items():
                            result = submit_answer(user_id, item_id, user_answer)
                            if result and result.get("is_correct"):
                                all_correct += 1

                        total = len(st.session_state["quiz_answers"])
                        score = int(all_correct / total * 100) if total > 0 else 0

                        st.session_state["quiz_submitted"] = True
                        st.success(f"答题完成！得分：{score}/100（{all_correct}/{total} 正确）")

                        # 显示答案解析
                        st.markdown("---")
                        st.subheader("答案解析")
                        for i, item in enumerate(items, 1):
                            st.markdown(f"### 第 {i} 题")
                            render_quiz_card(item, show_answer=True)

                with col_reset:
                    if st.button("🔄 重置答题"):
                        st.session_state["quiz_answers"] = {}
                        st.session_state["quiz_submitted"] = False
                        st.rerun()

with tab_history:
    st.subheader("答题历史")
    attempts = fetch_quiz_attempts(user_id)

    if not attempts:
        st.info("暂无答题记录。完成测验后将自动记录您的答题历史。")
    else:
        # 统计
        total_attempts = len(attempts)
        correct_count = sum(1 for a in attempts if a.get("is_correct"))
        accuracy = correct_count / total_attempts * 100 if total_attempts > 0 else 0

        col_stat1, col_stat2, col_stat3 = st.columns(3)
        with col_stat1:
            st.metric("总答题数", total_attempts)
        with col_stat2:
            st.metric("正确数", correct_count)
        with col_stat3:
            st.metric("正确率", f"{accuracy:.1f}%")

        st.markdown("---")

        # 历史记录表格
        st.subheader("详细记录")
        for attempt in reversed(attempts[-20:]):  # 显示最近20条
            is_correct = attempt.get("is_correct", False)
            icon = "✅" if is_correct else "❌"
            quiz_item_id = attempt.get("quiz_item_id", "")[:8]
            user_answer = attempt.get("user_answer", "")
            correct_answer = attempt.get("correct_answer", "")
            created_at = attempt.get("created_at", "")[:16] if attempt.get("created_at") else "未知"

            with st.container(border=True):
                col_h1, col_h2, col_h3 = st.columns([1, 3, 2])
                with col_h1:
                    st.write(f"{icon} {'正确' if is_correct else '错误'}")
                with col_h2:
                    st.write(f"题目ID: ...{quiz_item_id}")
                    if not is_correct:
                        st.caption(f"你的答案: {user_answer} | 正确答案: {correct_answer}")
                with col_h3:
                    st.caption(f"🕐 {created_at}")

with tab_weak:
    st.subheader("薄弱知识点分析")

    # 基于答题历史分析薄弱点
    attempts = fetch_quiz_attempts(user_id)

    if not attempts:
        st.info("暂无足够的答题数据进行分析。请先完成一些测验。")
    else:
        # 统计每道题目的正确率
        item_stats = {}
        for attempt in attempts:
            item_id = attempt.get("quiz_item_id")
            if item_id:
                if item_id not in item_stats:
                    item_stats[item_id] = {"total": 0, "correct": 0, "wrong_answer": ""}
                item_stats[item_id]["total"] += 1
                if attempt.get("is_correct"):
                    item_stats[item_id]["correct"] += 1
                else:
                    item_stats[item_id]["wrong_answer"] = attempt.get("user_answer", "")

        # 找出正确率低的题目
        weak_items = []
        for item_id, stats in item_stats.items():
            if stats["total"] >= 1:
                accuracy = stats["correct"] / stats["total"]
                if accuracy < 0.6:  # 正确率低于60%视为薄弱
                    weak_items.append((item_id, accuracy, stats["wrong_answer"]))

        if not weak_items:
            st.success("🎉 太棒了！您的答题正确率普遍较高，没有明显的薄弱知识点。")
        else:
            st.warning(f"发现 {len(weak_items)} 个薄弱知识点，建议加强学习：")

            for item_id, accuracy, wrong_answer in sorted(weak_items, key=lambda x: x[1]):
                col_w1, col_w2 = st.columns([3, 1])
                with col_w1:
                    with st.expander(f"❌ 题目 ...{item_id[:8]}（正确率：{accuracy*100:.0f}%）"):
                        st.write(f"错误答案: {wrong_answer}")
                        if st.button(f"📖 去学习", key=f"weak_learn_{item_id}"):
                            st.switch_page("pages/2_generate.py")
                with col_w2:
                    st.progress(accuracy, text=f"{accuracy*100:.0f}%")

            st.markdown("---")
            st.info("💡 建议：点击「去学习」按钮，系统将为您生成针对性的学习资源。")
