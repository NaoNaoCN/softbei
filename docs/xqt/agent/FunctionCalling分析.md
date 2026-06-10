# Function Calling / 工具调用分析文档

## 概述

本项目（softbei — 个性化资源生成与学习多智能体系统）**当前未使用任何 LLM function calling 或工具调用机制**。所有结构化输出均通过在 system prompt 中指示 LLM 返回 JSON 格式文本来实现（即"JSON-in-Prompt"模式），而非使用 OpenAI 兼容的 `tools`/`function_call` 参数或 LangChain 的 `@tool` 装饰器。

---

## 1. 当前架构：JSON-in-Prompt 模式

### 1.1 核心调用链路

```
Agent（async def run）
  → 构造 system prompt（包含 JSON 格式说明）
  → backend.services.llm.chat_completion(messages=[system, user])
  → LLM 返回纯文本 JSON
  → 手动 json.loads() 解析
  → 更新 AgentState 字段
```

### 1.2 LLM 服务层（`backend/services/llm.py`）

`chat_completion()` 函数（第 84–123 行）**不支持 tools 参数**：

```python
async def chat_completion(
    messages: list[dict],
    model: str = None,
    temperature: float = None,
    max_tokens: int = None,
    provider: str = None,
) -> str:
```

- 仅发送 `model`、`temperature`、`max_tokens` 参数到 OpenAI 兼容 API
- 无 `tools`、`functions`、`tool_choice`、`function_call` 参数
- `stream_chat_completion()` 仅提取 `delta.content`，不处理 `delta.tool_calls`

### 1.3 各 Agent 的结构化输出方式

| Agent | 文件 | 输出内容 | 解析方式 |
|-------|------|----------|----------|
| `profile_agent` | `agents/profile_agent.py` | 用户画像字段提取 | `json.loads()` 解析 JSON 对象 |
| `planner_agent` | `agents/planner_agent.py` | 意图分类 + 资源类型选择 | `json.loads()` 解析 JSON 对象 |
| `safety_agent` | `agents/safety_agent.py` | 安全审查结果 `{passed, issues}` | `json.loads()` 解析 JSON 对象 |
| `recommend_agent` | `agents/recommend_agent.py` | 推荐知识点列表 | `json.loads()` 解析 JSON 数组 |
| `mindmap_agent` | `agents/mindmap_agent.py` | ECharts 树形结构 JSON | 直接使用（模板渲染） |
| `quiz_agent` | `agents/quiz_agent.py` | 测验题目 JSON 数组 | `json.loads()` 解析 JSON 数组 |
| `doc_agent` | `agents/doc_agent.py` | 自由文本 Markdown | 无需解析 |
| `code_agent` | `agents/code_agent.py` | 自由文本代码 | 无需解析 |
| `summary_agent` | `agents/summary_agent.py` | 自由文本摘要 | 无需解析 |
| `kg_agent` | `agents/kg_agent.py` | 委托 `kg_builder` 处理 | `kg_builder` 内部 `json.loads()` |

### 1.4 典型示例：planner_agent 的 JSON-in-Prompt

```python
# backend/agents/planner_agent.py 第 19 行
SYSTEM_PROMPT = """你是一个学习规划专家。根据学生信息和对话上下文，你需要：
1. 判断学生的意图类型
2. 选择合适的资源生成类型
...

请以 JSON 格式返回：
{
  "intent": "generate",
  "resource_type": "doc",
  "kp_id": "...",
  "extra_types": []
}
"""
```

LLM 调用后手动解析：
```python
response = await chat_completion(messages)
result = json.loads(response)
```

---

## 2. 不存在的能力（对比分析）

### 2.1 当前不支持的功能

| 能力 | 状态 | 说明 |
|------|------|------|
| 原生 tool calling | 不支持 | API 调用不传 `tools` 参数 |
| LangChain `@tool` 装饰器 | 无 | 未使用 `langchain.tools` |
| `ToolNode` / `tool_node` | 无 | LangGraph 图中无工具节点 |
| `bind_tools()` | 无 | 未使用 LangChain 的模型工具绑定 |
| `with_structured_output()` | 无 | 未使用结构化输出 API |
| 流式工具调用 | 不支持 | `stream_chat_completion()` 不处理 `tool_calls` delta |
| 工具执行回调 | 无 | 无工具执行/分发机制 |

