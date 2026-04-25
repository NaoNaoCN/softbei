# Agent 模块文档

**最后更新**: 2026-04-25

---

## 1. 架构概览

### 1.1 节点拓扑

```
profile_agent
  ├─ (画像不足) → END
  └─ (画像足够) → planner_agent
                    ↙  ↙  ↙  ↘  ↘
                doc mindmap quiz code summary
                    ↘  ↘  ↘  ↙  ↙
                     safety_agent
                          ↓
                   recommend_agent → END
```

### 1.2 Agent 列表

| Agent | 文件 | 职责 |
|-------|------|------|
| `profile_agent` | `profile_agent.py` | 从对话中提取/更新学生画像，判断是否追问 |
| `planner_agent` | `planner_agent.py` | 解析用户意图，确定资源类型和知识点 |
| `doc_agent` | `doc_agent.py` | 生成 Markdown 格式学习文档 |
| `mindmap_agent` | `mindmap_agent.py` | 生成 ECharts tree 格式思维导图 JSON |
| `quiz_agent` | `quiz_agent.py` | 生成多题型测验题目（单选/多选/填空） |
| `code_agent` | `code_agent.py` | 生成代码示例或编程练习 |
| `summary_agent` | `summary_agent.py` | 生成知识点精简复习总结 |
| `safety_agent` | `safety_agent.py` | 内容安全审核，检测幻觉/错误 |
| `recommend_agent` | `recommend_agent.py` | 基于画像推荐下一步学习知识点 |

---

## 2. 状态机核心

### 2.1 graph.py

LangGraph 主状态机，管理所有 Agent 的注册、边路由和执行。

#### 核心函数

| 函数 | 签名 | 说明 |
|------|------|------|
| `build_graph` | `() -> CompiledStateGraph` | 构建并返回编译后的状态机 |
| `get_graph` | `() -> StateGraph` | 返回全局图实例（单例） |
| `invoke` | `(user_id, session_id, message, db) -> AgentState` | 同步执行完整图推理 |
| `stream_invoke` | `(user_id, session_id, message, db)` | 流式执行，yield 事件 |

#### 条件路由

- `profile_agent.route_after_profile`: 画像完整度路由
  - `True` → `planner_agent`
  - `False` → `END`

- `planner_agent.route_by_resource_type`: 资源类型路由
  - `doc` → `doc_agent`
  - `mindmap` → `mindmap_agent`
  - `quiz` → `quiz_agent`
  - `code` → `code_agent`
  - `summary` → `summary_agent`
  - 其他 → `recommend_agent`

#### db 注入机制

所有 Agent 的 `run(state, config)` 函数通过 `config["configurable"]["db"]` 获取数据库会话，实现数据库操作。

---

## 3. Agent 详解

### 3.1 profile_agent

**职责**: 从用户对话中提取并更新学生画像，判断是否需要追问

**入口函数**: `run(state, config)`

**执行流程**:
1. **提取画像字段** - 调用 LLM 从 `user_message` 提取 JSON 格式画像字段
2. **合并到数据库** - 调用 `profile_svc.merge_chat_updates()` 增量更新画像
3. **判断消息意图** - 调用 LLM 判断是否为资源请求（yes/no）
4. **判断画像完整性** - 检查 `learning_goal` 或 `knowledge_weak/mastered` 是否非空
5. **生成追问消息** - 若画像不足，生成友好追问

**画像完整性判定**:
```python
最低要求：learning_goal 或 knowledge_weak 或 knowledge_mastered 至少一个非空
```

**路由函数**: `route_after_profile(state)`
- 画像完整 → `planner_agent`
- 画像不足 → `END`（追问用户）

---

### 3.2 planner_agent

**职责**: 解析用户意图，确定资源类型和目标知识点

**入口函数**: `run(state, config)`

**执行流程**:
1. 构建画像上下文（调用 `profile_svc.build_profile_context`）
2. 从数据库查询 KGNode 获取可用知识点列表
3. 调用 LLM 分析意图，返回 `{resource_type, kp_id}`
4. 更新 `state.resource_type` 和 `state.kp_id`

