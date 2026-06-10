# FastAPI 异步后端架构文档

## 概述

本项目后端基于 **FastAPI** 构建，采用全异步（async/await）架构，整合 LangGraph 多智能体流水线、SQLAlchemy 2.0 异步 ORM、ChromaDB 向量数据库，为学生自动生成个性化学习资源。

- **入口文件**: `backend/main.py`（~1472 行）
- **应用实例**: `FastAPI(title="A3 -- Learning Multi-Agent System", version="0.1.0")`
- **前端服务**: 通过 `StaticFiles` 挂载 `frontend/` 目录于 `/app` 路径，`html=True` 启用 SPA fallback

---

## 1. 应用生命周期

应用使用 `@asynccontextmanager` 实现 `lifespan` 管理启动与关闭流程：

```
启动流程:
  1. init_db()          → 创建异步数据库引擎 + SQLite 自动建表
  2. init_vector_db()   → 初始化 ChromaDB 持久化客户端与集合
  3. get_graph()        → 预编译 LangGraph 状态机
  4. 启动后台清理任务      → 每 24 小时清理过期动态聊天表
  5. 自动索引知识库       → 若向量集合为空且 knowledge_base/ai_intro 存在，自动导入

关闭流程:
  1. 取消清理任务
  2. close_db()         → 释放数据库连接池
```

```python
# backend/main.py:84-113
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await init_vector_db()
    get_graph()
    cleanup_task = asyncio.create_task(start_cleanup_task())
    # ... 自动索引逻辑
    yield
    cleanup_task.cancel()
    await close_db()
```

### 中间件

- **CORS**: 允许所有来源、方法、请求头（`backend/main.py:126-131`）
- **LoggingMiddleware**: 自定义请求日志中间件，使用 `contextvars` 传递 `trace_id`（`backend/middleware/logging_middleware.py:58`）

---

## 2. 异步数据库层

### 2.1 引擎配置

**文件**: `backend/db/database.py`（112 行）

使用 SQLAlchemy 2.0 异步风格：

| 组件 | 说明 |
|------|------|
| `_engine` | 模块级单例 `AsyncEngine`，由 `create_async_engine()` 创建 |
| `_session_factory` | 模块级 `async_sessionmaker`，绑定到 `_engine` |
| `Base` | `DeclarativeBase` 基类 |

```python
# 生产环境连接池配置（非 SQLite）
create_async_engine(url, pool_size=10, max_overflow=20,
                    pool_timeout=30, pool_recycle=3600)

# SQLite 配置
create_async_engine(url, connect_args={"timeout": 30})
```

### 2.2 会话依赖注入

```python
# backend/db/database.py:91-101
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        try:
            yield session
            await session.commit()    # 成功自动提交
        except Exception:
            await session.rollback()  # 异常自动回滚
            raise
```

路由中使用 `db: AsyncSession = Depends(get_session)` 注入。该会话生命周期绑定到 HTTP 请求，响应返回后自动关闭。

### 2.3 ORM 模型

**文件**: `backend/db/models.py`（334 行）

共 15 张表，使用 SQLAlchemy 2.x `mapped_column` 风格：

| 模型 | 表名 | 用途 |
|------|------|------|
| `User` | `user` | 用户账户 |
| `StudentProfile` | `student_profile` | 学生画像（含学习目标、认知风格、掌握/薄弱知识点等） |
| `ProfileHistory` | `profile_history` | 画像快照历史 |
| `ChatSession` | `chat_session` | 聊天会话（含动态消息表名引用） |
| `KGNode` | `kg_node` | 知识图谱节点（课程/章/知识点/子点/概念） |
| `KGEdge` | `kg_edge` | 知识图谱边（IS_PART_OF/REQUIRES/RELATED_TO/CONTAINS） |
| `ResourceMeta` | `resource_meta` | 生成的学习资源（文档/思维导图/题目等） |
| `GenerationBatch` | `generation_batch` | 批量生成任务批次 |
| `GenerationTask` | `generation_task` | 单个资源生成任务 |
| `KGBuildTask` | `kg_build_task` | 知识图谱构建任务 |
| `QuizItem` | `quiz_item` | 题目（单选/多选/填空/简答） |
| `QuizAttempt` | `quiz_attempt` | 答题记录 |
| `LearningPath` | `learning_path` | 学习路径 |
| `LearningPathItem` | `learning_path_item` | 学习路径节点 |
| `LearningRecord` | `learning_record` | 学习行为记录 |

