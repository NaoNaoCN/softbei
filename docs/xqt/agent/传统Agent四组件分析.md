# 传统 Agent 四组件架构分析

## 概述

传统智能体（Agent）的基本架构包含四个核心组件：**LLM（大语言模型）**、**工具（Tools）**、**记忆（Memory）**、**规划模块（Planning）**。本文档逐一分析本项目（softbei — 个性化资源生成与学习多智能体系统）中这四个组件的实现方式和完备程度。

---

## 1. LLM（大语言模型）

### 1.1 实现方式

LLM 组件由 `backend/services/llm.py` 统一封装，作为所有 Agent 的底层推理引擎。

### 1.2 多供应商支持

支持 4 个 LLM 供应商，通过 `configs/config.yaml` 配置切换（`backend/services/llm.py:35-44`）：

| 供应商 | 标识符 | API 网关 |
|--------|--------|----------|
| 通义千问（DashScope） | `qwen` | `https://dashscope.aliyuncs.com/compatible-mode/v1` |
| 讯飞星火 | `spark` | `https://spark-api-open.xf-yun.com/v1` |
| DeepSeek | `deepseek` | `https://api.deepseek.com/v1` |
| OpenAI | `openai` | `https://api.openai.com/v1` |

### 1.3 核心能力

- **同步生成**（`chat_completion`，`backend/services/llm.py:90-132`）：支持自定义 `model`、`temperature`、`max_tokens`，内置指数退避重试（tenacity），对千问配额耗尽自动切换备用模型。
- **流式生成**（`stream_chat_completion`，`backend/services/llm.py:135-177`）：异步生成器，逐 token 产出 delta 文本，用于前端实时展示。
- **嵌入生成**（`get_embedding` / `get_embeddings_batch`，`backend/services/llm.py:179-259`）：DashScope `text-embedding-v4`，1024 维向量，用于 RAG 向量检索。

### 1.4 当前模型

项目当前使用 `qwen3.6-plus-2026-04-02`，通过 DashScope API 调用（`configs/config.yaml`）。

### 1.5 使用模式

**纯文本生成模式**：所有 Agent 调用 `chat_completion()` 时仅传递 `messages` 列表（system prompt + user message），不启用 function calling / tool use 机制。LLM 的角色是"给定上下文，生成文本"——结构化输出（如 JSON）通过 system prompt 中的格式指令约束，由 Python 代码解析。

### 1.6 结论

LLM 组件**完整且独立**。多供应商封装、重试机制、流式支持和嵌入服务均已就位，是系统中最为成熟的组件。

---

## 2. 工具（Tools）

### 2.1 实现方式

本项目**未使用标准化的工具调用机制**（无 OpenAI function calling、无 LangChain `@tool` 装饰器、无 MCP 协议集成）。所有"工具"本质上是 Python 函数，在 Agent 代码中**命令式调用**，LLM 不参与工具的选择决策。

### 2.2 命令式工具清单

| 工具函数 | 文件位置 | 功能说明 | 调用时机 |
|----------|----------|----------|----------|
| `retrieve_context()` | `backend/agents/utils.py:438` | RAG 检索全流程：查询改写、向量/关键词混合检索、上下文格式化 | 各生成 Agent 调用 LLM **之前** |
| `search_videos()` | `backend/services/video_search.py` | 搜索 Bilibili/Tavily 视频资源 | 生成完成后按需调用 |
| `merge_chat_updates()` | `backend/services/profile.py:154` | 增量合并 LLM 提取的画像字段到数据库 | profile_agent 提取画像**之后** |
| `build_kg()` | `backend/services/kg_builder.py` | 知识图谱构建（节点提取 + 边推理） | kg_agent 独立路径 |
| `build_profile_context()` | `backend/services/profile.py:342` | 将 `StudentProfileOut` 序列化为 prompt 文本 | 构造 LLM 输入的画像上下文 |
| `load_chat_history()` | `backend/services/chat_history.py:67` | 从 `ChatMessage` 表加载多轮对话历史 | 每次 graph 调用开始时 |
| `_rewrite_query()` | `backend/agents/utils.py:289` | 查询去上下文化 + 画像感知改写（策略 A+B） | RAG 检索前 |
| `_expand_queries()` | `backend/agents/utils.py:368` | 多角度查询扩展（策略 C，生成 3-5 个子查询） | RAG 检索前（可选） |
| `_rrf_fusion()` | `backend/agents/utils.py:400` | 倒数排名融合（Reciprocal Rank Fusion） | 多查询检索结果合并 |
| `parse_json_llm_response()` | `backend/agents/utils.py:61` | 剥离 Markdown 代码块包裹 | 每次 LLM 返回 JSON 后 |
| `safe_json_loads()` | `backend/agents/utils.py:75` | 多策略 JSON 修复（LaTeX 转义、截断修复、文本提取） | 每次 LLM 返回 JSON 后 |