**SYSTEM_PROMPT 模板变量**:
- `{kp_list}` - 可选知识点列表（每行 `- id: name`）

**路由函数**: `route_by_resource_type(state)`
- 根据 `resource_type` 路由到对应生成 Agent

---

### 3.3 doc_agent

**职责**: 基于 RAG 生成结构化 Markdown 学习文档

**入口函数**: `run(state, config)`

**执行流程**:
1. 调用 `retrieve_by_kp(kp_name)` 检索相关文档片段
2. 调用 `format_context(chunks)` 构造上下文
3. 调用 LLM 生成 Markdown 文档
4. 更新 `state.retrieved_docs` 和 `state.draft_content`

**输出格式**: Markdown 文档

---

### 3.4 mindmap_agent

**职责**: 生成 ECharts tree 格式思维导图 JSON

**入口函数**: `run(state, config)`

**执行流程**:
1. 调用 `retrieve_by_kp()` 检索相关文档
2. 调用 LLM 生成严格 JSON 格式的思维导图
3. 验证 JSON 合法性（自动提取 JSON 部分）
4. 更新 `state.draft_content`

**输出格式**: ECharts tree JSON
```json
{
  "name": "知识点名称",
  "children": [
    {"name": "子概念1", "children": [...]},
    ...
  ]
}
```

---

### 3.5 quiz_agent

**职责**: 生成多题型测验题目集合

**入口函数**: `run(state, config)`

**执行流程**:
1. 根据画像决定题目数量分布（单选/多选/填空）
2. 检索相关文档
3. 调用 LLM 生成题目 JSON 数组
4. 更新 `state.draft_content`

**题目数量分布**:
- 无画像 / 薄弱知识点 ≤ 2: 单选 1道, 多选 1道, 填空 0道（共2道）
- 薄弱知识点 3-5: 单选 1道, 多选 1道, 填空 0道（共2道）
- 薄弱知识点 > 5: 单选 2道, 多选 2道, 填空 0道（共7道）
- 有画像（默认）: 单选 2道, 多选 1道, 填空 1道（共4道）

**题目格式**:
```json
{
  "question_type": "single/multi/fill",
  "difficulty": 1-5,
  "stem": "题干",
  "options": ["A. ...", "B. ..."],
  "answer": "A" 或 ["A","C"] 或 "答案文本",
  "explanation": "解析"
}
```

**辅助函数**: `save_quiz_items(resource_id, kp_id, questions, db)`
- 批量写入 `quiz_item` 表

---

### 3.6 code_agent

**职责**: 生成代码示例或编程练习

**入口函数**: `run(state, config)`

**执行流程**:
1. 检索相关文档（代码相关片段）
2. 构建画像上下文
3. 调用 LLM 生成代码
4. 更新 `state.draft_content`

**输出格式**: Markdown 代码块
- 包含题目描述
- 参考答案用 `# ===== 参考答案 =====` 分隔

---

### 3.7 summary_agent

**职责**: 生成知识点精简复习总结

**入口函数**: `run(state, config)`

**执行流程**:
1. 检索相关文档
2. 调用 LLM 生成要点式 Markdown 总结
3. 更新 `state.draft_content`

**输出要求**:
- 要点式 Markdown（无序列表 + 加粗）
- 控制在 300-500 字
- 突出核心概念、常见误区、记忆技巧
- 公式用 LaTeX 格式

---

### 3.8 safety_agent

**职责**: 内容安全审核，检测幻觉和错误

**入口函数**: `run(state, config)`

**执行流程**:
1. 若无 `draft_content` 直接通过
2. 将 `draft_content` 与 `retrieved_docs` 对比
3. 调用 LLM 审核，返回 `{passed, issues, revised_content}`
4. 若不通过，设置 `safety_passed=False`，使用修正内容