主要约定：
- 所有主键使用 `UUID` 类型，默认值 `uuid.uuid4`
- 时间戳统一使用 `created_at` / `updated_at`
- 外键 + `relationship()` 双向定义
- `KGNode` 使用字符串主键（如 `"kp_03_01"`），不走 UUID

### 2.4 通用异步 CRUD

**文件**: `backend/db/crud.py`（319 行）

全部为 `async def` 函数，使用 SQLAlchemy 2.x 核心查询风格（`select()` / `sa_update()` / `sa_delete()`）：

| 函数 | 用途 |
|------|------|
| `insert(session, model, data)` | 单条插入 |
| `insert_many(session, model, data_list)` | 批量插入 |
| `select(session, model, filters, order_by, limit, offset, loadRelations)` | 条件查询，支持 `selectinload` 预加载关联 |
| `select_one(session, model, filters, loadRelations)` | 单条查询 |
| `select_by_id(session, model, id, loadRelations)` | 按主键查询 |
| `count(session, model, filters)` | 计数查询 |
| `update_(session, model, filters, data)` | 条件更新 |
| `update_by_id(session, model, id, data)` | 按主键更新 |
| `delete(session, model, filters)` | 条件删除 |
| `delete_by_id(session, model, id)` | 按主键删除 |

特点：
- `filters` 接受 `dict[str, Any]`，`None` 值映射为 `IS NULL`
- `loadRelations` 支持嵌套路径，如 `"items.kp"` → `selectinload(Model.items).selectinload(Item.kp)`
- 所有写入操作默认 `commit=True`，可在调用方设为 `False` 实现事务组合

### 2.5 动态聊天消息表

**文件**: `backend/db/dynamic_chat.py`（220 行）

为每个聊天会话创建独立的消息表（SQLite 场景下单表过大时性能下降），表名格式为 `chat_msg_{username}_{short_id}`。

核心函数：
- `create_session_table(table_name)` — `CREATE TABLE IF NOT EXISTS`，同时通过 `PRAGMA table_info` + `ALTER TABLE` 做轻量迁移（新增列）
- `insert_message(table_name, role, content, ...)` — 自动确保表存在后插入
- `read_messages(table_name)` — 按 `created_at ASC` 读取全部消息
- `drop_session_table(table_name)` — 删除动态表
- `cleanup_expired_sessions()` — 清理 30 天前的会话及消息表

### 2.6 向量数据库

**文件**: `backend/db/vector.py`（129 行）

使用 ChromaDB 持久化本地模式（`chromadb.PersistentClient`），余弦相似度检索：

```python
# 初始化
client = chromadb.PersistentClient(path=config.vector_db.persist_dir)
collection = client.get_or_create_collection(
    name=config.vector_db.collection,
    metadata={"hnsw:space": "cosine"}
)
```

核心操作：`upsert_documents`、`query_documents`、`delete_documents`、`delete_by_doc_id`、`get_documents_by_doc_id`。

注意：ChromaDB Python 客户端本身是同步的，但嵌入步骤（`get_embedding`）是异步的，索引器通过 `asyncio.gather` + 信号量控制并发。

---

## 3. 配置系统

**文件**: `backend/config.py`（168 行） + `configs/config.yaml`（41 行）

### 3.1 加载流程