### 2.3 调用模式示意

```
Agent.run()
  ├── [工具] load_chat_history()          # 加载对话历史（记忆）
  ├── [工具] retrieve_context()           # RAG 检索（知识获取）
  │     ├── _rewrite_query()              # 查询改写
  │     ├── _expand_queries()             # 查询扩展
  │     └── _rrf_fusion()                 # 结果融合
  ├── [LLM]  chat_completion()            # 文本生成
  ├── [工具] parse_json_llm_response()    # 解析 LLM 输出
  ├── [工具] search_videos()              # 视频搜索
  └── [工具] merge_chat_updates()         # 持久化状态更新
```

### 2.4 与标准化工具调用的差异

| 维度 | 标准化工具调用（如 OpenAI function calling） | 本项目实现 |
|------|---------------------------------------------|------------|
| 决策者 | LLM 自主决定是否、何时、调用哪个工具 | Python 代码固定逻辑 |
| 调用方式 | LLM 返回 `tool_calls` 数组，框架执行后回传结果 | 代码在 LLM 调用前后直接执行函数 |
| 灵活性 | LLM 可动态组合工具链 | 工具链由代码固定编排 |
| 可观测性 | 需解析 tool_calls 消息查看决策 | 直接查看 Python 调用栈 |
| 错误处理 | 需处理 LLM 幻觉的工具名/参数 | Python 异常处理 |

### 2.5 结论

工具组件**功能齐全但非标准化**。所有必要的工具能力（检索、搜索、持久化、知识图谱构建）均已实现，但采用命令式调用而非 LLM 自主工具选择。这简化了错误处理，但牺牲了 LLM 动态编排工具的灵活性。对于本项目的确定性教育场景（生成文档、测验、思维导图等），命令式模式是合适的选择。

---

## 3. 记忆（Memory）

### 3.1 实现方式

本项目的记忆系统分为**三个层次**，从短到长递进：

### 3.2 第一层：对话记忆（Conversation Memory）

- **载体**：`AgentState.chat_history: list[dict[str, str]]`（`backend/models/schemas.py:477-500`）
- **存储**：`ChatMessage` 数据库表（`backend/db/models.py`），每次对话的 user/assistant 消息均持久化
- **加载**：`load_chat_history()`（`backend/services/chat_history.py:67-105`），按 `session_id` 查询，取最近 N 轮
- **截断策略**（`truncate_history()`，`backend/services/chat_history.py:26-64`）：
  - 按轮次截断：保留最近 `max_turns=10` 轮对话
  - 按 token 截断：累计 token 数超过 `history_max_tokens=4000` 时截断
  - 确保首条消息为 `user` 角色（不遗留孤立的 assistant 消息）
- **生命周期**：会话级别（有过期时间 `session_expiry_days=30`）

### 3.3 第二层：画像记忆（Profile Memory）

- **载体**：`AgentState.profile: StudentProfileIn`（`backend/models/schemas.py`）
- **存储**：`StudentProfile` + `ProfileHistory` 数据库表
- **核心字段**：
  - `major` — 专业
  - `learning_goal` — 学习目标（支持 LLM 异步摘要压缩）
  - `cognitive_style` — 认知风格
  - `knowledge_mastered` — 已掌握知识点
  - `knowledge_weak` — 薄弱知识点
  - `error_prone` — 易错点
  - `goal_questions` — 历史提问列表
- **更新机制**（`backend/services/profile.py:154`）：
  - 每次对话，`profile_agent` 调用 LLM 从用户消息中提取画像字段
  - 增量合并到数据库（非覆盖式，仅填充空字段，追加列表字段）
  - 异步触发 `learning_goal` 摘要压缩（单工作线程 + 120 秒去抖动）
  - 测验答题后根据正确率阈值更新 `knowledge_mastered`/`knowledge_weak`
