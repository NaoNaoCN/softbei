# Token 统计方案分析

## 当前状态

**项目目前没有任何 token 用量统计。** 所有 LLM 调用都经过 `backend/services/llm.py` 的 `chat_completion()` 和 `stream_chat_completion()`，但 OpenAI API 返回的 `response.usage` 对象（包含 `prompt_tokens`、`completion_tokens`、`total_tokens`）在函数内部被**直接丢弃**，只提取了文本内容返回。

```python
# backend/services/llm.py:113-120 — 当前实现
response = await client.chat.completions.create(
    model=model, messages=messages,
    temperature=temperature, max_tokens=max_tokens,
)
return response.choices[0].message.content or ""
# ⚠️ response.usage 被丢弃，包含 prompt_tokens / completion_tokens / total_tokens
```

### 已有的 token 相关代码

项目中唯一与 token 相关的功能是 `backend/services/chat_history.py` 中的 `estimate_tokens()`：

```python
# 基于字符数的启发式估算（非真实 token 计数）
cn_chars / 1.5 + en_chars / 4.0
```

仅用于截断聊天历史以适应 token 预算（`history_max_tokens: 4000`），**不涉及实际 LLM API 消耗统计**。

### 影响范围

整个系统中**所有 LLM 调用都是 token 统计的盲区**：

| 模块 | LLM 调用次数（每次对话） | 说明 |
|------|------------------------|------|
| `profile_agent` | 1-3 次 | 用户画像提取 + 意图识别 + 追问 |
| `planner_agent` | 1-2 次 | 意图分类 + 智能规划 |
| `doc_agent` | 1 次 | 文档生成 |
| `mindmap_agent` | 1 次 | 思维导图生成 |
| `quiz_agent` | 1 次 | 测验生成 |
| `code_agent` | 1 次 | 代码生成 |
| `summary_agent` | 1 次 | 摘要生成 |
| `safety_agent` | 1 次 | 内容安全审核 |
| `recommend_agent` | 1 次 | 推荐生成 |
| `utils.py` (Query Rewrite) | 1-3 次 | RAG 查询改写 |
| `kg_builder.py` | 多次 | 知识图谱构建 |
| `evaluation/judge.py` | 多次 | 评估 Judge |
| `main.py` (auto-title) | 1 次 | 对话自动标题 |

一次完整的资源生成对话可能涉及 **10-20 次 LLM 调用**，每次调用的 token 消耗从几百到上万不等，累积用量可观但完全不可见。

---

## 捕获点分析

### 唯一扼流点：`backend/services/llm.py`

所有 LLM 调用都经过两个函数，只需在这两个函数中捕获即可覆盖全系统：

**1. `chat_completion()` — 非流式调用（占大多数）**

```python
# line 113-119
response = await client.chat.completions.create(...)
# ← 在此处 response.usage 可用：
#   response.usage.prompt_tokens     — 输入 token 数
#   response.usage.completion_tokens — 输出 token 数
#   response.usage.total_tokens      — 总 token 数
return response.choices[0].message.content or ""
```

这是**最简单的捕获点**：一次同步获取，无需特殊处理。

**2. `stream_chat_completion()` — 流式调用**

```python
# line 149-156
async for chunk in stream:
    if chunk.choices and chunk.choices[0].delta.content:
        yield chunk.choices[0].delta.content
# ← 流结束后，最后一个 chunk 可能包含 usage（取决于 provider）
```

流式调用的 token 统计需要特殊处理：
- OpenAI / DeepSeek：最后一个 chunk 的 `chunk.usage` 包含完整统计
- DashScope (qwen)：需在流结束后通过 `stream.response.headers` 中的 `x-dashscope-usage` 获取
- 或者在流结束后单独做一次 token 估算

### 辅助捕获点：embedding 调用

```python
# get_embedding() — line 201-216
# get_embeddings_batch() — line 219-236
```

embedding 也有 token 消耗（按文本长度计费），但通常远小于生成调用，且 OpenAI 兼容 API 的 embedding 响应也包含 `usage.total_tokens`。

---

## 统计方案设计

### 方案一：轻量级 — 仅 Log 记录（推荐起步）

**实现：** 在 `chat_completion()` 和 `stream_chat_completion()` 中捕获 `usage`，通过 loguru 输出结构化日志。

```python
# 改造后的 chat_completion
response = await client.chat.completions.create(...)

# 记录 token 用量
if hasattr(response, 'usage') and response.usage:
    logger.info(
        "[LLM] token_usage | model={} provider={} "
        "prompt={} completion={} total={}",
        model, provider,
        response.usage.prompt_tokens,
        response.usage.completion_tokens,
        response.usage.total_tokens,
    )

return response.choices[0].message.content or ""
```

**优势：**
- 改动极小，仅修改 `llm.py` 一个文件
- 立即可用，无需数据库变更
- 日志文件天然带时间戳，可做离线分析
- 结合 loguru 的日志轮转，自动归档

**劣势：**
- 无法实时查询和聚合（需 grep/awk 或日志分析工具）
- 无法按用户/会话维度统计
- 无法做成本核算

