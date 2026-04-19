"""
streamlit_app/components/resource_card.py
学习资源卡片组件：统一展示不同类型资源的预览。
"""

from __future__ import annotations

from typing import Any

import streamlit as st


_TYPE_ICON = {
    "doc": "📄",
    "mindmap": "🗺️",
    "quiz": "📝",
    "code": "💻",
    "summary": "📋",
}

_TYPE_LABEL = {
    "doc": "学习文档",
    "mindmap": "思维导图",
    "quiz": "测验题目",
    "code": "代码示例",
    "summary": "知识总结",
}


def render_resource_card(resource: dict[str, Any], expandable: bool = True) -> None:
    """
    渲染单个资源卡片。

    :param resource:   资源元数据字典（ResourceMetaOut 序列化）
    :param expandable: 是否使用 expander 折叠内容（True=可展开，False=直接展示）
    """
    r_type = resource.get("resource_type", "doc")
    icon = _TYPE_ICON.get(r_type, "📦")
    label = _TYPE_LABEL.get(r_type, r_type)
    title = resource.get("title", "无标题")
    created_at = resource.get("created_at", "")

    header = f"{icon} **{title}** — {label}"
    if created_at:
        header += f"  \n<small>生成时间：{created_at[:10]}</small>"

    if expandable:
        with st.expander(f"{icon} {title}", expanded=False):
            _render_content(resource)
    else:
        st.markdown(header, unsafe_allow_html=True)
        _render_content(resource)


def _render_content(resource: dict[str, Any]) -> None:
    """根据资源类型渲染内容区域。"""
    r_type = resource.get("resource_type", "doc")
    content_json = resource.get("content_json")
    content_path = resource.get("content_path")

    if r_type in ("doc", "summary"):
        # Markdown 文档
        text = (content_json or {}).get("markdown") or ""
        if text:
            st.markdown(text)
        elif content_path:
            st.caption(f"文件路径：{content_path}")
        else:
            st.info("内容为空")

    elif r_type == "code":
        code = (content_json or {}).get("code") or ""
        lang = (content_json or {}).get("language", "python")
        if code:
            st.code(code, language=lang)
        else:
            st.info("暂无代码内容")

    elif r_type == "mindmap":
        from streamlit_app.components.mindmap import render_mindmap
        tree = (content_json or {}).get("tree") or content_json or {}
        render_mindmap(tree, height=400)

    elif r_type == "quiz":
        from streamlit_app.components.quiz_card import render_quiz_card
        items = (content_json or {}).get("items", [])
        if items:
            for item in items[:3]:   # 预览前 3 道
                render_quiz_card(item, show_answer=False)
            if len(items) > 3:
                st.caption(f"（共 {len(items)} 道题，前往"学习评估"页面完整作答）")
        else:
            st.info("暂无题目")

    else:
        st.json(content_json or {})
