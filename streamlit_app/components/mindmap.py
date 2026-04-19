"""
streamlit_app/components/mindmap.py
思维导图组件：使用 streamlit-echarts 渲染 ECharts tree 图。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

try:
    from streamlit_echarts import st_echarts
    _ECHARTS_AVAILABLE = True
except ImportError:
    _ECHARTS_AVAILABLE = False


def render_mindmap(tree_data: dict[str, Any], height: int = 600) -> None:
    """
    渲染思维导图（ECharts tree）。

    :param tree_data: ECharts tree 格式字典，包含 name / children 字段
    :param height:    图表高度（像素）
    """
    if not tree_data:
        st.info("暂无思维导图数据。")
        return

    if not _ECHARTS_AVAILABLE:
        st.warning("streamlit-echarts 未安装，以 JSON 形式展示。")
        st.json(tree_data)
        return

    option = {
        "tooltip": {"trigger": "item", "triggerOn": "mousemove"},
        "series": [
            {
                "type": "tree",
                "data": [tree_data],
                "top": "5%",
                "left": "10%",
                "bottom": "5%",
                "right": "10%",
                "symbolSize": 10,
                "label": {
                    "position": "left",
                    "verticalAlign": "middle",
                    "align": "right",
                    "fontSize": 13,
                },
                "leaves": {
                    "label": {
                        "position": "right",
                        "verticalAlign": "middle",
                        "align": "left",
                    }
                },
                "emphasis": {"focus": "descendant"},
                "expandAndCollapse": True,
                "animationDuration": 300,
                "animationDurationUpdate": 450,
            }
        ],
    }
    st_echarts(options=option, height=f"{height}px")


def render_kg_graph(graph_data: dict[str, Any], height: int = 700) -> None:
    """
    渲染知识图谱（ECharts graph 力导向布局）。

    :param graph_data: 包含 nodes / edges 列表的字典（KGGraphOut 序列化）
    :param height:     图表高度（像素）
    """
    if not graph_data:
        st.info("暂无知识图谱数据。")
        return

    if not _ECHARTS_AVAILABLE:
        st.warning("streamlit-echarts 未安装，以 JSON 形式展示。")
        st.json(graph_data)
        return

    # 节点类型颜色映射
    color_map = {
        "Course": "#5470c6",
        "Chapter": "#91cc75",
        "KnowledgePoint": "#fac858",
        "SubPoint": "#ee6666",
        "Concept": "#73c0de",
    }

    nodes = [
        {
            "id": n["id"],
            "name": n["name"],
            "symbolSize": {"Course": 40, "Chapter": 30, "KnowledgePoint": 20}.get(n["type"], 12),
            "itemStyle": {"color": color_map.get(n["type"], "#999")},
            "category": n["type"],
        }
        for n in graph_data.get("nodes", [])
    ]
    links = [
        {"source": e["source_id"], "target": e["target_id"], "label": {"show": False}}
        for e in graph_data.get("edges", [])
    ]

    option = {
        "tooltip": {},
        "legend": [{"data": list(color_map.keys())}],
        "series": [
            {
                "type": "graph",
                "layout": "force",
                "data": nodes,
                "links": links,
                "roam": True,
                "label": {"show": True, "position": "right", "fontSize": 11},
                "force": {"repulsion": 200, "edgeLength": 80},
                "emphasis": {"focus": "adjacency"},
                "lineStyle": {"color": "source", "curveness": 0.3},
            }
        ],
    }
    st_echarts(options=option, height=f"{height}px")