### 2.2 JSON-in-Prompt vs Function Calling 对比

| 维度 | JSON-in-Prompt（当前） | Function Calling |
|------|------------------------|-------------------|
| **输出可靠性** | 依赖 prompt 质量，可能输出非 JSON 文本 | 模型原生约束，输出格式严格 |
| **Schema 校验** | 需手动 `json.loads()` + 手动校验 | 模型按 JSON Schema 生成，天然符合 |
| **多轮调用** | 需手动管理状态 | 工具调用天然支持多轮 |
| **模型支持** | 所有模型通用 | 需要模型支持（主流模型均支持） |
| **调试难度** | 较低（纯文本） | 中等（需处理工具调用消息） |
| **灵活性** | 高，可随时调整格式 | 受 Schema 约束，调整需改定义 |
| **流式解析** | 简单（字符级拼接） | 复杂（需处理 tool_call delta 累积） |

---

## 3. 路由机制：基于状态值而非工具选择

### 3.1 LangGraph 路由

`backend/agents/graph.py` 使用 `StateGraph` 的条件边进行路由：

```python
# 第 72 行
workflow = StateGraph(AgentState)

# 第 75-85 行：所有节点都是 agent 运行函数，非 ToolNode
workflow.add_node("profile", profile_agent.run)
workflow.add_node("planner", planner_agent.run)
# ...

# 条件路由基于 AgentState 字段值，而非工具调用结果
workflow.add_conditional_edges("profile", profile_agent.route_after_profile, {
    "end": END,
    "planner": "planner",
})
```

### 3.2 路由逻辑示例

```python
# profile_agent.py
async def route_after_profile(state: AgentState):
    if state["intent_type"] == "ask_question":
        return "end"
    return "planner"
```

路由依据是 AgentState 中的字段（如 `intent_type`、`resource_type`），而非 LLM 工具调用结果。

---

## 4. 当前模式的优势与局限

### 4.1 优势

1. **实现简单**：无需定义 tool schema、无需工具注册/分发/执行基础设施
2. **调试友好**：LLM 输出为纯文本 JSON，可直接打印查看
3. **模型无关**：不依赖特定模型对 function calling 的支持质量
4. **灵活迭代**：修改输出格式只需改 prompt 文本，无需改代码结构
5. **无额外延迟**：不产生 tool call → tool response 的额外 API 往返

### 4.2 局限

1. **JSON 解析脆弱性**：LLM 可能输出格式错误的 JSON、包含额外文本、使用 markdown 代码块包裹等
2. **无 Schema 强制执行**：模型可能遗漏字段或使用错误类型
3. **无法并行工具调用**：无法像 function calling 那样同时发起多个独立操作
4. **难以扩展**：新增结构化输出场景需要新增 prompt + 解析代码
5. **不适合交互式工具**：无法实现类似"调用外部 API 获取实时数据"的工具模式

---

## 5. 可引入 Function Calling 的潜在场景

如果未来考虑引入 function calling，以下场景收益最大：

### 5.1 外部知识检索（RAG 增强）

当前 `backend/agents/utils.py` 的 `retrieve_context()` 是硬编码的 RAG 检索。可以让 LLM 主动决定何时需要检索，而不是每次都检索：

```python
tools = [{
    "type": "function",
    "function": {
        "name": "search_knowledge_base",
        "description": "搜索知识库获取相关教学内容",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "top_k": {"type": "integer", "default": 5}
            },
            "required": ["query"]
        }
    }
}]
```

### 5.2 学生数据查询

Agent 可以通过工具函数查询数据库中的学生画像、学习记录等信息，而非在 prompt 中一次性传入所有上下文：

```python
tools = [{
    "type": "function",
    "function": {
        "name": "get_student_profile",
        "description": "获取学生的学习画像和掌握程度"
    },
}, {
    "type": "function",
    "function": {
        "name": "get_learning_history",
        "description": "获取学生最近的学习记录"
    }
}]
```

