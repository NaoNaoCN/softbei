# LangGraph 多智能体系统设计文档

## 1. 概述

本系统基于 **LangGraph**（`langgraph.graph.StateGraph`）构建了一个**条件路由的有向无环图（DAG）**，共包含 **11 个 Agent 节点**，协同完成从"理解学生需求"到"生成个性化学习资源"再到"安全审计与推荐"的完整链路。

### 设计目标

- **个性化**：每个 Agent 的生成都基于学生画像（薄弱点、学习目标、认知风格）
- **可扩展**：新增资源类型只需添加一个 Agent 节点并注册路由
- **可观测**：全链路状态通过 `AgentState` 传递，每一步都可审计
- **容错性**：LLM 调用失败有兜底策略，安全审计失败不阻断内容输出

---

## 2. 核心概念

### 2.1 StateGraph

`StateGraph` 是 LangGraph 的核心抽象：把一次完整的推理过程建模为一张有向图，每个节点是一个处理函数（Agent），边定义了节点之间的流转方向。与传统的线性 Pipeline 不同，StateGraph 支持**条件分支**——根据当前状态动态决定下一步走向。

### 2.2 AgentState — 全局状态

`AgentState`（定义于 `backend/models/schemas.py:373`）是在所有 Agent 节点间流转的**不可变数据对象**。每个 Agent 读取它，计算后返回一个新的副本（通过 `state.model_copy(update={...})`），而非原地修改。

| 字段 | 类型 | 写入者 | 说明 |
|---|---|---|---|
| `user_id` | `int` | 初始状态 | 用户 ID（Snowflake BIGINT） |
| `session_id` | `int` | 初始状态 | 会话 ID |
| `user_message` | `str` | 初始状态 | 用户当前输入 |
| `chat_history` | `list[dict]` | 初始状态 | 多轮对话历史 |
| `profile` | `StudentProfileIn?` | `profile_agent` | 学生画像 |
| `profile_complete` | `bool` | `profile_agent` | 画像是否满足最低要求，**决定是否放行到后续节点** |
| `intent_type` | `str?` | `planner_agent` | `"generate"` 或 `"clarify"` |
| `resource_type` | `ResourceType?` | `planner_agent` | 要生成的资源类型 |
| `kp_id` | `str?` | `planner_agent` | 目标知识点标识 |
| `retrieved_docs` | `list[str]` | 各生成 Agent | RAG 检索到的参考文档片段 |
| `draft_content` | `str?` | 各生成 Agent | 生成的原始内容（安全审计的输入） |
| `final_content` | `str?` | `safety_agent` / `clarify_agent` 等 | 最终输出给用户的内容 |
| `safety_passed` | `bool` | `safety_agent` | 内容是否通过安全审计 |
| `clarify_message` | `str?` | `profile_agent` | 追问/澄清消息 |
| `metadata` | `dict` | `planner_agent` / `recommend_agent` | 扩展数据（多资源意图、推荐结果等） |
| `error` | `str?` | 各 Agent | 错误信息 |

### 2.3 不可变更新模式

```python
# 每个 Agent 的标准更新方式
state = state.model_copy(update={"profile_complete": True, "final_content": "..."})
return state
```

这一模式确保了数据流清晰可追溯：任何 Agent 都不会意外修改其他 Agent 已经写入的数据。

---

## 3. 图拓扑

### 3.1 节点与边

```
                          START
                            │
                            ▼
                    ┌───────────────┐
                    │ profile_agent │  画像提取与完整性判断
                    └───────┬───────┘
                            │ 条件路由: profile_complete?
                   ┌────────┼────────┐
                   │ false           │ true
                   ▼                 ▼
                  END        ┌───────────────┐
                             │ planner_agent │  意图解析与资源规划
                             └───────┬───────┘
                                     │ 条件路由: intent_type + resource_type
                     ┌───────┬───────┼───────┬───────┬───────┬───────┐
                     │       │       │       │       │       │       │
                     ▼       ▼       ▼       ▼       ▼       ▼       ▼
                clarify  doc  mindmap  quiz   code  summary    kg    recommend
                _agent  _agent _agent _agent _agent  _agent  _agent  _agent
                   │       │       │       │       │       │       │
                   │       └───┬───┴───┬───┴───┬───┴───────┘       │
                   │           │       │       │                   │
                   │           ▼       ▼       ▼                   │
                   │      ┌──────────────────────┐                 │
                   │      │    safety_agent      │  内容安全审计    │
                   │      └──────────┬───────────┘                 │
                   │                 │                              │
                   ▼                 ▼                              ▼
                  END    ┌──────────────────────┐
                         │  recommend_agent     │  后续学习推荐
                         └──────────┬───────────┘
                                    │
                                    ▼
                                   END
```

