# JSON 容错解析设计

> 最后更新：2026-06-10

本文档详解项目中的 `safe_json_loads()` 函数——它是所有 Agent 和 Judge 系统解析 LLM 输出的**唯一入口**，通过 5 层递进策略处理 LLM JSON 输出的各类格式问题。

实现在 `backend/agents/utils.py:75-160`。

---

## 1. 问题根源：LLM 的 JSON 输出为什么不可靠

LLM 输出的 JSON 天然存在四种"格式损坏"，原因各不相同：

| 问题类型 | 表现 | 根因 |
|---------|------|------|
| Markdown 代码块包裹 | ` ```json\n{...}\n``` ` | LLM 训练数据中 JSON 常被放在 Markdown 代码块里，模型习得了这个习惯 |
| LaTeX 反斜杠污染 | `"formula": "\frac{1}{2}"` | `\f` 在 JSON 中是合法的换页符，但 `\p`、`\d`、`\t` 后面的内容被 JSON 解析器拒绝 |
| 解释性文字干扰 | "好的，以下是生成的题目：\n{...}" | LLM 是对话模型，习惯在输出前加一句"人话"再给数据 |
| max_tokens 截断 | `{"questions": [{"id": 1, "text": "xxx` | 生成内容超过 max_tokens 上限时 API 在任意位置截断输出 |

这四种问题在项目中都会高频出现——因为有 7 个 Agent 和 4 个 Judge 依赖 LLM 返回结构化 JSON。如果每个调用方都自己处理，会是灾难级的代码重复和逻辑不一致。

---

## 2. 整体架构

```
输入: raw string (LLM 原始输出)
    │
    ├─ parse_json_llm_response()  ← 前处理：清洗 Markdown 代码块
    │
    ├─ 策略 1: json.loads() 直接解析
    │   └─ 成功 → return
    │
    ├─ 策略 2: 修复非法反斜杠 → json.loads()
    │   └─ 成功 → return
    │
    ├─ 策略 3: 提取 JSON 块 + 反斜杠修复 → json.loads()
    │   └─ 成功 → return
    │
    ├─ 策略 4: 截断修复 + 反斜杠修复 → json.loads()
    │   └─ 成功 → return
    │
    ├─ 策略 5: ast.literal_eval()
    │   └─ 成功 → return
    │
    └─ 全失败: logger.warning() + raise JSONDecodeError
```

**调用方感知**：无论经历了哪一层策略，调用方拿到的都是标准 Python dict/list，不需要关心内部修复过程。

---

## 3. 前处理：parse_json_llm_response()

```python
# backend/agents/utils.py:61-72
def parse_json_llm_response(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        cleaned = cleaned.rsplit("```", 1)[0].strip()
    return cleaned
```

处理 `` ```json ... ``` `` 包裹。设计上作为一个独立函数存在，因为它也被其他地方直接调用（如只需要去代码块但不需要完整容错解析的场景）。

---

## 4. 五层策略详解

### 4.1 策略 1：json.loads() 直接解析

```python
cleaned = parse_json_llm_response(raw)
try:
    return json.loads(cleaned)
except json.JSONDecodeError:
    pass
```

正常情况下，LLM 输出的 JSON 去掉代码块包裹后就是合法的。绝大多数请求（估计 80%+）在这一步就返回了，没有额外开销。

### 4.2 策略 2：反斜杠修复

```python
fixed = re.sub(
    r'\\(?!["\\/bfnrtu])(?![0-9A-Fa-f]{4})',
    r'\\\\',
    cleaned,
)
try:
    return json.loads(fixed)
except json.JSONDecodeError:
    pass