**适用场景：** 开发调试、性能摸底、单次对话排查

---

### 方案二：结构化 — 写入数据库（推荐生产）

**实现：** 新增 `TokenUsage` 表，在 LLM 调用后异步写入。

#### 2.1 数据模型

```python
# backend/db/models.py — 新增 ORM 模型
class TokenUsage(Base):
    __tablename__ = "token_usage"

    id = Column(UUID, primary_key=True, default=uuid4)
    user_id = Column(String(255), nullable=False, index=True)
    session_id = Column(UUID, nullable=True, index=True)
    agent_name = Column(String(100), nullable=True, index=True)   # 调用来源
    provider = Column(String(50), nullable=False)                 # spark/deepseek/qwen/openai
    model = Column(String(100), nullable=False)                    # 具体模型名
    prompt_tokens = Column(Integer, nullable=False)
    completion_tokens = Column(Integer, nullable=False)
    total_tokens = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), index=True)
```

#### 2.2 捕获实现

改造 `chat_completion()` 签名，增加可选的 `agent_name` 和 `user_id` 参数：

```python
async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    provider: Optional[str] = None,
    # 新增：用于 token 统计的元数据
    agent_name: str = "",
    user_id: str = "",
) -> str:
```

在返回前异步写入 token 记录：

```python
if response.usage and user_id:
    # 使用 background task 异步写入，不阻塞主流程
    asyncio.create_task(_record_token_usage(
        user_id=user_id,
        agent_name=agent_name,
        provider=provider,
        model=model,
        usage=response.usage,
    ))
```

#### 2.3 查询能力

有了数据库记录后，可以支持：

```sql
-- 按用户聚合
SELECT user_id, SUM(total_tokens) as total, COUNT(*) as calls
FROM token_usage
WHERE created_at > NOW() - INTERVAL '7 days'
GROUP BY user_id ORDER BY total DESC;

-- 按 Agent 聚合（定位高消耗节点）
SELECT agent_name, SUM(total_tokens) as total, AVG(total_tokens) as avg_per_call
FROM token_usage
GROUP BY agent_name ORDER BY total DESC;

-- 按模型聚合（成本归因）
SELECT model, SUM(prompt_tokens) as prompt, SUM(completion_tokens) as completion
FROM token_usage
GROUP BY model;
```

**优势：**
- 支持多维度实时查询和聚合
- 可按用户/会话/Agent 分析用量分布
- 为成本核算和预算控制打基础

**劣势：**
- 需要数据库迁移（新增表）
- 每次 LLM 调用多一次 DB 写入（可异步化降低影响）
- 流式调用需要延后写入（流结束后才能拿到 usage）

---

### 方案三：全链路 — 融入 AgentState + 前端展示

在方案二基础上，将 token 统计融入 LangGraph 的 `AgentState`，在每个 Agent 节点执行后将 token 用量累积到 state 中，最终在 `recommend_agent` 汇总并通过 API 返回给前端展示。

**AgentState 扩展：**

```python
class AgentState(TypedDict):
    # ... 现有字段 ...
    token_usage: list[dict]        # 每次 LLM 调用的 token 记录
    total_prompt_tokens: int        # 累计输入 token
    total_completion_tokens: int    # 累计输出 token
```

**前端展示：** 在生成结果页或对话页底部展示"本次消耗 token 数"。

**优势：**
- 用户可感知，提升透明度
- 为按用户配额控制打基础

**劣势：**
- 改动面大，涉及 Agent、State、API、前端
- 流式调用的 usage 延后拿到，state 需在流结束后更新

---

## Token 估算：API 不返回 usage 时的回退方案

某些 provider 或场景下，API 响应可能不包含 `usage` 字段。此时需要回退到客户端估算。

### 输入 token 估算

```python
def estimate_input_tokens(messages: list[dict]) -> int:
    """基于消息列表估算输入 token 数。"""
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            # 多模态消息
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    total += estimate_tokens(part.get("text", ""))
    return total
```

### 输出 token 估算

输出 token 的精确估算较困难（只能在生成后统计）。简单做法：

- 非流式：`estimate_tokens(response_text)`
- 流式：在流结束后统计累积的 `full_response_text`

### 现有 `estimate_tokens()` 的精度

项目已有的 `chat_history.py:estimate_tokens()` 使用字符比率法：
- 中文字符 / 1.5 ≈ token 数
- 英文字符 / 4.0 ≈ token 数

精度约为 **±20%**（实际 tokenization 取决于模型的分词器）。对于成本估算可接受，但不适合精确计费。

更精确的方案：使用 `tiktoken` 库（OpenAI 开源），按模型选择对应的编码器（如 `cl100k_base` 用于 GPT-4）。

---

## 流式调用的特殊处理

流式调用中 token usage 的获取方式因 provider 而异：

| Provider | usage 获取方式 |
|----------|---------------|
| OpenAI | 最后一个 chunk 的 `chunk.usage` |
| DeepSeek | 与 OpenAI 兼容 |
| DashScope (qwen) | `stream.response.headers["x-dashscope-usage"]` (JSON 字符串，需解析) |
| Spark | 最后一个 chunk 的 `chunk.usage` |

