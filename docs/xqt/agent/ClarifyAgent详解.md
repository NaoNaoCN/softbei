# ClarifyAgent 详解

## 概述

ClarifyAgent 是项目中**第 11 个 Agent**，与其他 10 个 Agent 不同——它**不在 LangGraph StateGraph 中运行**，而是一个独立的对话式 Agent，专门处理学生对已生成内容的**追问和澄清请求**。

**文件位置**：`backend/agents/clarify_agent.py`（64 行）

---

## 1. 设计动机

### 为什么需要独立的 ClarifyAgent？

项目的主 StateGraph 是为**资源生成**设计的：画像提取 → 意图分析 → 选择资源类型 → 生成 → 安全检查 → 推荐。但这个流水线不适合处理以下场景：

- 学生看完生成的文档后追问"这个注意力机制和多头注意力有什么区别？"
- 学生对思维导图中的某个节点不理解，要求解释
- 学生要求用更简单的话重新解释某个概念

这些场景的共同特征：
1. **不需要生成完整资源**，只需要简短、针对性的回答
2. **依赖对话历史**，不能只看当前消息
3. **不需要安全检查**，因为不是新生成的教学内容，而是对已有内容的解释
4. **不需要推荐下一步**，学生还在消化当前内容

如果把这些请求送入主 StateGraph，会触发生成新文档、安全检查、推荐等一系列不必要的流程。因此需要一个轻量级的对话 Agent 来处理。

### 与 ProfileAgent 的 clarify 有何区别？

| 维度 | ProfileAgent 的 clarify | ClarifyAgent |
|------|------------------------|--------------|
| **目的** | 向学生**提问**，收集画像信息 | **回答**学生的追问 |
| **方向** | Agent → 学生 | 学生 → Agent |
| **触发时机** | 画像不完整时（初次对话） | 学生看到生成内容后追问 |
| **产物** | `clarify_message`（追问内容） | `final_content`（回复内容） |
| **是否在主图中** | 是（StateGraph 入口节点） | 否（独立调用） |

---

## 2. 源代码分析

### 完整代码 (`backend/agents/clarify_agent.py`)

```python
SYSTEM_PROMPT = """你是一个学习辅导助手。学生正在对之前的对话内容进行追问或请求澄清。

你的任务：
- 基于对话历史，针对学生的追问给出简短、准确的回答
- 不要重新生成完整的学习文档或资源
- 回答要有针对性，直接解答学生的疑问
- 如果对话历史中有相关内容，引用并展开解释
- 保持回答简洁明了，像一个耐心的老师在回答学生的课堂提问

学生画像信息：
{profile_ctx}"""

async def run(state: AgentState, config: RunnableConfig) -> AgentState:
    # 1. 构建画像上下文
    profile_ctx = ""
    if state.profile:
        profile_ctx = await profile_svc.build_profile_context(state.profile)

    prompt = SYSTEM_PROMPT.format(profile_ctx=...)

    # 2. 构造消息列表：system + 对话历史 + 当前消息
    messages = [{"role": "system", "content": prompt}]
    messages.extend(state.chat_history)
    messages.append({"role": "user", "content": state.user_message})

    # 3. 调用 LLM 生成回复
    response = await chat_completion(messages, temperature=0.7)

    # 4. 写入 state.final_content
    state = state.model_copy(update={"final_content": response})
    return state
```

### 关键设计点

**1. 对话历史注入（最核心的设计）**

```python
messages.extend(state.chat_history)
```

ClarifyAgent 将完整的对话历史注入 prompt，让 LLM 可以"看到"之前生成的内容和上下文。这是它与生成 Agent 最大的区别——生成 Agent 只依赖 RAG 检索结果和当前用户消息，而 ClarifyAgent 需要理解对话上下文才能回答追问。

对话历史由 `backend/services/chat_history.py` 管理：
- 从动态 per-session 消息表加载
- 截断策略：最近 10 轮 + 4000 token 预算
- 确保从 user 消息开始（不会出现孤立的 assistant 消息）

**2. 画像感知**

通过 `{profile_ctx}` 注入学生画像，使回复可以个性化。例如：
- 视觉型学生 → 用图示类语言解释
- 文本型学生 → 用文字类比解释
- 知道学生的薄弱点 → 解释时特别注意这些概念