- **版本历史**：`ProfileHistory` 表记录每次画像变更的增量 snapshot
- **生命周期**：跨会话持久化（用户级别）

### 3.4 第三层：元数据记忆（Metadata Memory）

- **载体**：`AgentState.metadata: dict[str, Any]`
- **用途**：单次 graph 调用中的节点间数据传递
  - `extra_resource_types` — 多资源意图标记
  - `safety_issues` — 安全审查问题列表
  - `recommendations` — 推荐的知识点
  - `video_refs` — 视频引用
  - `kg_result` — 知识图谱构建结果
  - `generation_latency_ms` — 生成耗时记录
- **生命周期**：单次请求（request-scoped）

### 3.5 记忆架构总结

```
┌──────────────────────────────────────────────────┐
│ 记忆层次                                           │
├──────────────┬───────────────┬───────────────────┤
│ 元数据记忆     │ 对话记忆       │ 画像记忆           │
│ metadata{}   │ chat_history  │ profile           │
│ 单次请求      │ 会话级别       │ 用户级别           │
│ 节点间传递     │ 多轮上下文     │ 跨会话累积         │
│ 内存 dict     │ ChatMessage表  │ StudentProfile表  │
└──────────────┴───────────────┴───────────────────┘
```

### 3.6 结论

记忆组件**层次分明、设计完备**。三层记忆递进覆盖了从单次请求的临时状态到跨会话的用户画像，截断策略和异步压缩机制考虑了 LLM 上下文窗口的实际限制。相比许多仅保留对话历史的 Agent 系统，本项目的三层记忆架构是一大亮点。

---

## 4. 规划模块（Planning）

### 4.1 实现方式

本项目的规划不是在单个 Agent 内部通过 ReAct / Chain-of-Thought 实现的动态推理循环，而是通过**三层静态规划**实现：

### 4.2 第一层：Graph 拓扑规划（执行流程规划）

由 `backend/agents/graph.py:52-129` 中的 `build_graph()` 定义。基于 LangGraph `StateGraph`，定义了 11 个节点的固定执行拓扑：

```
START -> profile_agent
           ├── profile_complete=False ──> END
           └── profile_complete=True  ──> planner_agent
                                            ├── intent="clarify" ──> clarify_agent ──> END
                                            └── intent="generate" ──> [按resource_type路由]
                                                 ├── doc_agent ──────┐
                                                 ├── mindmap_agent ───┤
                                                 ├── quiz_agent ──────┤
                                                 ├── code_agent ──────┼──> safety_agent
                                                 ├── anim_agent ──────┤         │
                                                 └── summary_agent ───┘         │
                                                                               v
                                                 ┌── kg_agent ────────> recommend_agent ──> END
                                                 └── (fallback) ──────> recommend_agent ──> END
```

**特点**：条件路由（`conditional_edges`），非并行扇出（每次执行仅分发到一个生成节点），节点顺序固定不可变。

### 4.3 第二层：意图分类与资源类型选择（任务规划）

由 `planner_agent`（`backend/agents/planner_agent.py`）实现，包含两个 LLM 分类步骤：

**步骤 1 — 意图分类**（`planner_agent.py:55-78`）：
- 输入：最近 6 条对话历史 + 当前用户消息
- 输出：`{"intent": "generate"}` 或 `{"intent": "clarify"}`
- 路由：`clarify` 直接转到 `clarify_agent` 并结束（跳过安全审查）

**步骤 2 — 资源类型选择**（`planner_agent.py:104-167`）：
- 输入：用户消息 + 学生画像 + 可选知识点列表（从 `KGNode` 表查询）
- 输出：`{"resource_type": "doc", "kp_id": "...", "extra_types": ["quiz"]}`
- 路由：`resource_type` 决定分发到哪个生成 Agent
- 多资源支持：`extra_types` 字段支持一次请求产出多种资源（如同时生成文档和测验）

### 4.4 第三层：画像完备性判断（准入规划）

由 `profile_agent`（`backend/agents/profile_agent.py:86-279`）实现。在执行任何资源生成之前，检查学生画像是否完整：

| 场景 | 行为 |
|------|------|
| 画像不完整 + 请求资源 | 生成针对缺失字段的澄清问题，引导用户补充信息 |
| 画像完整 + 首次对话 + 无上传文档 | 生成文档上传引导消息，鼓励用户上传学习材料 |
| 画像完整 + 请求资源 | 放行到 `planner_agent` |
| 画像完整 + 非资源请求 | 生成确认消息，询问是否需要帮助 |

