# system_prompt

# System Prompt 在 Agent 系统中的作用

## 概述

System Prompt（系统提示词）是整个 Agent 系统的核心组件，它定义了每个 LLM Agent 的角色身份、行为规范和输出格式。本文档详细说明 System Prompt 在各 Agent 中的具体作用、设计原则和实现机制。

## 什么是 System Prompt

System Prompt 是发送给大语言模型（LLM）的指令性文本，位于 `messages` 列表的首位，用于：

1. **定义 AI 角色** - 告诉 LLM 它扮演什么身份
2. **规定行为规范** - 说明它应该如何执行任务
3. **指定输出格式** - 明确返回内容的结构和格式要求
4. **提供上下文模板** - 预留占位符，运行时动态填充

## System Prompt 的结构

每个 Agent 的 System Prompt 通常包含以下部分：

```
┌─────────────────────────────────────────────┐
│ 角色定义                                    │
│ "你是一位XXX专家"                           │
├─────────────────────────────────────────────┤
│ 任务说明                                    │
│ "请根据...生成..."                          │
├─────────────────────────────────────────────┤
│ 格式要求                                    │
│ "以JSON格式返回：{...}"                     │
├─────────────────────────────────────────────┤
│ 约束条件                                    │
│ "不超过X层"、"必须基于参考资料"           │
├─────────────────────────────────────────────┤
│ 占位符                                     │
│ {context}、{kp_name}、{profile}            │
└─────────────────────────────────────────────┘
```

## 各 Agent 的 System Prompt 详解

### 1. ProfileAgent - 学生画像分析

**System Prompt 核心内容：**

```
你是一个学生画像分析助手。
你的任务是从学生的自我描述或对话中，提取以下信息并以 JSON 格式返回：
- major: 学生专业
- learning_goal: 学习目标
- cognitive_style: 认知风格（visual/text/practice）
- daily_time_minutes: 每日学习时间（分钟）
- knowledge_mastered: 已掌握的知识点列表
- knowledge_weak: 薄弱知识点列表
- error_prone: 容易出错的知识点列表
- current_progress: 当前学习进度描述

只返回 JSON，不要包含其他内容。
```

**作用：**
- 角色定位为”学生画像分析助手”
- 明确需要提取的 8 个字段
- 规定输出必须为纯 JSON，不含其他文本

**执行时的消息构造：**

```python
messages = [
    {"role": "system", "content": SYSTEM_PROMPT},
    {"role": "user", "content": state.user_message}
]
```

### 2. PlannerAgent - 意图分析与路由

**System Prompt 核心内容：**

```
你是一个学习计划分析助手。
根据学生的问题和画像，判断：
1. 学生想要生成什么类型的学习资源（doc/mindmap/quiz/code/summary）
2. 目标知识点 ID（从知识图谱节点中选择）

以 JSON 格式返回：{"resource_type": "...", "kp_id": "..."}
若无法判断，resource_type 设为 null。
```

**作用：**
- 将 LLM 作为”意图分类器”
- 根据用户消息和画像判断资源类型
- 同时完成知识点定位

**条件路由 `route_by_resource_type` 函数：**

```python
mapping = {
    ResourceType.doc: "doc_agent",
    ResourceType.mindmap: "mindmap_agent",
    ResourceType.quiz: "quiz_agent",
    ResourceType.code: "code_agent",
    ResourceType.summary: "summary_agent",
}
```

### 3. DocAgent - 学习文档生成

**System Prompt 核心内容：**

```
你是一位专业的教学资料撰写专家。
请根据提供的参考资料和知识点信息，生成一份结构清晰、内容准确的学习文档。
要求：
- 使用 Markdown 格式，包含标题、正文、例子和小结
- 内容必须基于参考资料，不得捏造
- 在引用参考资料时，以 [n] 形式标注来源编号
- 难度和深度适配学生当前画像
```

**作用：**
- 角色定位为”教学资料撰写专家”
- 要求输出 Markdown 格式
- 强调必须基于参考资料（防止幻觉）
- 要求标注来源（可追溯性）
- 要求适配学生画像（个性化）

### 4. MindmapAgent - 思维导图生成

**System Prompt 核心内容：**

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

层级深度：不超过 4 层，每节点子项不超过 6 个。
```

**作用：**
- 明确输出必须是”严格 JSON”
- 提供明确的树状结构模板
- 设定可视化约束（深度、宽度限制）

### 5. QuizAgent - 测验题目生成

**System Prompt 核心内容：**

```
你是一位出题专家。
请为以下知识点出 {count} 道题目，题型分布：
- 单选题（single）：{single_count} 道
- 多选题（multi）：{multi_count} 道
- 填空题（fill）：{fill_count} 道

以 JSON 数组返回，每道题格式：
{
  "question_type": "single/multi/fill",
  "difficulty": 1-5,
  "stem": "题干",
  "options": ["A. ...", "B. ..."],  // 填空题为 null
  "answer": "A" 或 ["A","C"] 或 "答案文本",
  "explanation": "解析"
}
```

**作用：**
- 角色定位为”出题专家”
- 动态填充题型数量（适配不同需求）
- 每道题包含 6 个字段（类型、难度、题干、选项、答案、解析）

### 6. CodeAgent - 代码示例生成

**System Prompt 核心内容：**

```
你是一位编程教学专家。
请为以下知识点生成一个代码示例或编程练习，要求：
- 使用 Python（除非学生有特殊要求）
- 代码包含详细注释
- 先给出题目描述，再给出参考答案
- 若是练习题，在答案前用 "# ===== 参考答案 =====" 分隔