### 3.2 边汇总

| 来源节点 | 目标节点 | 类型 |
|---|---|---|
| `profile_agent` | `planner_agent` 或 `END` | **条件边** |
| `planner_agent` | `doc_agent` / `mindmap_agent` / `quiz_agent` / `code_agent` / `summary_agent` / `kg_agent` / `clarify_agent` / `recommend_agent` | **条件边** |
| `doc_agent` → `summary_agent` | `safety_agent` | 固定边 |
| `safety_agent` | `recommend_agent` | 固定边 |
| `kg_agent` | `recommend_agent` | 固定边（**跳过安全审计**） |
| `recommend_agent` | `END` | 固定边 |
| `clarify_agent` | `END` | 固定边（**跳过安全审计和推荐**） |

---

## 4. Agent 详解

### 4.1 ProfileAgent — 画像提取与准入控制

**文件**：`backend/agents/profile_agent.py`

**职责**：作为图的入口节点，充当整个系统的"守门人"。

**工作流程**：

1. **画像提取**：调用 LLM 从用户消息中提取专业、学习目标、认知风格、已掌握/薄弱知识点等字段（JSON 格式），温度 0.1 保证准确。
2. **增量合并**：将提取结果合并到数据库的 `StudentProfile` 表（数组字段去重追加，非替换）。若 DB 不可用则回退到内存合并。
3. **意图判断**：调用 LLM 判断用户消息是否包含资源请求意图（`yes` / `no`）。
4. **完整性检查**：要求 `learning_goal`、`knowledge_weak`、`knowledge_mastered` 至少一个非空。
5. **决策路由**：

| 画像完整？ | 有资源请求？ | 教材已上传？ | 首次画像？ | 动作 |
|---|---|---|---|---|
| 是 | 是 | 否 | 是 | 引导上传教材，`profile_complete=False`，消息为引导语 |
| 是 | 是 | 是/非首次 | — | `profile_complete=True`，放行到 planner |
| 是 | 否 | — | — | 生成确认消息，`profile_complete=False` |
| 否 | — | — | — | 生成追问消息，`profile_complete=False` |

**路由函数** `route_after_profile()`：
```python
def route_after_profile(state: AgentState) -> str:
    if state.profile_complete:
        return "planner_agent"
    return END
```

### 4.2 PlannerAgent — 意图解析与资源规划

**文件**：`backend/agents/planner_agent.py`

**职责**：判断用户想要什么类型的资源以及针对哪个知识点。

**工作流程**：

1. **快速通道**：若 `state.resource_type` 和 `state.kp_id` 已预设（直接生成模式），跳过 LLM 分析。
2. **意图分类**（有对话历史时）：调用 LLM 判断是 `"generate"`（新资源请求）还是 `"clarify"`（追问之前的内容）。设 `intent_type="clarify"` 时直接返回，路由到 `clarify_agent`。
3. **知识点匹配**：查询 `KGNode` 表（按 `user_id` 过滤，上限 500 条），构建可用知识点列表。
4. **资源类型判断**：调用 LLM 一次完成三项判断：
   - `resource_type`：doc / mindmap / quiz / code / summary / kg
   - `kp_id`：目标知识点名称
   - `extra_types`：多资源意图时附加的类型列表
5. **兜底**：LLM 解析失败时默认 `ResourceType.doc`；`kp_id` 为空时取用户消息前 50 字符。

**路由函数** `route_by_resource_type()`：
```python
def route_by_resource_type(state: AgentState) -> str:
    if state.intent_type == "clarify":
        return "clarify_agent"
    mapping = {
        ResourceType.doc: "doc_agent",
        ResourceType.mindmap: "mindmap_agent",
        ResourceType.quiz: "quiz_agent",
        ResourceType.code: "code_agent",
        ResourceType.summary: "summary_agent",
        ResourceType.kg: "kg_agent",
    }
    return mapping.get(state.resource_type, "recommend_agent")
```