```
configs/config.yaml ──→ _resolve_env_vars() ──→ 数据类实例 ──→ 模块级单例 config
                             │
                      读取 ${ENV_VAR} 对应的环境变量
                      （通过 load_dotenv() 加载 .env 文件）
```

### 3.2 配置数据类

```python
@dataclass
class DatabaseConfig:
    url: str                # 默认 "sqlite+aiosqlite:///dev.db"
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 3600

@dataclass
class LLMConfig:
    api_key: str
    base_url: str
    model: str
    provider: str           # spark / deepseek / qwen / openai

@dataclass
class Config:
    database: DatabaseConfig
    vector_db: VectorDBConfig
    llm: LLMConfig
    rag: RAGConfig
    embedding: EmbeddingConfig
    jwt: JWTConfig
```

使用方式：`from backend.config import config` → `config.llm.model`

### 3.3 所需环境变量

| 变量 | 用途 | 配置引用 |
|------|------|---------|
| `LLM_API_KEY` | LLM API 密钥 | `${LLM_API_KEY}` |
| `JWT_SECRET` | JWT 签名密钥 | `${JWT_SECRET}` |
| `DATABASE_URL` | 数据库连接字符串 | `${DATABASE_URL}`（可选，默认 SQLite） |

---

## 4. 多智能体流水线（LangGraph）

### 4.1 图拓扑

**文件**: `backend/agents/graph.py`（179 行）

10 个节点的有向无环图（DAG）：

```
                        ┌─────────────────┐
                        │  profile_agent   │ ← START
                        └────────┬────────┘
                                 │
                    profile_complete?
                     │            │
                   False         True
                     │            │
                     ▼            ▼
                    END    ┌─────────────┐
                           │planner_agent │
                           └──────┬──────┘
                                  │
                     route_by_resource_type()
                  ┌───────┬───────┼───────┬───────┬───────┐
                  ▼       ▼       ▼       ▼       ▼       ▼
               doc    mindmap   quiz    code   summary   kg
              agent   agent    agent   agent   agent    agent
                  │       │       │       │       │       │
                  ▼       ▼       ▼       ▼       ▼       │
              ┌─────────────────┐                          │
              │  safety_agent   │  (kg 跳过安全检查)        │
              └────────┬────────┘                          │
                       │                                   │
                       ▼                                   │
              ┌─────────────────┐                          │
              │recommend_agent  │◄─────────────────────────┘
              └────────┬────────┘
                       │
                       ▼
                      END
```

### 4.2 调用方式

```python
# 同步调用（后台任务）
result = await get_graph().ainvoke(initial_state, config={"configurable": {"db": db}})

# 流式调用（SSE 推送）
async for event in get_graph().astream(initial_state, config={"configurable": {"db": db}}):
    yield event
```

图实例为模块级单例，首次调用时编译并缓存。

### 4.3 状态管理

所有 Agent 节点共享 `AgentState`（`backend/models/schemas.py:377-397`）：

```python
class AgentState(BaseModel):
    user_id: str
    session_id: str
    user_message: str
    profile: Optional[StudentProfileIn] = None
    kp_id: Optional[str] = None
    resource_type: Optional[ResourceType] = None
    retrieved_docs: list[str] = []
    draft_content: Optional[str] = None
    final_content: Optional[str] = None
    safety_passed: bool = True
    error: Optional[str] = None
    metadata: dict[str, Any] = {}
    profile_complete: bool = False
    clarify_message: Optional[str] = None
    num_questions: int = 4
    # ...
```

**不可变更新模式**：每个节点函数返回 `state.model_copy(update={...})`，绝不原地修改状态。

**数据库传递**：`db` 会话通过 `config["configurable"]["db"]` 传入，而非放在 State 中——这是 LangGraph 推荐的做法，将基础设施依赖与业务状态分离。

### 4.4 各 Agent 职责