### 5.3 资源生成参数选择

将 planner_agent 的意图分类和资源类型选择改为函数调用，可获得更可靠的枚举值约束：

```python
tools = [{
    "type": "function",
    "function": {
        "name": "plan_resource_generation",
        "description": "规划要生成的资源类型和参数",
        "parameters": {
            "type": "object",
            "properties": {
                "resource_types": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["doc", "quiz", "mindmap", "code", "summary"]}
                },
                "kp_ids": {
                    "type": "array",
                    "items": {"type": "string"}
                }
            },
            "required": ["resource_types"]
        }
    }
}]
```

### 5.4 安全审查增强

`safety_agent` 可以将"通过/不通过"的 JSON 输出改为函数调用，并添加动作为参数：

```python
tools = [{
    "type": "function",
    "function": {
        "name": "submit_safety_review",
        "parameters": {
            "properties": {
                "passed": {"type": "boolean"},
                "issues": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                            "description": {"type": "string"}
                        }
                    }
                }
            }
        }
    }
}]
```

---

## 6. 引入 Function Calling 的改造成本估算

如果要将当前 JSON-in-Prompt 模式迁移到 function calling，涉及以下改造：

### 6.1 LLM 服务层（`backend/services/llm.py`）

- `chat_completion()` 需增加 `tools`、`tool_choice` 参数
- 返回类型从 `str` 改为包含 `content` + `tool_calls` 的结构体
- `stream_chat_completion()` 需处理 `delta.tool_calls` 累积
- 约 **50–80 行**改动

### 6.2 各 Agent 改造

- 每个使用 JSON 输出的 Agent 需要：
  - 将 prompt 中的 JSON 格式说明改为工具定义
  - 将 `json.loads(response)` 改为解析 `tool_calls[0].function.arguments`
  - 如果使用流式输出，需要额外的 tool_call delta 累积逻辑
- 预计每个 Agent **20–40 行**改动，共 9 个 Agent

### 6.3 路由逻辑

- `graph.py` 的 `add_conditional_edges` 函数可能需要调整为基于工具调用名称路由
- 如果引入需要执行结果反馈的工具（如知识库查询），需要在图中增加 `ToolNode`
- 约 **30–50 行**改动

### 6.4 配置

- `configs/config.yaml` 和 `backend/config.py` 需增加工具相关配置项（工具启用列表、tool_choice 默认值等）
- 约 **10–20 行**改动

### 总体估计

| 模块 | 改动量 |
|------|--------|
| LLM 服务层 | 50–80 行 |
| Agent 层（9 个） | 180–360 行 |
| 图路由 | 30–50 行 |
| 配置 | 10–20 行 |
| **总计** | **270–510 行** |

---

## 7. 建议的渐进式引入路径

如果决定引入 function calling，建议按以下优先级逐步推进：

1. **试点阶段**：选择输出结构最固定的 Agent（如 `safety_agent`，仅返回 `{passed: bool, issues: []}`），尝试 function calling
2. **验证收益**：对比 function calling 与 JSON-in-Prompt 在格式正确率、解析失败率上的差异
3. **基础设施完善**：在 `llm.py` 中完善 tools 支持和错误处理
4. **逐步推广**：按 Agent 重要性依次迁移（planner → quiz → recommend → profile → others）
5. **流式支持**：在需要流式输出的 Agent 上实现 tool_call delta 处理

---

## 8. 结论

- **当前状态**：项目完全基于 JSON-in-Prompt 模式实现结构化输出，无任何 function calling 能力
- **适用性**：对于当前 9 个 Agent 的场景，JSON-in-Prompt 模式功能上完全满足需求，且保持架构简单
- **引入时机**：当出现以下需求时，引入 function calling 的收益将超过改造成本：
  - 需要 LLM 动态决定调用外部工具/API
  - JSON 输出格式错误率超出可接受范围
  - 需要支持原生并行函数调用
  - 迁移至更严格的 function calling 模型（如 GPT-4 的 strict mode）
