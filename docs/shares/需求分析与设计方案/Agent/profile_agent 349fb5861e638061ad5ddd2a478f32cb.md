# profile_agent

# **ProfileAgent - 学生画像智能体**

## **概述**

ProfileAgent 负责从学生的对话中提取和更新学生画像信息，判断画像完整性，决定是否放行到 PlannerAgent。它是一位学生画像分析助手，能够从学生的自我描述或对话内容中，自动识别并提取学习相关的特征信息。

## **核心职责**

1. **信息提取** - 调用 LLM 分析 `user_message`，提取画像字段
2. **画像更新** - 调用 `profile_service.merge_chat_updates` 更新数据库 **（增量叠加策略）**
3. **状态同步** - 将最新 profile 写回 `state.profile`
4. **意图判断** - 区分资源请求 vs 纯自我介绍
5. **文档上传引导** - 首次画像完整但无教材时，引导用户上传 PDF
6. **多场景澄清** - 画像不足/纯自我介绍/无文档 等不同场景生成差异化追问

## **System Prompt**

### 1.画像提取 **Prompt**

```
    你是一个学生画像分析助手。从学生的消息中提取以下字段，以 JSON 格式返回，无法提取的字段设为 null：
    {  
       "major": "学生专业",  
       "learning_goal": "学习目标",  
       "cognitive_style": "visual|text|practice",  
       "daily_time_minutes": 整数,  
       "knowledge_mastered": ["已掌握知识点"],  
       "knowledge_weak": ["薄弱知识点"],  
       "error_prone": ["容易出错的知识点"],  
       "current_progress": "当前学习进度描述"
    }
    只返回 JSON，不要包含其他内容。
```

### **2. 意图判断 Prompt**

```
判断学生消息是否包含"想要学习某个具体知识点或请求生成学习资源"的意图。只回答 yes 或 no。
```

### **3. 画像初始化追问 Prompt**

```
你是一个友好的学习助手，正在帮助新用户建立学习画像。当前已知画像信息：{known_fields}还缺少的关键信息：{missing_fields}请用自然、友好的语气，针对缺失信息提出 1-2 个问题，引导用户补充。不要列清单，像朋友聊天一样。
```

### **4. 资源请求但画像不足追问 Prompt**

```
用户想要学习"{topic}"，但我还需要了解更多信息才能生成个性化资源。当前已知画像：{known_fields}缺少的必要信息：{missing_fields}请用自然语气，在提到"我来帮你生成资料"的同时，追问缺失的信息。控制在 2-3 句话内。
```

### **5. 画像完整但无文档引导 Prompt**

```
你是一个友好的学习助手。用户刚完成了学习画像的建立。当前画像信息：{known_fields}用户的学习目标：{learning_goal}但用户还没有上传任何课程教材（PDF）。请：1. 先简要确认已记录的画像信息2. 建议用户到「资源库」页面上传相关课程教材 PDF，这样可以基于教材生成更精准的个性化资源3. 同时告知用户也可以直接请求生成资源，系统会用通用知识来生成语气友好自然，控制在 3-4 句话内。
```

### **6. 画像完整、纯自我介绍确认 Prompt**

```
你是一个友好的学习助手。用户刚完成了学习画像的建立，但没有明确请求生成学习资源。当前画像信息：{known_fields}用户还没有上传任何课程教材。请：1. 简要确认已记录的画像信息（1-2句话概括）2. 建议用户到「资源库」页面上传课程教材 PDF，这样能生成更精准的个性化资源3. 告知用户也可以直接请求生成资源（如"帮我生成卷积的学习资料"），系统会用通用知识来生成语气友好自然，控制在 3-4 句话内。
```

## **输入与输出**

### **输入（AgentState）**

| 字段 | 说明 |
| --- | --- |
| `user_id` | 用户 UUID |
| `user_message` | 用户输入的对话内容 |
| `chat_history` | 多轮对话历史（注入到 LLM 帮助理解上下文） |
| `profile` | 已有画像（用于增量合并） |

### **输出（AgentState 更新）**

| 字段 | 说明 |
| --- | --- |
| `profile` | 更新后的 StudentProfileOut |
| `profile_complete` | 画像是否完整（bool） |
| `clarify_message` | 追问/引导消息（画像不足或需引导时） |
| `final_content` | 最终返回给用户的消息内容 |

## **提取的画像字段**