| Agent | 文件 | 行数 | 职责 |
|-------|------|------|------|
| `profile_agent` | `profile_agent.py` | 218 | 从用户消息中提取画像字段，增量合并到数据库，检查完整性，生成追问 |
| `planner_agent` | `planner_agent.py` | 237 | 解析意图（资源类型 + 知识点ID），支持多资源并行生成请求检测 |
| `doc_agent` | `doc_agent.py` | 78 | 基于 RAG 检索生成 Markdown 学习文档 |
| `mindmap_agent` | `mindmap_agent.py` | 97 | 基于 RAG 检索生成 ECharts 树形 JSON 思维导图 |
| `quiz_agent` | `quiz_agent.py` | 173 | 生成多类型题目（单选/多选/填空），支持自定义各类型数量 |
| `code_agent` | `code_agent.py` | 97 | 生成 Python 编程练习题（含参考答案） |
| `summary_agent` | `summary_agent.py` | 74 | 生成复习摘要（含 LaTeX 公式） |
| `kg_agent` | `kg_agent.py` | 72 | 委托 `kg_builder` 从导入文档构建知识图谱 |
| `safety_agent` | `safety_agent.py` | 110 | 对照检索文档审查生成内容的准确性；解析/API 错误时保守放行 |
| `recommend_agent` | `recommend_agent.py` | 150 | 基于知识图谱 + 学生画像生成 3-5 个后续学习建议 |
| `clarify_agent` | `clarify_agent.py` | 63 | 利用聊天历史回答追问（独立节点，未接入主图） |

---

## 5. 服务层

### 5.1 LLM 服务

**文件**: `backend/services/llm.py`（215 行）

支持 4 个 LLM 提供商，统一通过 `openai.AsyncOpenAI` 异步客户端访问：

| 提供商 | 标识 | 说明 |
|--------|------|------|
| 星火 | `spark` | 讯飞 Spark API |
| DeepSeek | `deepseek` | DeepSeek API |
| 通义千问 | `qwen` | DashScope API（当前默认） |
| OpenAI | `openai` | 标准 OpenAI 兼容 API |

核心函数：

```python
# 非流式调用（含 tenacity 重试：5次，指数退避 3-30s）
async def chat_completion(messages, model=None, temperature=0.7,
                          max_tokens=4096, provider=None) -> str

# 流式调用（SSE，AsyncGenerator）
async def stream_chat_completion(messages, model=None, temperature=0.7,
                                 max_tokens=4096, provider=None) -> AsyncGenerator[str, None]

# 嵌入向量
async def get_embedding(text: str) -> list[float]
```

重试策略：
- `RateLimitError` 和 `PermissionDeniedError` 触发重试
- 千问配额不足时自动降级到备用模型（`qwen3.5-flash`）

嵌入模型：本地加载 `BAAI/bge-m3`（sentence-transformers），或通过 API 使用 `text-embedding-v4`（由 `config.embedding.use_spark` 控制）。

### 5.2 资源生成服务

**文件**: `backend/services/generation.py`（319 行）

后台资源生成的核心编排逻辑：

```
run_generation(task_id, user_id, session_id, request)
    │
    ├─ 1. 创建独立 DB 会话（通过 _session_factory()，不依赖请求生命周期）
    ├─ 2. 构造 AgentState，调用 get_graph().ainvoke()
    ├─ 3. 解析 draft_content，持久化到 ResourceMeta
    │     ├─ 文本类（doc/code/summary） → content 字段
    │     ├─ 结构化（mindmap）          → content_json 字段
    │     └─ 题目（quiz）              → content_json + QuizItem 表
    ├─ 4. 更新 GenerationTask 状态（done / failed）
    └─ 5. 如有推荐内容且用户无学习路径，自动创建学习路径
```

批量生成使用 `asyncio.gather(*tasks, return_exceptions=True)` 并行执行。

### 5.3 学生画像服务

**文件**: `backend/services/profile.py`（372 行）

