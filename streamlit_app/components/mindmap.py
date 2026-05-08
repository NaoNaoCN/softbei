"""
streamlit_app/components/mindmap.py
思维导图组件：使用 st.html + ECharts 原生 JS 渲染。
"""

from __future__ import annotations

from typing import Any

import streamlit as st

# ECharts CDN
_ECHARTS_CDN = "https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"


def render_mindmap(tree_data: dict[str, Any], height: int = 600) -> None:
    """渲染思维导图（ECharts tree）。"""
    if not tree_data:
        st.info("暂无思维导图数据。")
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

    _render_echarts(option, height=height)


def _render_echarts(option: dict[str, Any], height: int = 700) -> None:
    """通过 st.html 渲染 ECharts 图表。"""
    import json

    option_json = json.dumps(option, ensure_ascii=False)
    height_px = f"{height}px"

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <script src="{_ECHARTS_CDN}"></script>
    </head>
    <body style="margin:0;padding:0;">
        <div id="chart" style="width:100%;height:{height_px};"></div>
        <script>
            var chart = echarts.init(document.getElementById('chart'));
            var option = {option_json};
            chart.setOption(option);
            window.addEventListener('resize', function() {{ chart.resize(); }});
        </script>
    </body>
    </html>
    """
    st.html(html, unsafe_allow_javascript=True)


def _echarts_click_key() -> str:
    """返回当前页面唯一的 click key（防止多图冲突）。"""
    # 用 st.session_state 生成一个每页唯一的 key
    if "echarts_click_count" not in st.session_state:
        st.session_state["echarts_click_count"] = 0
    return f"echarts_click_{st.session_state['echarts_click_count']}"


def render_kg_graph(
    graph_data: dict[str, Any],
    height: int = 700,
    on_click: bool = False,
    pathway_highlight: dict[str, set[str]] | None = None,
    learned_ids: set[str] | None = None,
) -> str | None:
    """
    渲染知识图谱（ECharts graph 力导向布局）。

    :param graph_data:        包含 nodes / edges 列表的字典
    :param height:            图表高度（像素）
    :param on_click:           是否启用点击事件回调
    :param pathway_highlight:  学习路径高亮配置
    :param learned_ids:        已学习节点 ID 集合
    :return:                   点击的节点 ID（如果 on_click=True），否则 None
    """
    if not graph_data:
        st.info("暂无知识图谱数据。")
        return None

    color_map = {
        "Course": "#5470c6",
        "Chapter": "#91cc75",
        "KnowledgePoint": "#fac858",
        "SubPoint": "#ee6666",
        "Concept": "#73c0de",
    }
    hl_colors = {
        "completed": "#52c41a",
        "current": "#fa8c16",
        "planned": "#1890ff",
    }

    has_hl = pathway_highlight is not None
    completed_ids = pathway_highlight.get("completed", set()) if has_hl else set()
    current_ids = pathway_highlight.get("current", set()) if has_hl else set()
    planned_ids = pathway_highlight.get("planned", set()) if has_hl else set()
    planned_order: dict[str, int] = {}
    if has_hl and pathway_highlight.get("planned_order"):
        planned_order = pathway_highlight["planned_order"]

    edge_count: dict[str, int] = {}
    for e in graph_data.get("edges", []):
        edge_count[e["source_id"]] = edge_count.get(e["source_id"], 0) + 1
        edge_count[e["target_id"]] = edge_count.get(e["target_id"], 0) + 1

    base_sizes = {"Course": 40, "Chapter": 30, "KnowledgePoint": 20, "SubPoint": 14, "Concept": 12}

    nodes = []
    for n in graph_data.get("nodes", []):
        nid = n["id"]
        base = base_sizes.get(n["type"], 12)
        ec = edge_count.get(nid, 0)
        size = base + min(ec * 3, 20)
        desc = n.get("extra", {}).get("description", "") if isinstance(n.get("extra"), dict) else ""

        node_cfg: dict[str, Any] = {
            "id": nid,
            "name": n["name"],
            "symbolSize": size,
            "itemStyle": {"color": color_map.get(n["type"], "#999")},
            "category": n["type"],
            "tooltip": {"formatter": f"<b>{n['name']}</b><br/>类型: {n['type']}<br/>{desc}"},
        }

        if has_hl:
            if nid in completed_ids:
                node_cfg["itemStyle"] = {
                    "color": hl_colors["completed"],
                    "shadowBlur": 12,
                    "shadowColor": hl_colors["completed"],
                    "borderColor": "#fff",
                    "borderWidth": 2,
                }
                node_cfg["symbolSize"] = size + 6
                node_cfg["label"] = {"show": True, "color": "#333", "fontWeight": "bold"}
            elif nid in current_ids:
                node_cfg["itemStyle"] = {
                    "color": hl_colors["current"],
                    "shadowBlur": 18,
                    "shadowColor": hl_colors["current"],
                    "borderColor": "#fff",
                    "borderWidth": 3,
                }
                node_cfg["symbolSize"] = size + 10
                node_cfg["symbol"] = "diamond"
                node_cfg["label"] = {"show": True, "color": "#fa8c16", "fontWeight": "bold", "fontSize": 13}
            elif nid in planned_ids:
                order_label = planned_order.get(nid, "")
                suffix = f" [{order_label}]" if order_label else ""
                node_cfg["itemStyle"] = {
                    "color": hl_colors["planned"],
                    "shadowBlur": 8,
                    "shadowColor": hl_colors["planned"],
                    "borderColor": "#fff",
                    "borderWidth": 1,
                }
                node_cfg["symbolSize"] = size + 4
                node_cfg["label"] = {"show": True, "color": "#1890ff", "fontWeight": "bold",
                                     "formatter": f"{n['name']}{suffix}"}
            else:
                node_cfg["itemStyle"] = {"color": color_map.get(n["type"], "#999"), "opacity": 0.12}
                node_cfg["symbolSize"] = max(size - 4, 6)
                node_cfg["label"] = {"show": False}
        elif learned_ids is not None:
            if nid in learned_ids:
                node_cfg["itemStyle"] = {
                    "color": color_map.get(n["type"], "#999"),
                    "shadowBlur": 10,
                    "shadowColor": "#52c41a",
                    "borderColor": "#52c41a",
                    "borderWidth": 2,
                }
                node_cfg["label"] = {"show": True}
            else:
                node_cfg["itemStyle"] = {"color": "#ccc", "opacity": 0.25}
                node_cfg["symbolSize"] = max(size - 4, 6)
                node_cfg["label"] = {"show": False}

        nodes.append(node_cfg)

    links = []
    for e in graph_data.get("edges", []):
        sid, tid = e["source_id"], e["target_id"]
        link_cfg: dict[str, Any] = {
            "source": sid,
            "target": tid,
            "label": {"show": False},
            "lineStyle": {"type": {"REQUIRES": "dashed", "RELATED_TO": "dotted"}.get(e.get("relation", ""), "solid")},
        }
        if has_hl:
            both_in = sid in (completed_ids | current_ids | planned_ids) and tid in (completed_ids | current_ids | planned_ids)
            if both_in:
                link_cfg["lineStyle"]["width"] = 3
                link_cfg["lineStyle"]["opacity"] = 0.9
                if sid in completed_ids and tid in completed_ids:
                    link_cfg["lineStyle"]["color"] = hl_colors["completed"]
                elif sid in current_ids or tid in current_ids:
                    link_cfg["lineStyle"]["color"] = hl_colors["current"]
                else:
                    link_cfg["lineStyle"]["color"] = hl_colors["planned"]
            else:
                link_cfg["lineStyle"]["opacity"] = 0.06
                link_cfg["lineStyle"]["width"] = 0.5
        elif learned_ids is not None:
            both_learned = sid in learned_ids and tid in learned_ids
            if both_learned:
                link_cfg["lineStyle"]["opacity"] = 0.8
                link_cfg["lineStyle"]["color"] = "#52c41a"
            else:
                link_cfg["lineStyle"]["opacity"] = 0.08
                link_cfg["lineStyle"]["width"] = 0.5
        links.append(link_cfg)

    categories = [{"name": k, "itemStyle": {"color": v}} for k, v in color_map.items()]

    option: dict[str, Any] = {
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

    if has_hl:
        option["legend"] = [{"data": list(color_map.keys()), "top": 30}]
        option["graphic"] = [
            {"type": "group", "left": 20, "top": 10, "children": [
                {"type": "circle", "shape": {"r": 6}, "style": {"fill": hl_colors["completed"]}, "left": 0, "top": 2},
                {"type": "text", "style": {"text": "已完成", "fontSize": 12, "fill": "#333"}, "left": 18, "top": 0},
                {"type": "circle", "shape": {"r": 6}, "style": {"fill": hl_colors["current"]}, "left": 75, "top": 2},
                {"type": "text", "style": {"text": "进行中", "fontSize": 12, "fill": "#333"}, "left": 93, "top": 0},
                {"type": "circle", "shape": {"r": 6}, "style": {"fill": hl_colors["planned"]}, "left": 150, "top": 2},
                {"type": "text", "style": {"text": "待学习", "fontSize": 12, "fill": "#333"}, "left": 168, "top": 0},
            ]}
        ]
    elif learned_ids is not None:
        option["graphic"] = [
            {"type": "group", "left": 20, "top": 10, "children": [
                {"type": "circle", "shape": {"r": 6}, "style": {"fill": "#52c41a"}, "left": 0, "top": 2},
                {"type": "text", "style": {"text": "已学习", "fontSize": 12, "fill": "#333"}, "left": 18, "top": 0},
                {"type": "circle", "shape": {"r": 6}, "style": {"fill": "#ccc"}, "left": 75, "top": 2},
                {"type": "text", "style": {"text": "未学习", "fontSize": 12, "fill": "#999"}, "left": 93, "top": 0},
            ]}
        ]

    # 生成唯一 key 供点击回调使用
    click_key = _echarts_click_key()
    st.session_state["echarts_click_count"] += 1

    if on_click:
        # 读取上一轮点击结果（通过 query_params 回传）
        params = st.query_params
        clicked = params.get(click_key, None)
        # 清除 query_params 避免刷新后残留
        try:
            del params[click_key]
        except Exception:
            pass
        import json
        option_json = json.dumps(option, ensure_ascii=False)
        height_px = f"{height}px"

        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="utf-8">
        <script src="{_ECHARTS_CDN}"></script>
        </head>
        <body style="margin:0;padding:0;">
        <div id="chart" style="width:100%;height:{height_px};"></div>
        <script>
        var chart = echarts.init(document.getElementById('chart'));
        var option = {option_json};
        chart.setOption(option);
        window.addEventListener('resize', function() {{ chart.resize(); }});
        chart.on('click', function(params) {{
            if (!params.data || !params.data.id) return;
            var key = '{click_key}';
            var url = new URL(window.location.href);
            url.searchParams.set(key, params.data.id);
            window.location.href = url.toString();
        }});
        </script>
        </body>
        </html>
        """
        st.html(html, unsafe_allow_javascript=True)
        return clicked if clicked else None
    else:
        _render_echarts(option, height=height)
        return None