此外，`planner_agent` 还提供了独立的 `plan_resource_types()` 函数，用于 `/generate/smart` 端点，根据画像推荐 2-3 种最佳资源类型组合。

### 4.3 五个生成 Agent

**文件**：`backend/agents/doc_agent.py`、`mindmap_agent.py`、`quiz_agent.py`、`code_agent.py`、`summary_agent.py`

五个生成 Agent 遵循**相同的模式**，差异仅在于 Prompt 和输出格式：

```
1. resolve_kp_name() → 解析知识点名称
2. retrieve_context() → RAG 检索相关文档（带请求级缓存）
3. 构建专用 System Prompt（注入画像、知识点、参考上下文）
4. chat_completion() → 调用 LLM 生成
5. 写入 state.draft_content + state.retrieved_docs
```

| Agent | 输出格式 | 温度 | 特殊处理 |
|---|---|---|---|
| **DocAgent** | Markdown 文档，带 `[n]` 引用标记 | 0.7 | — |
| **MindmapAgent** | JSON（ECharts tree 格式 `{name, children}`） | 0.5 | 校验 JSON 有效性，限制深度 ≤4、子节点 ≤6 |
| **QuizAgent** | JSON 数组（单选/多选/填空） | 0.6 | 根据薄弱点数量动态调整题型配比 [基础, 进阶, 综合] |
| **CodeAgent** | Markdown + Python 参考解答（`# ===== 参考答案 =====` 分隔） | 0.7 | max_tokens 5000 |
| **SummaryAgent** | Markdown 要点总结 + LaTeX 公式 | 0.7 | 300-500 词目标 |

### 4.4 KGAgent — 知识图谱构建

**文件**：`backend/agents/kg_agent.py`

**职责**：从导入的文档自动构建知识图谱。与其他生成 Agent 不同，它不直接生成内容，而是**编排** `backend/services/kg_builder.py` 的构建流程：

1. 从向量库获取文档的所有文本块
2. 按页/TOC 章节分组
3. **并发**（信号量控制 ≤10）调用 LLM 提取知识点（节点）和关系（边）
4. 去重 → 创建 `Course` 根节点 → 清除旧数据 → 批量写入 `KGNode` / `KGEdge`
5. 返回构建摘要到 `state.final_content`

**路由**：跳过 `safety_agent`，直接到 `recommend_agent`。

### 4.5 ClarifyAgent — 追问处理

**文件**：`backend/agents/clarify_agent.py`

**职责**：处理用户对历史回答的追问（如"上一部分展开说说"），而非新的资源生成。

基于对话历史给出简短的针对性回答，写入 `state.final_content`，**直接走到 `END`**，不经过安全审计。

### 4.6 SafetyAgent — 内容安全审计

**文件**：`backend/agents/safety_agent.py`

**职责**：对生成内容进行质量检查，但不拦截输出。

**关键设计决策**：

- 取前 3 条参考文档和前 500 字草稿，调用 LLM 检查事实一致性、明显错误、学习适用性
- 返回 `{passed: bool, issues: [...]}`
- **无论通过与否，原稿始终保留为 `final_content`**——安全审计只记录问题，不修改内容
- LLM 调用失败时默认通过（不阻塞流程）

### 4.7 RecommendAgent — 后续学习推荐

**文件**：`backend/agents/recommend_agent.py`

**职责**：基于用户画像推荐 3-5 个后续学习知识点。

**反幻觉设计**：
1. 从 `KGNode` 表查询所有可用知识点
2. 交给 LLM 推荐，每个推荐带理由
3. **验证**：用数据库结果过滤 LLM 输出——只保留真实存在的 `kp_id`

结果写入 `state.metadata["recommendations"]` 和 `state.metadata["recommendations_text"]`。

---

## 5. 数据库会话注入机制

数据库会话**不存储在 AgentState 中**，而是通过 LangGraph 的 `RunnableConfig` 传递：

```python
# 调用侧
result = await get_graph().ainvoke(
    initial_state,
    config={"configurable": {"db": db}},
)

# Agent 侧
db = config["configurable"].get("db") if config and "configurable" in config else None
```