核心能力：
- **增量合并** (`merge_chat_updates`)：每次对话后，将 LLM 提取的新信息合并到已有画像
  - 列表字段（`knowledge_mastered`、`knowledge_weak`、`error_prone`）：追加 + 去重
  - 学习目标：追加用户消息到 `goal_questions` 列表，然后**异步触发** `refresh_learning_goal()`
- **异步目标摘要**：使用独立的 DB 会话和 `asyncio.Task`，对累计的 `goal_questions` 调用 LLM 重新总结 `learning_goal`，不阻塞聊天响应
- **历史快照**：每次更新画像前，将当前状态保存到 `ProfileHistory`

### 5.4 知识图谱构建服务

**文件**: `backend/services/kg_builder.py`（800 行）

两种构建路径：
1. **TOC 路径**（PDF 有书签/大纲时）：提取目录骨架 → 逐章用 LLM 提取细粒度知识点 → 合并骨架与细节 → 推断跨章关联边
2. **Fallback 路径**（无 TOC）：按页分批 → LLM 提取节点 → LLM 推断边

并发控制：`asyncio.Semaphore(10)` 限制并发 LLM 调用数。边提取批次有 10 节点重叠确保边界关系不断裂。

---

## 6. RAG 流水线

### 6.1 文档加载

**文件**: `backend/rag/loader.py`（432 行）

- **核心数据结构**: `TextChunk`（chunk_id, text, doc_id, source_path, page, section, metadata）
- **支持格式**: PDF（PyPDFLoader）、DOCX（UnstructuredWordDocumentLoader）、Markdown（按 `##` 标题切分）、TXT
- **PDF TOC 提取**: 使用 `pypdf.PdfReader` 提取书签/大纲，解析目标页码
- **文本切分**: `split_text()` 按 `chunk_size`/`chunk_overlap` 从配置读取

### 6.2 向量索引

**文件**: `backend/rag/indexer.py`（102 行）

```
文档 → load_file() → TextChunk[] → 分批嵌入 → ChromaDB upsert
                                      │
                              asyncio.Semaphore(8)
                              并发嵌入调用 ≤ 8
```

### 6.3 语义检索

**文件**: `backend/rag/retriever.py`（153 行）

- `retrieve(query, n_results=5, score_threshold=0.5)` — 通用语义检索
- `retrieve_by_kp(kp_name, n_results=8)` — 知识点检索（自动添加"知识点："前缀）
- `format_context(chunks, max_tokens=3000)` — 将检索结果格式化为编号引用字符串

ChromaDB 返回的余弦距离自动转换为相似度分数（`1 - distance`），按分数降序排列。

---

## 7. 认证与鉴权

### 7.1 JWT 认证流程

**注册** (`POST /auth/register`)：检查用户名唯一 → bcrypt 哈希密码 → 插入用户 → 返回 `UserOut`

**登录** (`POST /auth/login`)：查询用户 → bcrypt 验证密码 → 生成 JWT（含 `sub`、`exp`）→ 返回 `TokenOut`

### 7.2 鉴权依赖

**文件**: `backend/auth/deps.py`（42 行）

```python
async def get_current_user_id(
    cred: HTTPAuthorizationCredentials | None = Depends(_bearer),
    user_id: uuid.UUID | None = Query(None),
) -> uuid.UUID:
```

两级鉴权：
1. **JWT 优先**：验证 `Authorization: Bearer <token>` 请求头
2. **Query 参数回退**：兼容过渡期的 `?user_id=...` 方式
3. 两者皆无则返回 401

**密码哈希**: 纯 bcrypt（`backend/auth/hash_utils.py`，12 行），`hash_password()` 自动生成盐值。

### 7.3 所有权校验

敏感路由中额外校验资源归属：`resource.user_id == user_id` 或 `session.user_id == user_id`，不匹配返回 403。

---

## 8. 后台任务模式

项目使用四种后台执行模式：

### 模式 A: FastAPI `BackgroundTasks`