| 字段 | 类型 | 说明 | 更新策略 |
| --- | --- | --- | --- |
| `major` | str | null | 学生专业 | 覆盖 |
| `learning_goal` | str | null | 学习目标 | **增量概括**（异步 LLM） |
| `cognitive_style` | CognitiveStyle | null | 认知风格（视觉型/阅读型/动手型） | 覆盖 |
| `daily_time_minutes` | int | null | 每日学习时间（分钟） | 覆盖 |
| `knowledge_mastered` | list[str] | 已掌握知识点 | **增量叠加**（去重保序） |
| `knowledge_weak` | list[str] | 薄弱知识点 | **增量叠加**（去重保序） |
| `error_prone` | list[str] | 易错知识点 | **增量叠加**（去重保序） |
| `current_progress` | str | null | 当前学习进度 | 覆盖 |

## **路由判断（route_after_profile）**

判断是否需要放行到 planner_agent：

| 条件 | 路由目标 |
| --- | --- |
| `profile_complete == True` | `planner_agent` |
| `profile_complete == False` |  `END`（追问/引导，本轮结束） |

**画像完整性判断标准**：`learning_goal` 或 `knowledge_weak` 或 `knowledge_mastered` 至少有一个非空。

## **执行流程**

1. **提取画像字段**：
    - 构造 System Prompt（`_EXTRACT_PROMPT`）
    - 注入 `chat_history`，帮助理解上下文
    - 注入 `user_message`
    - 调用 LLM（`temperature=0.1`）提取 JSON
    - 防御：LLM 返回 null/非 dict 时归一为 `{}`
    - 异常时 fallback `{}`
2. **合并到数据库**：
    - 调用 `profile_svc.merge_chat_updates(user_id, updates, db, user_message)`
    - 增量叠加策略：三类知识点（mastered/weak/error_prone）去重保序追加
    - learning_goal 异步概括：DB 写完后 BackgroundTasks 异步 LLM 概括
    - DB 失败回退：异常时回退到 `_merge_profile_in_memory`
3. **判断消息意图**：
    - 调用意图判断 LLM（`_INTENT_PROMPT`）
    - 注入 `chat_history`，帮助理解指代
    - 返回 `is_resource_request`（yes/no）
4. **判断画像完整性**：
    - 调用 `_check_profile_complete(state)`
    - 写入 `state.profile_complete`
5. **场景 1：画像完整 + 有资源请求 + 无文档 + 首次画像**：
    - 检查用户是否有已上传文档（`_check_user_has_documents`）
    - 若无文档且 `version==1`，生成引导上传消息
    - 写入 `clarify_message` + `final_content`，`profile_complete=False`，直接返回
6. **场景 2：画像完整 + 无资源请求（纯自我介绍）**：
    - 检查用户是否有已上传文档
    - 无文档 → 确认画像 + 引导上传
    - 有文档 → 确认画像 + 提示可请求资源
    - 写入 `clarify_message` + `final_content`，`profile_complete=False`，直接返回
7. **场景 3：画像不完整**：
    - 计算缺失字段（学习目标/知识基础/学习偏好）
    - 区分资源请求 vs 纯初始化，使用不同 Prompt
    - 注入 `chat_history`，让追问更自然连贯
    - 生成 `clarify_message` + `final_content`

## **辅助函数**

### **`_check_user_has_documents(user_id) -> bool`**

检查用户是否在向量库中有已上传的文档。

- 查询 ChromaDB collection（`where={"user_id": user_id}, limit=1`）
- 返回是否有文档
- 向量库不可用时保守返回 `True`（不阻断流程）

### **`_profile_to_known_fields(profile) -> dict`**

将 StudentProfileOut 转为非空字段字典，用于 Prompt 填充。

### **`_merge_profile_in_memory(state, updates) > AgentState`**

DB 不可用时的内存级画像合并（回退方案）。

### **`_check_profile_complete(state) -> bool`**

判断画像是否满足资源生成的最小要求（learning_goal / knowledge_weak / knowledge_mastered 至少一个非空）。

## **依赖关系**

- **上游**：图的入口节点，无前置 Agent
- **下游**：
    - `profile_complete=True` → PlannerAgent（使用 profile 分析意图）
    - `profile_complete=False` → END（追问/引导，本轮结束）

## **文件位置**

`backend/agents/profile_agent.py`