# JSON Schema 约束 LLM 输出可行性分析

## 1. 背景

当前项目通过 **prompt 自然语言描述** 来约束 11 个 LangGraph Agent 的输出格式，再通过 `safe_json_loads()` 多策略解析原始文本。这种方式有两个痛点：

- **无 API 级保证**：LLM 仍可能输出非法 JSON、插入前言后语、遗漏字段
- **解析成本高**：`backend/agents/utils.py:75-166` 维护了 6 层回退策略（LaTeX 修复 → 拼接对象解码 → JSON 块提取 → 截断修复 → `ast.literal_eval`）

但实际生产中偶发的解析失败仍会导致 Agent 节点报错回退。

## 2. 可行方案概览

| 方案 | 需要改 API 参数 | 需要换模型 | 约束强度 | 可行性 |
|------|:-:|:-:|:-:|:-:|
| A. `response_format: json_object` | 是 | 否 | 弱（仅保证合法 JSON） | **高** |
| B. `response_format: json_schema` | 是 | 是（需 OpenAI） | 强（字段类型/必填验证） | **低** |
| C. Tool Calling（function calling） | 是 | 否 | 强 | **中** |
| D. Pydantic 后置校验 | 否 | 否 | 中 | **高** |
| E. LangGraph `with_structured_output()` | 是 | 否 | 中-强 | **中** |

---

## 3. 各方案详细分析

### 3.1 方案 A：`response_format={"type": "json_object"}`

**原理**：OpenAI 兼容 API 的参数，要求 LLM 输出合法 JSON 字符串。

**当前模型支持情况**：

| 模型 | 支持 | 接口 |
|------|:-:|------|
| qwen3.6-flash（当前） | 支持 | DashScope OpenAI 兼容接口 |
| deepseek-chat | 支持 | `response_format={"type": "json_object"}` |
| gpt-4o-mini | 支持 | 同上 |
| spark generalv3.5 | 部分支持 | 需验证 |

**改动点**：
1. `backend/services/llm.py:113` — `chat_completion()` 增加 `response_format` 参数
2. `backend/services/llm.py:145` — `stream_chat_completion()` 同样增加
3. 各 Agent 调用 `chat_completion()` 时传入 `response_format={"type": "json_object"}`（仅 JSON 输出型 Agent）
4. 所有 system prompt 中需包含 `"json"` 关键词（API 要求）

**优点**：
- 改动量最小，核心改动仅 1 个文件（`llm.py`）
- 当前模型 qwen3.6-flash 原生支持
- 从 API 层面杜绝非 JSON 输出
- `chat_completion()` 的公开接口不受影响（新增可选参数，向后兼容）

**缺点**：
- 仅保证输出是合法 JSON，**不保证字段名、类型、必填字段完整**
- 仍需 `json.loads()` 解析，只是不再需要 `safe_json_loads()` 的 6 层回退
- 文本输出型 Agent（doc/summary/code/clarify）不适用

**结论：可行，改动最小，建议立即采用。**

---

### 3.2 方案 B：`response_format={"type": "json_schema", ...}`

**原理**：OpenAI 的结构化输出（Structured Outputs）特性，传入 JSON Schema 定义，API 保证输出严格符合 schema。

**关键限制**：这是 OpenAI 的**专有特性**，后端由 `gpt-4o-2024-08-06+` 支持。DashScope（阿里云）和 DeepSeek 的 API **均不支持** `json_schema` 类型。

| 模型 | `json_schema` 支持 |
|------|:-:|
| gpt-4o-mini / gpt-4o | 支持 |
| qwen3.6-flash | **不支持** |
| deepseek-chat | **不支持** |
| spark generalv3.5 | **不支持** |

**结论：不可行。** 除非切换 LLM provider 到 OpenAI，但这牵涉成本、（跨境）延迟、合规等全局性问题，不在本次讨论范围。

---

### 3.3 方案 C：Tool Calling（Function Calling）

**原理**：定义一个 `function`/`tool` 描述 JSON Schema，LLM 返回结构化的 function call 而非自由文本。这不是 MCP 协议，而是 OpenAI 兼容 API 的 `tools` 参数。

```python
# 示例
tools = [{
    "type": "function",
    "function": {
        "name": "output_profile",
        "description": "返回学生画像提取结果",
        "parameters": {
            "type": "object",
            "properties": {
                "major": {"type": "string", "description": "学生专业"},
                "learning_goal": {"type": "string", "description": "学习目标"},
                "level": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]}
            },
            "required": ["major", "learning_goal", "level"]
        }
    }
}]
```

**当前模型支持情况**：

| 模型 | Tool Calling 支持 |
|------|:-:|
| qwen3.6-flash | 支持（OpenAI 兼容格式） |
| deepseek-chat | 支持 |
| gpt-4o-mini | 支持 |