**3. 温度 0.7 — 需要一定创造力**

追问是开放式的，0.7 的温度让回答更自然、不机械。对比：SafetyAgent 用 0.1（需要精确判断），ProfileAgent 提取用 0.1（需要确定性输出）。

**4. 错误处理**

LLM 调用失败时，返回友好的降级消息：

```python
except Exception as e:
    state = state.model_copy(update={
        "final_content": "抱歉，我暂时无法回答这个问题，请稍后再试。",
        "error": str(e),
    })
```

---

## 3. 当前状态：未集成

ClarifyAgent 目前**已定义但尚未集成**到系统中：

- `backend/agents/clarify_agent.py` 文件存在且逻辑完整
- 但 `main.py` 和 `graph.py` 中**没有导入或调用** ClarifyAgent
- `AgentState` 中**没有 `chat_history` 字段**（ClarifyAgent 引用了 `state.chat_history`）

### 集成方案

要使 ClarifyAgent 生效，需要以下步骤：

1. **在 `AgentState` 中增加 `chat_history` 字段**：
   ```python
   chat_history: list[dict[str, str]] = Field(default_factory=list)
   ```

2. **在 `POST /chat/{session_id}` 中增加意图判断**，区分"请求生成资源"和"追问/澄清"：
   ```python
   # 伪代码
   if is_clarification(user_message, chat_history):
       # 加载对话历史 → 注入 state.chat_history → 调用 clarify_agent.run()
       result = await clarify_agent.run(state, config)
   else:
       # 走主 StateGraph
       result = await invoke(user_id, session_id, user_message, db)
   ```

3. **意图判断的实现**（可选方案）：
   - **方案 A**：PlannerAgent 分析 intent 时增加一个"追问"类别
   - **方案 B**：用独立轻量 LLM 调用做二分类（resource_request vs clarification）
   - **方案 C**：前端让用户选择模式

---

## 4. 与主流程的对比

| 维度 | 主 StateGraph | ClarifyAgent |
|------|---------------|--------------|
| **触发条件** | 用户请求生成学习资源 | 学生对已生成内容追问 |
| **输入** | `user_message` + RAG + profile | `user_message` + chat_history + profile |
| **LLM 温度** | 各 Agent 不同（0.1-0.7） | 0.7 |
| **输出** | 完整学习资源（文档/思维导图/题目等） | 简短对话回复 |
| **节点数** | 5-6 个节点流转 | 1 个节点直接返回 |
| **安全检查** | 经过 SafetyAgent | 跳过 `safety_agent` |
| **推荐** | 经过 RecommendAgent | 跳过 `recommend_agent` |
| **延迟** | 较长（多节点 + LLM 多次调用） | 较短（单次 LLM 调用） |

---

## 5. 在 11 Agent 体系中的定位

```
                ┌──────────────────────────────────────┐
                │          LangGraph StateGraph         │
                │                                      │
                │  profile → planner → generator →     │
                │  safety → recommend → END            │
                │                                      │
                └──────────────────────────────────────┘

                              ↑
                    请求生成资源 │ 追问/澄清
                              │        ↓
                          用户消息
                                    │
                        ┌───────────┴───────────┐
                        │   ClarifyAgent (独立)  │
                        │                       │
                        │  chat_history          │
                        │  + user_message        │
                        │  + profile             │
                        │       ↓               │
                        │  final_content        │
                        │  → END（直接返回）     │
                        └───────────────────────┘
```

ClarifyAgent 是"旁路"——不经过 LangGraph，独立处理对话式追问，直接返回。这样可以：
- 避免不必要的资源生成
- 避免不必要的安全检查
- 降低延迟
- 保持主 StateGraph 的职责单一

---

## 6. 设计启示

ClarifyAgent 的存在反映了多 Agent 系统的一个重要设计原则：**不是所有 Agent 都需要在编排图中**。

- **编排图中的 Agent** 处理有明确步骤和依赖关系的任务（如资源生成流水线）
- **独立 Agent** 处理单步对话任务（如追问、闲聊、解释）
- 独立的 Agent 可以让主图保持简洁，同时提供更大的灵活性