适用于从路由直接触发的后台任务：

```python
# main.py:634
background_tasks.add_task(run_kg_build, task.id, doc_id, db, user_id)
```

注意：任务函数内部必须创建独立的 DB 会话（通过 `_session_factory()`），因为请求级会话在响应返回后即关闭。

### 模式 B: `asyncio.create_task()` 即发即忘

适用于不关心返回值的异步任务：

```python
# main.py:734
asyncio.create_task(run_generation(task.task_id, str(user_id), session_id, body_dict))
```

任务在同一个事件循环中运行，路由不等待其完成。同样使用独立的 DB 会话。

### 模式 C: 托管 `asyncio.Task`

用于需要防止被垃圾回收的后台任务：

```python
# profile.py:282-292
_BG_TASKS: set[asyncio.Task] = set()

task = loop.create_task(refresh_learning_goal(user_id, questions))
_BG_TASKS.add(task)
task.add_done_callback(_BG_TASKS.discard)
```

通过模块级 set 持有引用，`done_callback` 自动清理。

### 模式 D: `asyncio.gather()` 并行执行

用于批量并发操作：

```python
# generation.py:296
results = await asyncio.gather(
    *[run_generation(cfg) for cfg in task_configs],
    return_exceptions=True  # 单个失败不影响其他
)
```

---

## 9. 异步全景总结

| 层级 | 异步实现 |
|------|---------|
| **Web 框架** | FastAPI `async def` 路由处理器 |
| **数据库** | SQLAlchemy 2.0 `AsyncEngine` + `AsyncSession`，所有 CRUD 均为 `async def` |
| **LLM 调用** | `openai.AsyncOpenAI` 异步 HTTP 客户端 |
| **嵌入模型** | `async def get_embedding()`，本地模型同步推理但在异步上下文中调用 |
| **向量数据库** | ChromaDB 操作同步（Python 客户端限制），但嵌入步骤异步，索引批次通过 `asyncio.gather` 并发 |
| **LangGraph** | `ainvoke()` / `astream()` 异步方法 |
| **流式响应** | `StreamingResponse` + `text/event-stream`（SSE） |
| **文件 I/O** | `Path.write_bytes()` 同步（小文件可接受），PDF 加载同步 |
| **日志** | `loguru` 全项目使用（`logging_config.py` 配置控制台 + 滚动文件） |

### 关键约定

1. **会话管理**：请求内使用 `Depends(get_session)`；后台任务使用 `_session_factory()` 创建独立会话
2. **状态不可变**：LangGraph 节点必须 `model_copy(update=...)`，禁止原地修改
3. **DB 不放入 State**：通过 LangGraph 的 `config["configurable"]["db"]` 传递基础设施依赖
4. **`return_exceptions=True`**：批量并发操作使用此参数，单个失败不中断整体
5. **信号量控制并发**：LLM 调用（Semaphore(10)）、嵌入调用（Semaphore(8)）

---

## 10. API 路由总览