**改动点**：
1. `backend/services/llm.py` — `chat_completion()` 增加 `tools` 参数，返回增加 `tool_calls` 解析
2. `backend/models/schemas.py` — 为每个 Agent 的输出定义 Pydantic schema，生成 `tools` 参数
3. 各 Agent 调用方式 — 从 `chat_completion(messages)` 改为 `chat_completion(messages, tools=[...], tool_choice="required")`
4. 输出解析 — 从 `parse_json_llm_response(raw)` 改为解析 `tool_calls[0].function.arguments`

**优点**：
- Qwen3 原生支持，API 兼容性好
- Schema 约束完整，保证字段名、类型、枚举值
- 天然支持 required 字段标记
- 相比方案 A，不仅保证 JSON，还保证结构

**缺点**：
- **改动量大**：影响 `llm.py` + 所有 JSON 型 Agent（至少 9 个 Agent）+ prompts.yaml
- **Agent 架构变更**：需区分 "输出型" 和 "对话型" 调用路径
- **流式输出复杂**：`stream_chat_completion()` 的 tool_calls 增量流需要累积拼接
- **Qwen tool calling 稳定性**：阿里云合规模式下 tool calling 的流式行为需实测验证
- system prompt 语义变化：从"按此格式输出 JSON"变为"调用 output_xxx 函数"

**结论：技术可行但不推荐全量改造。** 成本高、风险大，且 Qwen tool calling 的稳定性需先做专项验证。

---

### 3.4 方案 D：Pydantic 后置校验（增强现有流程）

**原理**：不改变 LLM 调用方式，在现有 `json.loads()` 之后增加 Pydantic **校验层**。

```python
from pydantic import BaseModel, ValidationError

class ProfileOutput(BaseModel):
    major: str
    learning_goal: str
    level: str

# 现有流程：
raw = await chat_completion(messages)
parsed = json.loads(clean_json(raw))

# 增加校验：
try:
    result = ProfileOutput.model_validate(parsed)
except ValidationError as e:
    # 记录异常 → 触发重试或降级
    logger.warning("[ProfileAgent] schema validation failed: {}", e)
    # 可触发 LLM 重试（附带错误信息）
```

**改动点**：
1. `backend/models/schemas.py` — 新增各 Agent 的输出 Schema 模型（Pydantic v2）
2. 各 Agent — 在 `json.loads()` 后增加 `model_validate()` 调用
3. 可选：校验失败时触发重试（将错误描述作为 user message 回传 LLM）

**优点**：
- **零 API 改动**，不改 `llm.py`
- **渐进式**，可按 Agent 逐个接入
- 提供精确的错误定位："缺少 required 字段 `kp_id`" vs 当前"JSON 解析失败"
- 不依赖模型特性，所有 provider 通用
- 可以与方案 A 叠加使用

**缺点**：
- 不减少 LLM 输出非法 JSON 的概率，只是更快/更精确地发现
- 需要额外维护 schema
- 校验失败的恢复策略（重试/降级）需设计

**结论：推荐作为基础层方案，与方案 A 叠加效果最佳。**

---

### 3.5 方案 E：LangGraph `with_structured_output()`

**原理**：LangChain 提供 `ChatModel.with_structured_output(schema)` 方法，自动选择底层实现（优先 tool calling，降级 JSON mode）。

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="qwen3.6-flash", base_url="...")
structured_llm = llm.with_structured_output(ProfileOutput)
result: ProfileOutput = await structured_llm.ainvoke(messages)
```

**改动点**：
1. 引入 `langchain-openai` 依赖
2. 重构 `backend/services/llm.py` 或新增 LangChain LLM 封装
3. 各 Agent 改用 LangChain 的 ChatModel 接口
4. 流式输出需适配

**优点**：
- 自动选择最佳底层实现
- 返回 Pydantic 对象，无需手动解析

**缺点**：
- **引入新依赖**（langchain-openai），增加项目复杂度
- LangChain 封装层可能跟 Qwen 的兼容模式产生摩擦
- `enable_thinking` 等 Qwen 特有参数的传递路径不明确
- 项目当前是"裸 FastAPI + 原生 OpenAI SDK"极简架构，引入 LangChain 只为一个功能性价比低

**结论：不推荐。** 引入重量级依赖解决一个相对小的问题，不符合项目的极简架构路线。

---

## 4. 综合推荐方案

### 推荐：A + D 组合（JSON Mode + Pydantic 校验）

```
LLM API 调用                     输出校验
┌──────────────┐     json     ┌──────────────┐
│ response_format │ ────────→ │ Pydantic      │
│ = json_object   │           │ model_validate│
└──────────────┘              └──────┬───────┘
                                     │
                              ┌──────▼───────┐
                              │ ✅ 通过 → 返回│
                              │ ❌ 失败 → 重试│
                              └──────────────┘
