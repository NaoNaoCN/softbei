"""
streamlit_app/components/quiz_card.py
测验题目卡片组件：支持单选/多选/填空/问答四种题型的展示与交互。
"""

from __future__ import annotations

from typing import Any

import streamlit as st


def render_quiz_card(
    item: dict[str, Any],
    show_answer: bool = False,
    interactive: bool = False,
    key_prefix: str = "",
) -> Any:
    """
    渲染单道题目卡片。

    :param item:        题目数据字典（QuizItemOut 序列化）
    :param show_answer: 是否展示参考答案和解析
    :param interactive: 是否展示可交互输入控件（做题模式）
    :param key_prefix:  Streamlit widget key 前缀，避免 key 冲突
    :return:            用户输入的答案（interactive=True 时有效），否则 None
    """
    q_type = item.get("question_type", "single")
    difficulty = item.get("difficulty", 3)
    stem = item.get("stem", "")
    options = item.get("options") or []
    answer = item.get("answer")
    explanation = item.get("explanation", "")

    # 题型标签
    type_label = {
        "single": "🔵 单选",
        "multi": "🟣 多选",
        "fill": "🟡 填空",
        "short": "🟢 简答",
    }.get(q_type, q_type)

    difficulty_stars = "⭐" * difficulty

    with st.container(border=True):
        st.markdown(f"**{type_label}** | 难度：{difficulty_stars}")
        st.markdown(f"**{stem}**")

        user_answer = None

        if interactive:
            item_key = f"{key_prefix}_{item.get('id', stem[:10])}"
            if q_type == "single" and options:
                user_answer = st.radio("选择答案", options, key=f"radio_{item_key}")
            elif q_type == "multi" and options:
                user_answer = st.multiselect("选择所有正确答案", options, key=f"multi_{item_key}")
            elif q_type in ("fill", "short"):
                user_answer = st.text_area("输入答案", key=f"text_{item_key}", height=80)
        elif options:
            # 只展示选项，不可交互
            for opt in options:
                st.markdown(f"- {opt}")

        if show_answer:
            st.markdown("---")
            st.markdown(f"**参考答案：** `{answer}`")
            if explanation:
                st.info(f"💡 解析：{explanation}")

    return user_answer
