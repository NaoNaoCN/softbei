# safety_agent

# SafetyAgent - 内容安全审核智能体

## 概述

SafetyAgent 是内容质量把关节点，负责对生成的内容进行安全审核，过滤幻觉和不当内容，并附加引用来源。它是一位内容质量审核专家，确保最终输出的内容准确、可信、适合学习场景。

## 核心职责

1. **内容对比** - 将 `draft_content` 与 `retrieved_docs` 进行对比
2. **质量审核** - 调用 LLM 检查内容的准确性和适切性
3. **修正或放行** - 若不通过，生成修正后的内容；若通过，保留原内容
4. **异常兜底** - LLM 调用失败时保守通过，不中断流程

## System Prompt

```
你是一位内容质量审核专家。
请对以下 AI 生成内容进行审核：

【参考资料（来源真实）】
{context}

【待审核内容】
{draft}

请检查：
1. 内容是否与参考资料一致（无捏造事实）
2. 是否存在明显错误或误导性表达
3. 内容是否适合学习场景

以 JSON 返回：
{
  "passed": true/false,
  "issues": ["问题1", "问题2"],
  "revised_content": "修正后内容（若 passed=false）或 null"
}
```

## 输入与输出

### 输入（AgentState）

| 字段 | 说明 |
| --- | --- |
| `draft_content` | 待审核的生成内容 |
| `retrieved_docs` | 参考文档列表 |
| `metadata` | 现有元数据（用于存储 `safety_issues`） |

### 输出（AgentState 更新）

| 字段 | 说明 |
| --- | --- |
| `safety_passed` | 审核是否通过（bool） |
| `final_content` | **始终等于 `draft_content`**（不再修正） |
| `metadata["safety_issues"]` | 审核未通过时的问题列表 |

## 审核判定规则

| 条件 | 结果 |
| --- | --- |
| 内容与参考资料一致，无明显错误 | `passed=true` |
| 存在捏造事实或严重错误 | `passed=false`，写入 `safety_issues` |
| 内容不适合学习场景 | `passed=false`，写入 `safety_issues` |
| LLM 调用失败 / JSON 解析失败 | 保守通过（`passed=true`），不阻断流程 |

## 跳过条件（should_skip_safety）

若 `draft_content` 为空，则跳过安全检查，直接进入下一节点。

## 执行流程

```

1. **跳过检查：**
    ◦ 若 `state.draft_content` 为空 → 记录日志，写入 `safety_passed=True` + `final_content=""`，直接返回
2. **记录日志：**打印 `draft_len`
3. **构造审核输入：**
    ◦ 取前 3 条参考资料（`retrieved_docs[:3]`）
    ◦ 只取 draft 前 500 字（`draft_preview = draft_content[:500]`）
    ◦ 若无参考资料，context = `"（无参考资料）"`
4. **调用 LLM 审核：**
    ◦ 填充 SYSTEM_PROMPT（`context` + `draft_preview`）
    ◦ `temperature=0.1`（低随机性，保证审核一致性）
    ◦ `max_tokens=300`（只需返回 passed + issues，节省 token）
5. **处理 Markdown 代码块包裹的 JSON**
6. **解析审核结果：**
    ◦ `passed = result.get("passed", True)`（默认通过）
    ◦ `issues = result.get("issues", [])`
    ◦ 记录日志：`passed` + `issues`
7. **统一保留原始内容：**
    ◦ 无论是否通过，`final_content` 始终 = `draft_content`
    ◦ 写入 `safety_passed`
    ◦ 若未通过且有 issues → 写入 `metadata["safety_issues"]`
8. **异常兜底：**
    ◦ JSONDecodeError → 记录 warning + raw_preview，保守通过
    ◦ 其他异常 → 记录 info，保守通过
```

## 依赖关系

- **上游**：doc_agent / mindmap_agent / quiz_agent / code_agent / summary_agent
- **下游**：RecommendAgent

## 文件位置

`backend/agents/safety_agent.py`