```

**核心正则释义**：

- `\\` — 匹配一个反斜杠
- `(?!["\\/bfnrtu])` — 负向前瞻：后面不能是合法的 JSON 转义字符（`"` `\` `/` `b` `f` `n` `r` `t`）
- `(?![0-9A-Fa-f]{4})` — 负向前瞻：后面不能是 4 位十六进制（Unicode 转义 `\uXXXX`）
- `r'\\\\'` — 替换为两个反斜杠（在 JSON 中表示一个字面反斜杠）

**具体例子**：

| LLM 输出 | 匹配的反斜杠 | 修复后 | JSON 解析结果 |
|----------|------------|--------|-------------|
| `"\frac{1}{2}"` | `\f`（后面是 `r`，不是合法转义） | `"\\frac{1}{2}"` | 字符串 `\frac{1}{2}` |
| `"\partial"` | `\p`（后面是 `a`，不是合法转义） | `"\\partial"` | 字符串 `\partial` |
| `"换行\n在这里"` | 不匹配（`\n` 是合法转义） | 不变 | 换行符正确保留 |
| `"\u0041"` | 不匹配（`\u` + 4 位 hex） | 不变 | 字符 `A` 正确保留 |

**为什么会产生这个问题**：LaTeX 命令（`\frac`、`\partial`、`\sum` 等）中的反斜杠，在 LLM 的"认知"中是数学符号的一部分。但 JSON 规范要求字符串中的 `\` 要么转义为 `\\`，要么是合法转义序列。LLM 在这两者之间频繁犯错。

### 4.3 策略 3：JSON 块提取

```python
extracted = _extract_json_block(cleaned)
if extracted:
    try:
        return json.loads(extracted)
    except json.JSONDecodeError:
        pass
    # 提取的块也尝试反斜杠修复
    fixed_extracted = re.sub(...)
    try:
        return json.loads(fixed_extracted)
    except json.JSONDecodeError:
        pass
```

`_extract_json_block()` 的实现（`backend/agents/utils.py:228-250`）：

```python
def _extract_json_block(text: str) -> str | None:
    start = text.find("{")
    if start >= 0:
        depth = 0
        in_string = False
        for i in range(start, len(text)):
            ch = text[i]
            if ch == '"' and (i == 0 or text[i - 1] != '\\'):
                in_string = not in_string
            if not in_string:
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return text[start:i + 1]
    # 同样逻辑处理数组 [...]
```

关键设计：
- **括号深度计数**：正确处理嵌套 `{}`，不会被内部的 `{` `}` 迷惑
- **in_string 状态追踪**：区分"字符串内的 `{`"和"真正的 JSON 结构括号"，避免字符串内容干扰括号匹配
- **支持对象和数组**：同时处理 `{...}` 和 `[...]`
- **提取后二次修复**：提取出的块仍可能含有反斜杠问题，再套一次策略 2

### 4.4 策略 4：截断修复

```python
repaired = _repair_truncated_json(cleaned)
if repaired != cleaned:
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass
    # 修复后也尝试反斜杠修复
    ...
```

`_repair_truncated_json()` 分三步（`backend/agents/utils.py:163-202`）：

**第 1 步 — 切除尾部不完整片段**：

```python
if _has_unclosed_string(stripped):
    last_complete = _find_last_complete_boundary(stripped)
    if last_complete > 0:
        stripped = stripped[:last_complete]
```

`_has_unclosed_string()` 遍历文本判断末尾是否有未闭合的双引号（奇数个未转义引号 = 字符串未关闭）。如果有，`_find_last_complete_boundary()` 找到最后一个完整的结构边界（`"` 闭合处或 `}` `]` 后），从那之后的内容全部切除。

**第 2 步 — 统计括号深度**：

```python
depth_brace = 0    # {}
depth_bracket = 0  # []
in_string = False

for i, ch in enumerate(stripped):
    if ch == '"' and (i == 0 or stripped[i-1] != '\\'):
        in_string = not in_string
    elif not in_string:
        if ch == '{':    depth_brace += 1
        elif ch == '}':  depth_brace -= 1
        elif ch == '[':  depth_bracket += 1
        elif ch == ']':  depth_bracket -= 1
```

遍历时同步追踪 `in_string` 状态，字符串内的括号不参与计数。最终得到两个值：`depth_brace`（未闭合的 `{` 数量）、`depth_bracket`（未闭合的 `[` 数量）。

**第 3 步 — 补全缺失的闭合符号**：

```python
result = stripped.rstrip(',\n\r\t ')   # 去掉尾部逗号（数组最后一项可能被截断）
result += ']' * max(0, depth_bracket)
result += '}' * max(0, depth_brace)
return result
```

**实例演示**：

```
输入：{"questions": [{"id": 1, "text": "什么是梯度下
      （max_tokens 在此处截断）

步骤 1: 末尾是 "什么是梯度下 —— 字符串未闭合
        → 找到上个完整边界：{"id": 1, 的 " 后
        → 切除为 {"questions": [{"id": 1,
步骤 2: 统计括号：{ ×2, } ×0, [ ×1, ] ×0
        depth_brace=2, depth_bracket=1
步骤 3: 补全 → {"questions": [{"id": 1,]}]
```

注意补全后的 JSON 可能仍不合法（如 `{"id": 1,}` 中多余的 `,` 已通过 `rstrip(',')` 处理），但大多数情况下能形成可解析的 JSON。如果补全后仍失败，策略 4 捕获异常继续。

### 4.5 策略 5：ast.literal_eval() 兜底

```python
try:
    import ast
    return ast.literal_eval(cleaned)
except (ValueError, SyntaxError):
    pass
```

部分 LLM 输出是 Python 风格的字面量而非严格的 JSON：

- `None` 而非 `null`
- `True` / `False` 而非 `true` / `false`
- 单引号字符串 `'hello'` 而非 `"hello"`
- 尾部逗号 `[1, 2, 3,]`（Python 允许，JSON 不允许）

`ast.literal_eval()` 可以解析 Python 字面量语法，作为最后一道兜底。

---

## 5. 全失败处理

```python
from loguru import logger
logger.warning(
    f"[safe_json_loads] 所有解析策略均失败，原始输出前 300 字符: {original[:300]!r}"
)
raise json.JSONDecodeError(
    f"safe_json_loads: unable to parse after all fix strategies",
    cleaned, 0
)
```

**设计考量**：

1. **记录日志但不吞异常**：日志记录了原始输出前 300 字符，方便事后排查 LLM 到底输出了什么。但异常仍然向上抛出——不替调用方做"默认为空"之类的决定。
2. **调用方的 fallback 各自处理**：
   - SafetyAgent → fail-open，默认 `passed=True`
   - ProfileAgent → 返回已有画像，不做增量合并
   - PlannerAgent → 回退到默认资源类型 `doc`
   - RecommendAgent → 回退到空推荐列表
   - Judge 系统 → 记录评估失败，本次采样作废

---

## 6. 调用方全景

`safe_json_loads()` 在项目中有 **10 处**调用，覆盖所有依赖 LLM JSON 输出的场景：

| 调用方 | 解析内容 | 失败 fallback |
|--------|---------|--------------|
| `safety_agent.py` | 审核结论 `{passed, issues}` | fail-open，默认通过 |
| `quiz_agent.py` | 题目 JSON 数组 | 返回错误信息给前端 |
| `profile_agent.py` | 画像提取 `{learning_goal, knowledge_weak, ...}` | 返回已有画像 |
| `planner_agent.py` | 资源分类 `{resource_type, kp_id}` | 回退到 doc 类型 |
| `recommend_agent.py` | 推荐列表 `[{kp_id, reason}]` | DB 硬过滤兜底 |
| `judge.py`（×7） | 4 项评估结果 × 多个 Judge | 记录评估失败 |

---

## 7. 设计原则总结

1. **逐级降级而非一步到位**：80% 的情况在策略 1 就过了，没有任何额外开销。后面的策略只在前面失败时才执行。这是一种"乐观解析"模式。

2. **每层独立、可组合**：每层策略解决一类问题——反斜杠修复不依赖块提取，截断修复不依赖反斜杠修复。层与层之间是 fallback 关系而非依赖关系。

3. **修复后交叉尝试**：策略 3 提取出 JSON 块后会再套一层反斜杠修复，策略 4 截断修复后也会再套一层反斜杠修复——因为 LLM 的输出往往是多种问题叠加。

4. **调用方无感知**：无论内部分几层修复，返回的都是标准 dict/list。调用方不需要写任何容错代码，直接 `.get()` 即可。

5. **不替调用方做决定**：全失败时抛异常而非返回空值。不同的调用场景失败后的正确行为不同（审核应该放行、题目应该报错），让调用方自己选择 fallback 策略。

---

> 文档版本：v1.0 | 最后更新：2026-06-10