```

### 4.1 实施路径

**第一阶段：方案 A（核心改动，1 个文件）**

`backend/services/llm.py` 的 `chat_completion()` 增加 `response_format` 参数：

```python
async def chat_completion(
    messages: list[dict],
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int | None = None,
    provider: Optional[str] = None,
    response_format: Optional[dict] = None,  # 新增
) -> str:
    ...
    kwargs = {}
    if response_format is not None:
        kwargs["response_format"] = response_format
    if _extra is not None:
        kwargs["extra_body"] = _extra

    response = await client.chat.completions.create(
        model=_model,
        messages=messages,
        temperature=temperature,
        max_tokens=_max_tokens,
        **kwargs,
    )
```

各 JSON 型 Agent 调用时传入：
```python
raw = await chat_completion(messages, response_format={"type": "json_object"})
```

**注意**：system prompt 中需包含 `"json"` 关键词（这是 `json_object` 模式的 API 要求），检查 `configs/prompts.yaml` 中各 Agent prompt 是否满足。

文本型 Agent（doc/summary/code/clarify）不传此参数，行为不变。

**第二阶段：方案 D（渐进式，各 Agent 独立）**

为每个 JSON 型 Agent 在 `backend/models/schemas.py` 中新增输出 Schema：

```python
class PlannerOutput(BaseModel):
    resource_type: str
    kp_id: str | None = None
    extra_types: list[str] = []

class SafetyOutput(BaseModel):
    passed: bool
    issues: list[str] = []

class ProfileExtractOutput(BaseModel):
    major: str | None = None
    learning_goal: str | None = None
    level: str | None = None
    ...
```

Agent 解析逻辑变为：
```python
try:
    result = PlannerOutput.model_validate(parsed)
except ValidationError as e:
    logger.warning("[PlannerAgent] schema validation failed: {}", e)
    # 可选：带错误信息重试 LLM
    retry_msg = f"上次输出不符合 schema：{e}，请严格按照 JSON 格式重新输出"
    raw = await chat_completion(
        messages + [{"role": "user", "content": retry_msg}],
        response_format={"type": "json_object"},
    )
    parsed = json.loads(raw)
    result = PlannerOutput.model_validate(parsed)
```

### 4.2 风险与缓解

| 风险 | 缓解措施 |
|------|---------|
| qwen3.6-flash 的 `json_object` 实现有边界情况 | 保留 `safe_json_loads()` 作为回退，新老双轨运行 |
| `json_object` 模式下 LLM 仍输出空 JSON `{}` | Pydantic 校验会捕获，触发重试 |
| 包含 `"json"` 关键词的 prompt 自动触发 json_object 模式 | 各 Agent prompt 已包含"JSON"字样，天然满足 |
| 流式场景 `stream=True` + `response_format` 兼容性 | Qwen3 支持，但需实测 `stream_chat_completion()` |

---

## 5. 方案 C 备选分析：Tool Calling 的有限应用

虽然全量改造不推荐，但 **Tool Calling 可以在特定 Agent 中试点**。最合适的试点场景：

**`planner_agent`（意图分类）**：当前输出 `{"resource_type": "doc", "kp_id": "...", "extra_types": []}`。resource_type 有明确的枚举值（doc/mindmap/quiz/code/summary/kg/clarify）。用 tool calling 约束 `resource_type` 为 enum，可以根治分类错误。

**`safety_agent`（安全审核）**：当前输出 `{"passed": bool, "issues": [...]}`。结构极简，适合验证 tool calling 的稳定性。

建议：先完成 A+D 组合，在长期运行稳定后，选择 1-2 个 Agent 试点方案 C，对比解析成功率。

---

## 6. 五种方案对比总结

| 维度 | A. json_object | B. json_schema | C. Tool Calling | D. Pydantic 校验 | E. LangGraph |
|------|:-:|:-:|:-:|:-:|:-:|
| 改动文件数 | 1 | N/A | 10+ | 10+ | 5+ |
| 需换模型 | 否 | 是（OpenAI） | 否 | 否 | 否 |
| Schema 约束 | 弱 | 强 | 强 | 中 | 中-强 |
| 流式兼容 | 需验证 | N/A | 复杂 | 无影响 | 需验证 |
| 新增依赖 | 无 | N/A | 无 | 无 | langchain-openai |
| 向后兼容 | 完全 | N/A | 较大变更 | 完全 | 中等变更 |
| 实施风险 | 低 | N/A | 中-高 | 低 | 中 |

**最终建议**：立即采用 **A + D 组合**，不做模型替换，不引入新依赖，改动量小且可渐进推进。
