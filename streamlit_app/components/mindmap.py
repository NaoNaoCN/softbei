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


def render_kg_graph(graph_data: dict[str, Any], height: int = 700, on_click: bool = False) -> str | None:
    """
    渲染知识图谱（ECharts graph 力导向布局）。

    :param graph_data: 包含 nodes / edges 列表的字典（KGGraphOut 序列化）
    :param height:     图表高度（像素）
    :param on_click:   是否启用点击事件回调
    :return:           点击的节点 ID（如果 on_click=True），否则 None
    """
    if not graph_data:
        st.info("暂无知识图谱数据。")
        return None

    if not _ECHARTS_AVAILABLE:
        st.warning("streamlit-echarts 未安装，以 JSON 形式展示。")
        st.json(graph_data)
        return None

    # 节点类型颜色映射
    color_map = {
        "Course": "#5470c6",
        "Chapter": "#91cc75",
        "KnowledgePoint": "#fac858",
        "SubPoint": "#ee6666",
        "Concept": "#73c0de",
    }

    # 计算每个节点的关联边数量（用于动态大小）
    edge_count: dict[str, int] = {}
    for e in graph_data.get("edges", []):
        edge_count[e["source_id"]] = edge_count.get(e["source_id"], 0) + 1
        edge_count[e["target_id"]] = edge_count.get(e["target_id"], 0) + 1

    base_sizes = {"Course": 40, "Chapter": 30, "KnowledgePoint": 20, "SubPoint": 14, "Concept": 12}

    nodes = []
    for n in graph_data.get("nodes", []):
        base = base_sizes.get(n["type"], 12)
        ec = edge_count.get(n["id"], 0)
        size = base + min(ec * 3, 20)  # 关联越多越大，上限 +20
        desc = n.get("extra", {}).get("description", "") if isinstance(n.get("extra"), dict) else ""
        nodes.append({
            "id": n["id"],
            "name": n["name"],
            "symbolSize": size,
            "itemStyle": {"color": color_map.get(n["type"], "#999")},
            "category": n["type"],
            "tooltip": {"formatter": f"<b>{n['name']}</b><br/>类型: {n['type']}<br/>{desc}"},
        })

    links = [
        {
            "source": e["source_id"],
            "target": e["target_id"],
            "label": {"show": False},
            "lineStyle": {"type": {"REQUIRES": "dashed", "RELATED_TO": "dotted"}.get(e.get("relation", ""), "solid")},
        }
        for e in graph_data.get("edges", [])
    ]

    categories = [{"name": k, "itemStyle": {"color": v}} for k, v in color_map.items()]

    option = {
        "tooltip": {"trigger": "item"},
        "legend": [{"data": list(color_map.keys())}],
        "series": [
            {
                "type": "graph",
                "layout": "force",
                "data": nodes,
                "links": links,
                "categories": categories,
                "roam": True,
                "label": {"show": True, "position": "right", "fontSize": 11},
                "force": {"repulsion": 200, "edgeLength": 80, "gravity": 0.1},
                "emphasis": {"focus": "adjacency", "lineStyle": {"width": 3}},
                "lineStyle": {"color": "source", "curveness": 0.3},
            }
        ],
    }

    events = {"click": "function(params){return params.data ? params.data.id : null;}"} if on_click else {}
    result = st_echarts(options=option, height=f"{height}px", events=events)
    return result if on_click else None