| 标签 | 路径 | 方法 | 说明 |
|------|------|------|------|
| `system` | `/health` | GET | 健康检查（DB + 向量库） |
| `auth` | `/auth/register` | POST | 用户注册 |
| `auth` | `/auth/login` | POST | 用户登录，返回 JWT |
| `profile` | `/profile` | GET/PUT | 获取/更新学生画像 |
| `profile` | `/profile/history` | GET | 画像历史快照 |
| `chat` | `/chat/sessions` | GET/POST | 会话列表 / 创建 |
| `chat` | `/chat/{session_id}` | GET/DELETE/PATCH | 聊天消息（支持 `?stream=true` SSE 流式） |
| `knowledge-graph` | `/kg/graph` | GET | 获取知识图谱数据 |
| `knowledge-graph` | `/kg/build` | POST | 触发知识图谱构建（后台任务） |
| `generate` | `/generate` | POST | 生成单个学习资源（后台任务） |
| `generate` | `/generate/batch` | POST | 批量生成多种资源（并行后台任务） |
| `generate` | `/generate/smart` | POST | 智能规划 + 批量生成 |
| `resources` | `/resources` | GET | 资源列表（支持类型/知识点筛选） |
| `resources` | `/resources/stats` | GET | 资源统计 |
| `resources` | `/resources/{resource_id}` | GET/DELETE | 资源详情 / 删除 |
| `quiz` | `/resources/{resource_id}/quiz` | GET | 获取资源关联题目 |
| `quiz` | `/quiz/submit` | POST | 提交答案 |
| `quiz` | `/quiz/attempts` | GET | 答题记录 |
| `pathway` | `/pathways` | GET/POST | 学习路径列表 / 创建 |
| `pathway` | `/pathways/{path_id}` | GET/PUT/DELETE | 学习路径 CRUD |
| `pathway` | `/pathways/{path_id}/items` | POST | 添加路径节点 |
| `documents` | `/documents/import` | POST | 导入文档（同步） |
| `documents` | `/documents/import/async` | POST | 导入文档（异步，可轮询进度） |
| `documents` | `/documents` | GET | 文档列表 |
| `documents` | `/documents/file/{filename}` | GET | 文件下载（含路径穿越防护） |
| `records` | `/records` | POST/GET | 学习记录写入 / 查询 |

---

## 11. 项目文件索引

```
backend/
├── main.py                          # FastAPI 应用入口，全部路由，生命周期
├── config.py                        # 配置数据类，YAML 加载，环境变量解析
├── logging_config.py                # Loguru 日志配置
├── auth/
│   ├── deps.py                      # JWT 鉴权依赖（get_current_user_id）
│   └── hash_utils.py                # bcrypt 密码哈希
├── db/
│   ├── database.py                  # 异步引擎，会话工厂，get_session 依赖
│   ├── models.py                    # 15 个 SQLAlchemy ORM 模型
│   ├── crud.py                      # 通用异步 CRUD（10 个函数）
│   ├── vector.py                    # ChromaDB 客户端封装
│   └── dynamic_chat.py              # 动态聊天消息表 + 清理任务
├── models/
│   └── schemas.py                   # Pydantic 模型，枚举，AgentState
├── agents/
│   ├── graph.py                     # LangGraph 状态机（10 节点 DAG）
│   ├── profile_agent.py             # 学生画像提取与合并
│   ├── planner_agent.py            # 意图解析与资源路由
│   ├── doc_agent.py                 # 文档生成
│   ├── mindmap_agent.py             # 思维导图生成
│   ├── quiz_agent.py                # 题目生成
│   ├── code_agent.py                # 代码练习生成
│   ├── summary_agent.py             # 复习摘要生成
│   ├── kg_agent.py                  # 知识图谱构建代理
│   ├── safety_agent.py              # 内容安全检查
│   ├── recommend_agent.py           # 后续学习推荐
│   ├── clarify_agent.py             # 追问应答
│   └── utils.py                     # 知识点名称解析工具
├── services/
│   ├── llm.py                       # 多提供商 LLM 客户端，重试，嵌入
│   ├── generation.py                # 资源生成后台编排
│   ├── profile.py                   # 画像 CRUD，增量合并，异步目标摘要
│   ├── resource.py                  # 资源 CRUD，任务管理
│   ├── document.py                  # 文档导入流水线
│   ├── pathway.py                   # 学习路径 CRUD
│   ├── kg_builder.py                # 知识图谱构建（800 行核心逻辑）
│   └── chat_history.py              # 聊天历史加载与截断
├── rag/
│   ├── loader.py                    # 文档加载器（PDF/DOCX/MD/TXT）
│   ├── indexer.py                   # 批量嵌入 + 向量索引
│   └── retriever.py                 # 语义检索 + 上下文格式化
└── middleware/
    └── logging_middleware.py        # trace_id 请求日志中间件
```