**推荐做法：** 在 `stream_chat_completion()` 中：

```python
async def stream_chat_completion(...) -> AsyncGenerator[str, None]:
    # ... 现有逻辑 ...
    full_response = ""
    final_usage = None

    async for chunk in stream:
        # 尝试捕获 usage
        if hasattr(chunk, 'usage') and chunk.usage:
            final_usage = chunk.usage

        if chunk.choices and chunk.choices[0].delta.content:
            content = chunk.choices[0].delta.content
            full_response += content
            yield content

    # 流结束后记录 token
    if final_usage:
        logger.info("[LLM] token_usage | ...", ...)
    elif full_response:
        # 回退：provider 未返回 usage，使用估算
        estimated = estimate_tokens("".join(
            msg["content"] for msg in messages if isinstance(msg.get("content"), str)
        )) + estimate_tokens(full_response)
        logger.info("[LLM] token_usage (estimated) | total_estimate={}", estimated)
```

---

## 成本核算

有了 token 统计后，可进一步对接各 provider 的定价做成本核算。

### 当前 provider 定价参考（2026 年）

| Provider | 模型 | 输入价格 (¥/1M tokens) | 输出价格 (¥/1M tokens) |
|----------|------|----------------------|------------------------|
| 阿里 DashScope | kimi-k2.6 | 按 DashScope 计费 | 按 DashScope 计费 |
| DeepSeek | deepseek-chat | ¥1 | ¥2 |
| 阿里 DashScope | qwen3.6-plus | ¥2 | ¥6 |
| OpenAI | gpt-4o-mini | $0.15 | $0.60 |

### 配置化定价

```yaml
# configs/config.yaml 新增
llm:
  pricing:  # 单位：元 / 1M tokens
    kimi-k2.6:
      input:  4.0
      output: 12.0
    deepseek-chat:
      input:  1.0
      output: 2.0
    qwen3.6-plus:
      input:  2.0
      output: 6.0
    gpt-4o-mini:
      input:  1.1   # $0.15 ≈ ¥1.1
      output: 4.4   # $0.60 ≈ ¥4.4
```

### 成本计算公式

```python
def calculate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = config.llm.pricing.get(model, {})
    input_price = pricing.get("input", 0)
    output_price = pricing.get("output", 0)
    return (prompt_tokens / 1_000_000) * input_price + \
           (completion_tokens / 1_000_000) * output_price
```

---

## 推荐实施路径

| 阶段 | 内容 | 改动范围 | 价值 |
|------|------|---------|------|
| **Phase 1** | 方案一：日志记录 token | 仅 `llm.py`，~20 行 | 立即可用，摸清用量基线 |
| **Phase 2** | 方案二：DB 持久化 + 简单查询 API | `llm.py` + 新增 migration + model + CRUD | 多维度分析，成本归因 |
| **Phase 3** | 流式 token 统计 + tiktoken 精确估算 | `llm.py` | 覆盖全场景 |
| **Phase 4** | 方案三：前端展示 + 成本核算 | Agent + API + 前端 + config | 用户可见，预算管控 |

### Phase 2 的具体改动清单

1. **新增 migration** — 创建 `token_usage` 表（含 `user_id`, `session_id`, `agent_name`, `provider`, `model`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `created_at`）
2. **新增 ORM 模型** — `backend/db/models.py` 添加 `TokenUsage`
3. **修改 `chat_completion()`** — 增加 `agent_name`、`user_id` 可选参数，调用后记录 token
4. **修改 `stream_chat_completion()`** — 同上，在流结束后记录
5. **修改 `get_embedding()` / `get_embeddings_batch()`** — 记录 embedding token
6. **各 Agent 传参** — 逐个 Agent 在调用 `chat_completion()` 时传入 `agent_name` 和 `user_id`
7. **新增统计 API** — `GET /api/stats/tokens?user_id=xxx&days=7` 返回聚合数据

---

## 注意事项

1. **异步写入不能丢**：token 记录写入失败不应影响主流程（LLM 响应已返回给用户）。使用 `asyncio.create_task()` 或后台队列，写入失败只记 WARNING 日志。

2. **高并发下的写入压力**：如果一个资源生成触发 15 次 LLM 调用，并发 10 个用户就是 150 次 DB 写入/秒。建议批量写入（攒一批后 `insertmany`）或使用 PostgreSQL `COPY`。

3. **隐私合规**：token 记录表包含 `user_id`，属于用户行为数据。如涉及数据合规要求，需考虑脱敏和定期清理策略。

4. **流式调用中的 usage 延迟**：一个流式调用可能持续 10-30 秒，usage 在流结束后才能拿到。设计 state 更新逻辑时需注意时序。

5. **不要用 token 统计做实时计费**：API 返回的 token 数有时与计费 token 数有差异（如 prompt caching 折扣、特殊 token 处理）。API 返回的 usage 适合做用量分析和成本估算，不适合做精确计费。