以 Markdown 代码块格式输出。
```

**作用：**
- 角色定位为”编程教学专家”
- 规定使用 Python（除非特殊要求）
- 要求详细注释（便于学习）
- 分离题目和答案（支持练习场景）
- 规定 Markdown 代码块格式

### 7. SummaryAgent - 复习总结生成

**System Prompt 核心内容：**

```
你是一位学习总结专家。
请根据参考资料，为以下知识点生成一份简洁的复习总结，要求：
- 使用要点式 Markdown（无序列表 + 加粗重点词）
- 控制在 300-500 字以内
- 突出核心概念、常见误区和记忆技巧
- 若知识点有公式，用 LaTeX 格式列出
```

**作用：**
- 角色定位为”学习总结专家”
- 要求简洁（300-500 字）
- 要求要点式格式（便于快速浏览）
- 要求包含”常见误区”（针对薄弱点）
- 支持 LaTeX 公式（适合理工科）

### 8. SafetyAgent - 内容安全审核

**System Prompt 核心内容：**

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

**作用：**
- 角色定位为”内容质量审核专家”
- 对比”参考资料”与”生成内容”
- 检查三个维度：一致性、准确性、适切性
- 返回结构化审核结果（含修正内容）

### 9. RecommendAgent - 学习推荐

**System Prompt 核心内容：**

```
你是一位智能学习顾问。
根据学生的当前画像和已学知识点，从知识图谱中推荐 3-5 个下一步应学习的知识点。

学生画像：{profile}
已学知识点（已掌握）：{mastered}
薄弱知识点：{weak}
学习目标：{goal}

可选知识点（来自知识图谱）：{available_kps}

以 JSON 数组返回，每项包含：
{"kp_id": "...", "kp_name": "...", "reason": "推荐原因"}
```

**作用：**
- 角色定位为”智能学习顾问”
- 提供学生的完整画像上下文
- 结合知识图谱可选节点
- 要求包含推荐原因（可解释性）

## System Prompt 的执行机制

### 消息构造流程

```
1. 定义 SYSTEM_PROMPT（静态文本 + 动态占位符）
2. 运行时填充占位符：prompt = SYSTEM_PROMPT.format(context=..., kp_name=...)
3. 构造 messages 列表：
   messages = [
       {"role": "system", "content": prompt},
       {"role": "user", "content": user_message}
   ]
4. 调用 chat_completion(messages)
5. 解析返回的 JSON 结果
6. 更新 AgentState
```

### 占位符的使用

| 占位符 | 来源 | 说明 |
| --- | --- | --- |
| `{context}` | retrieved_docs 拼接 | 参考资料 |
| `{kp_name}` | kp_id 查询 | 知识点名称 |
| `{profile}` | state.profile | 学生画像 |
| `{count}` | 运行时计算 | 题目数量 |
| `{available_kps}` | kg_edge 查询 | 可选知识点 |

### 温度参数（Temperature）

不同 Agent 使用不同的 temperature 值：

| Agent | Temperature | 原因 |
| --- | --- | --- |
| ProfileAgent | 0.3 | 需要准确提取字段，低随机性 |
| PlannerAgent | - | 意图分类，低随机性 |
| DocAgent | - | 需要准确生成内容 |
| MindmapAgent | 0.5 | 结构化 JSON，中等创造性 |
| QuizAgent | 0.6 | 题目生成需要一定创造性 |
| CodeAgent | - | 代码生成，低随机性 |
| SummaryAgent | - | 要点总结，低随机性 |
| SafetyAgent | 0.1 | 审核，低随机性 |
| RecommendAgent | - | 推荐，低随机性 |

## System Prompt 的设计原则

### 1. 角色明确

每个 System Prompt 都以”你是…“开头明确定义角色身份，这有助于：
- 获得更符合专业场景的输出
- 统一输出风格和质量

### 2. 输出格式规范

使用 JSON 作为主要输出格式，因为：
- 易于程序解析
- 结构固定，便于验证
- 支持嵌套复杂数据

### 3. 约束具体化

避免模糊描述，使用具体约束：
- ❌ “不要太长”
- ✅ “控制在 300-500 字以内”

### 4. 防止幻觉

在生成类 Agent 中强调：
- “内容必须基于参考资料”
- “不得捏造”
- 参考资料作为输入的一部分

### 5. 适配个性化

在 DocAgent 和 QuizAgent 中加入：
- “适配学生当前画像”
- “结合已掌握/薄弱知识点”

## System Prompt 与 AgentState 的交互

```
┌─────────────────────────────────────────────────────────┐
│                    AgentState                           │
├─────────────────────────────────────────────────────────┤
│ user_id: str                                           │
│ session_id: str                                        │
│ user_message: str  ──────────┐                         │
│ profile: StudentProfileOut  ─┼──→ System Prompt 填充  │
│ kp_id: Optional[str]  ───────┼──→ {kp_name}            │
│ retrieved_docs: list[str] ───┴──→ {context}           │
│ draft_content: Optional[str] ←── 生成结果               │
│ final_content: Optional[str] ←── 审核后内容             │
└─────────────────────────────────────────────────────────┘
```

## 总结

System Prompt 是 Agent 系统的”灵魂”，它：

1. **连接架构与 AI 能力** - 将 LangGraph 的状态机设计转化为具体的 LLM 调用
2. **标准化输出** - 通过格式规范确保各 Agent 输出的一致性
3. **控制生成质量** - 通过约束条件防止低质量输出
4. **实现个性化** - 通过动态占位符实现上下文感知
5. **保障安全性** - 通过 SafetyAgent 的审核 prompt 确保内容合规

良好的 System Prompt 设计是构建可靠、可维护 Agent 系统的基础。