### 4.5 独立规划函数

`plan_resource_types()`（`planner_agent.py:197-256`）：独立的资源类型推荐函数，非 graph 节点，由批量生成 API 调用。根据学生画像和知识点特征推荐 2-3 种资源类型。

### 4.6 与 ReAct 式规划的对比

| 维度 | ReAct / 动态规划 | 本项目实现 |
|------|------------------|------------|
| 执行模型 | Think -> Act -> Observe -> Think -> ... 循环 | 单次 LLM 分类 -> 固定路由 |
| 任务拆解 | LLM 自主拆解为子步骤 | 代码预设的固定任务类型 |
| 错误恢复 | 可观察结果后重试或调整计划 | 依赖异常处理和重试机制 |
| 复杂度 | 高（Token 消耗大、循环控制难） | 低（确定性路由、可控性强） |
| 适用场景 | 开放域任务、探索性对话 | 教育领域的封闭式任务类型 |

### 4.7 结论

规划模块**面向确定性场景设计，简洁有效**。三层规划（Graph 拓扑 -> 意图/资源分类 -> 画像门控）覆盖了从执行流程到任务选择再到准入控制的完整规划链路。不足之处在于：缺少任务拆解（将复杂请求拆分为子步骤的能力）和动态重规划（执行失败后自动调整策略的能力）。但对于本项目的教育场景——资源类型有限、生成流程固定——当前设计是充分的。

---

## 5. 综合评估

### 5.1 四组件完备度矩阵

| 组件 | 是否存在 | 完备度 | 标准化程度 | 关键特点 |
|------|----------|--------|------------|----------|
| LLM | 是 | 高 | 高 | 多供应商、重试、流式、嵌入 |
| 工具 | 是 | 中 | 低 | 命令式调用、非标准化、但功能齐全 |
| 记忆 | 是 | 高 | 中 | 三层递进、增量合并、异步压缩 |
| 规划 | 是 | 中 | 低 | 静态路由、单次分类、无动态重规划 |

### 5.2 架构选型合理性

本项目选择**流水线式 Agent 架构**（LangGraph StateGraph）而非 **ReAct/工具调用式架构**，这一选择是由其业务场景决定的：

1. **任务类型封闭**：教育资源生成仅有 6 种固定类型（文档、思维导图、测验、代码、动画、摘要），不存在 LLM 需要动态决定"用什么工具"的场景。
2. **确定性优先**：教育场景对内容正确性要求极高（"不编造"是所有 prompt 的最高优先级规则），命令式工具调用消除了 LLM 幻觉工具名/参数的风险。
3. **成本可控**：每条消息仅做 2-3 次单轮 LLM 调用（profile -> planner -> generator），而非 ReAct 的 5-10 轮思考-行动循环，Token 消耗大幅降低。
4. **可观测性强**：Python 调用栈清晰，每个工具的输入输出可直接日志记录和调试。

### 5.3 可改进方向

1. **工具标准化**：可考虑引入 function calling 用于少数动态场景（如教学对话中的"学生追问"），使系统能处理规划之外的灵活交互。
2. **动态规划**：对于复杂请求（如"帮我系统学习微积分"），当前缺乏将大任务拆解为多轮子任务的能力，可引入任务拆解节点。
3. **记忆检索**：画像记忆当前是全量注入 prompt，当知识点列表极大时可能超长。可考虑对画像做向量检索，仅注入最相关的片段。
4. **规划验证**：缺少对规划结果的校验步骤（如：规划选择的资源类型是否与知识点真正匹配），可加入反思节点。

### 5.4 总体结论

本项目**具备传统 Agent 四组件的全部要素**，各组件以适合教育场景的方式落地：

- LLM 是最成熟的基础设施层
- 记忆是设计最出彩的组件，三层递进架构远超同类系统
- 工具功能齐全但以命令式实现，在确定性场景中这是正确的权衡
- 规划简洁有效，面向封闭任务类型做了恰当的设计

整体架构体现了"为场景而设计"的工程理念——不盲目追求 ReAct 范式的灵活性，而是在教育领域的约束条件下，用最少的 LLM 调用和最确定的路由逻辑，实现高质量、高可控的资源生成。