**辅助函数**: `should_skip_safety(state)`
- 若 `draft_content` 为空返回 `True`（跳过检查）

---

### 3.9 recommend_agent

**职责**: 基于画像和学习历史推荐下一步知识点

**入口函数**: `run(state, config)`

**执行流程**:
1. 构建画像上下文（学习目标、已掌握/薄弱知识点）
2. 从数据库查询 KGNode 获取可选知识点
3. 调用 LLM 生成推荐列表
4. 更新 `state.metadata["recommendations"]` 和 `state.final_content`

**输出格式**:
```json
[
  {"kp_id": "...", "kp_name": "...", "reason": "推荐原因"},
  ...
]
```

---

## 4. AgentState 状态结构

```python
class AgentState(BaseModel):
    user_id: str                    # 用户 UUID
    session_id: str                 # 会话 UUID
    user_message: str               # 用户原始消息
    profile: Optional[StudentProfileOut] = None   # 当前画像
    kp_id: Optional[str] = None     # 目标知识点 ID
    resource_type: Optional[ResourceType] = None # 资源类型
    retrieved_docs: list[str] = []   # 检索到的文档片段
    draft_content: Optional[str] = None  # 草稿内容（生成 Agent 输出）
    final_content: Optional[str] = None  # 最终内容（安全审核后）
    safety_passed: bool = True       # 安全审核是否通过
    profile_complete: bool = False   # 画像是否完整
    clarify_message: Optional[str] = None  # 追问消息
    error: Optional[str] = None      # 错误信息
    metadata: dict[str, Any] = {}    # 扩展元数据（如 recommendations）
```

---

## 5. 调用示例

### 5.1 FastAPI 中调用

```python
from backend.agents.graph import invoke, stream_invoke

# 同步调用
result = await invoke(
    user_id=str(user_uuid),
    session_id=str(session_uuid),
    message="帮我生成一份关于梯度下降的思维导图",
    db=db_session,
)

# 流式调用
async for event in stream_invoke(str(user_uuid), str(session_uuid), message, db):
    print(event)
```

### 5.2 Agent 独立调用

```python
from backend.agents.doc_agent import run as doc_run
from backend.models.schemas import AgentState

state = AgentState(
    user_id="...",
    session_id="...",
    user_message="生成文档",
    kp_id="kp_01",
    profile=profile,
)

result = await doc_run(state, config={"configurable": {"db": db_session}})
```

---

## 6. 相关模块依赖

| 模块 | 路径 | 用途 |
|------|------|------|
| `services.llm` | `backend/services/llm.py` | LLM 调用（chat_completion, get_embedding） |
| `services.profile` | `backend/services/profile.py` | 画像服务（merge_chat_updates, build_profile_context） |
| `rag.retriever` | `backend/rag/retriever.py` | RAG 检索（retrieve_by_kp, format_context） |
| `db.crud` | `backend/db/crud.py` | 数据库 CRUD 封装 |
| `models.schemas` | `backend/models/schemas.py` | Pydantic 数据模型 |

---

## 7. 单元测试覆盖（2026-04-25）

| Agent | 测试文件 | 测试数 |
|---|---|---|
| `graph.py` | `test_graph.py` | 9 |
| `profile_agent.py` | `test_profile_agent.py` | 14 |
| `planner_agent.py` | `test_planner_agent.py` | 10 |
| `doc_agent.py` | `test_doc_agent.py` | 4 |
| `mindmap_agent.py` | `test_mindmap_agent.py` | 3 |
| `quiz_agent.py` | `test_quiz_agent.py` | 7 |
| `code_agent.py` | `test_code_agent.py` | 3 |
| `summary_agent.py` | `test_summary_agent.py` | 3 |
| `safety_agent.py` | `test_safety_agent.py` | 7 |
| `recommend_agent.py` | `test_recommend_agent.py` | 5 |

共 68 个 agent 测试（整体测试套件 180 个）。

**测试运行**: `pytest tests/ -v`
