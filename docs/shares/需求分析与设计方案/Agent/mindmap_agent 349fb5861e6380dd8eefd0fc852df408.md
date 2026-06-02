# mindmap_agent

# MindmapAgent - 思维导图生成智能体

## 概述

MindmapAgent 负责生成思维导图数据（ECharts tree 格式 JSON）。它是一位思维导图设计专家，能够根据知识点和参考资料，生成适合可视化渲染的层级结构数据。

## 核心职责

1. **检索相关文档** - 获取知识点的参考资料
2. **生成树状结构** - 调用 LLM 生成 ECharts tree 格式的 JSON
3. **输出 JSON** - 将 JSON 字符串存入 `state.draft_content`
4.  **JSON 合法性验证** - 验证输出是否为合法 JSON，非法时尝试提取 JSON 片段
5. **异常兜底** - 生成失败时写入失败提示，不中断状态机

## System Prompt

```
你是一位思维导图设计专家。
请根据知识点和参考资料，生成一份适合 ECharts tree 图表的 JSON 数据。
格式要求（严格 JSON，不含任何 Markdown 标记）：
{
  "name": "知识点名称",
  "children": [
    {"name": "子概念1", "children": [...]},
    ...
  ]
}

参考资料：{context}
知识点：{kp_name}
层级深度：不超过 4 层，每节点子项不超过 6 个。
```

## 输入与输出

### 输入（AgentState）

| 字段 | 说明 |
| --- | --- |
| `kp_id` | 目标知识点 ID |
| `user_id` | 用户ID（用于 RAG 检索过滤） |
| `retrieved_docs` | 检索到的参考文档 |

### 输出（AgentState 更新）

| 字段 | 说明 |
| --- | --- |
| `draft_content` | ECharts tree 格式的 JSON 字符串 |
| `retrieved_docs` | 更新为本次检索到的文档文本列表 |

## 输出格式示例

```json
{
  "name": "机器学习概述",
  "children": [
    {
      "name": "监督学习",
      "children": [
        {"name": "分类", "children": []},
        {"name": "回归", "children": []}
      ]
    },
    {
      "name": "无监督学习",
      "children": [
        {"name": "聚类", "children": []},
        {"name": "降维", "children": []}
      ]
    }
  ]
}
```

## 约束条件

- **最大深度**：4 层
- **每节点最大子项**：6 个
- **格式**：严格 JSON，不含 Markdown 标记
- **JSON 验证**：生成后验证合法性，非法时尝试用正则提取 `{...}` 片段

## 依赖关系

- **上游**：PlannerAgent（确定 kp_id 和 resource_type）
- **下游**：SafetyAgent（内容安全审核）

## 执行流程

1. 通过 `resolve_kp_name` 从 `kp_id` 获取知识点名称 `kp_name`，并记录日志
2. 检索 context（优先检索包含代码的文档块，`n_results=5`） 
3. RAG 检索到文档时记录日志（条数），未检索到时记录 warning，检索异常时记录 warning 并降级
4. 构造 `context = format_context(chunks, max_tokens=3000)`
5. 填充 SYSTEM_PROMPT 中的 `{context}`、`{kp_name}`
6. 调用 `chat_completion` 生成 JSON （`temperature=0.5`, `max_tokens=2000`）
7. 验证 JSON 合法性：尝试 `json.loads(raw)`
8. 若非法，用正则 `r"\{[\s\S]*\}"` 提取 JSON 片段，再次验证
9. 将结果写入 `state.draft_content`
10. 异常时写入 `"思维导图生成失败：{e}"`，不抛异常中断 graph

## 文件位置

`backend/agents/mindmap_agent.py`