这样设计的好处：
- `AgentState` 保持纯数据，不含基础设施依赖
- 每个 Agent 可以独立决定是否使用 DB（如 `safety_agent` 完全不需要）
- 测试时可以轻松注入 mock 会话

---

## 6. 两种执行模式

### 6.1 非流式（`ainvoke`）

```python
result = await get_graph().ainvoke(initial_state, config={"configurable": {"db": db}})
final_state = AgentState(**result)
```

用于普通 API 调用（`POST /chat/{session_id}`），返回完整最终状态。前端一次性拿到结果。

### 6.2 流式（`astream`）

```python
async for event in get_graph().astream(initial_state, config={"configurable": {"db": db}}):
    yield event
```

用于 SSE 流式端点（`POST /chat/{session_id}?stream=true`），每个节点完成后即向前端推送中间状态，实现实时进度展示。

---

## 7. RAG 集成

所有生成 Agent 通过 `backend/agents/utils.py` 中的 `retrieve_context()` 共享 RAG 检索：

```python
async def retrieve_context(kp_name: str, user_id: int, agent_label: str) -> str:
```

**请求级缓存**：同一知识点的检索结果在单次图调用中只执行一次，多个 Agent 使用时复用缓存。缓存在图入口 `invoke()` / `stream_invoke()` 开始时清除。

**检索流程**：
1. `kp_name` → Embedding API 向量化
2. PostgreSQL pgvector 余弦相似度检索（阈值 ≥0.5）
3. 关键词重排序
4. 格式化为带引用标记的上下文字符串
5. 注入 Agent 的 System Prompt

---

## 8. 配置驱动设计

所有 Agent 的 LLM 参数集中管理在 `configs/config.yaml` 的 `agents` 节：

```yaml
agents:
  profile:
    extract_temperature: 0.1    # 画像提取：低温度保证准确
    intent_temperature: 0.0     # 意图判断：完全确定性
    clarify_temperature: 0.7    # 追问：需要自然多变
  planner:
    intent_temperature: 0.0     # 意图分类：完全确定性
    classify_temperature: 0.1   # 资源分类：极低随机性
  doc:
    temperature: 0.7
    max_tokens: 4000
  # ...
```

不同 Agent 使用不同的 temperature 体现了一个关键设计理念：**分类/提取任务用低温（0-0.1），生成/对话任务用高温（0.5-0.7）**。

---

## 9. 容错设计

系统在多个层次上做了容错处理：

| 层级 | 策略 |
|---|---|
| **LLM 调用** | tenacity 指数退避重试（最多 5 次，3s→30s） |
| **JSON 解析** | `parse_json_llm_response()` 自动清理 markdown 代码块 |
| **画像合并** | DB 失败时回退到内存合并 |
| **RAG 检索** | 失败时返回空上下文，Agent 用通用知识生成 |
| **安全审计** | 失败时默认通过，不阻断输出 |
| **推荐验证** | LLM 输出的知识点 ID 必须真实存在于 DB 中 |
| **路由兜底** | 无法匹配的资源类型默认路由到 `recommend_agent` |
| **资源类型兜底** | 解析失败默认 `ResourceType.doc` |
| **知识点兜底** | 为空时取用户消息前 50 字符 |

---

## 10. 扩展指南

### 添加新的资源类型 Agent

1. 创建 `backend/agents/xxx_agent.py`，实现 `async def run(state: AgentState, config: RunnableConfig) -> AgentState`
2. 在 `ResourceType` 枚举中添加新值（`backend/models/schemas.py`）
3. 在 `graph.py` 的 `build_graph()` 中：
   - `graph.add_node("xxx_agent", xxx_agent.run)`
   - 添加固定边：`graph.add_edge("xxx_agent", "safety_agent")`（或 `"recommend_agent"` 如果需要跳过安全审计）
4. 在 `planner_agent.py` 的 `route_by_resource_type()` 的 `mapping` 字典中添加映射
5. 在 `planner_agent.py` 的 `SYSTEM_PROMPT` 中添加对新类型的描述
6. 在 `configs/config.yaml` 的 `agents` 节添加配置

### 添加新的条件路由分支

在 `graph.py` 的 `build_graph()` 中使用 `graph.add_conditional_edges()` 注册路由函数和分支映射。路由函数签名为 `(state: AgentState) -> str`，返回目标节点名称。
