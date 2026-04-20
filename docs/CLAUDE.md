# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# 安装依赖
pip install -r requirements.txt

# 启动后端（开发模式，自动重载）
uvicorn backend.main:app --reload --port 8000

# 启动前端
streamlit run streamlit_app/app.py

# 运行全部测试
pytest tests/ -v

# 运行单个测试文件
pytest tests/test_schemas.py -v

# 运行单个测试用例
pytest tests/test_rag.py::TestSplitText::test_overlap_preserved -v

# 首次运行：索引知识库文档
python -c "
import asyncio
from backend.db.vector import init_vector_db
from backend.rag.indexer import index_directory
init_vector_db()
asyncio.run(index_directory('knowledge_base/ai_intro/chapters'))
"
```

## 环境变量

最小配置（开发模式，SQLite + 本地 embedding）：

```
SPARK_API_KEY=<讯飞星火 API Key>
```

生产配置额外需要：

```
DATABASE_URL=mysql+aiomysql://user:pass@host/db   # 或 postgresql+asyncpg://...
CHROMA_PERSIST_DIR=./chroma_data
USE_SPARK_EMBEDDING=false   # true 则调用讯飞 embedding API，否则用本地 BGE-M3
```

## 架构概览

### 请求流

```
用户 → Streamlit (8501) → FastAPI (8000) → LangGraph 状态机 → 各 Agent → LLM / ChromaDB / PostgreSQL
```

### Agent 执行顺序

所有对话请求都经过同一条 LangGraph 管道（`backend/agents/graph.py`）：

```
profile_agent → planner_agent → [doc|mindmap|quiz|code|summary]_agent → safety_agent → recommend_agent → END
```

- `planner_agent.route_by_resource_type()` 决定走哪个生成 Agent
- 若意图不需要生成资源，`planner_agent` 直接路由到 `recommend_agent`
- `safety_agent` 对所有生成内容做幻觉检测，可修正 `draft_content` 并设置 `safety_passed`

Agent 间通过 `AgentState`（`backend/models/schemas.py`）传递状态，关键字段：
- `user_message` / `profile` / `kp_id` / `resource_type`
- `retrieved_docs` — RAG 检索结果，供生成 Agent 使用
- `draft_content` → `final_content` — 生成内容经 SafetyAgent 审核后写入 `final_content`

### 数据库层

- `backend/db/postgres.py` — 引擎单例、`get_session()` Depends、`init_db()`
- `backend/db/models.py` — 全部 13 张 ORM 表（SQLAlchemy 2.x `Mapped` 风格）
- `backend/db/vector.py` — ChromaDB 封装，接口：`upsert_documents` / `query_documents` / `delete_documents`

SQLite 开发模式下 `init_db()` 自动建表；MySQL/PostgreSQL 生产模式需手动执行迁移（Alembic 尚未集成）。

### RAG 管道

```
loader.py（文档解析 + split_text）→ indexer.py（embed + upsert ChromaDB）
retriever.py（embed query → query ChromaDB → format_context）→ 生成 Agent
```

`split_text(text, chunk_size=512, overlap=64)` 是纯函数，已有单元测试。

### 实现状态

| 模块 | 状态 |
|------|------|
| `backend/models/schemas.py` | 完整 |
| `backend/db/postgres.py` + `models.py` | 完整 |
| `backend/db/vector.py` | 完整 |
| `backend/services/llm.py` | `chat_completion` / `stream_chat_completion` 完整；`_local_embedding` / `_spark_embedding` 是 stub |
| `backend/rag/loader.py` | `split_text` 完整；`_load_pdf` / `_load_docx` 是 stub |
| `backend/rag/indexer.py` / `retriever.py` | 框架完整，依赖 embedding stub |
| `backend/agents/*.py` (9个) | 全部 `raise NotImplementedError`，含详细 TODO 注释 |
| `backend/services/profile.py` / `resource.py` | 全部 stub |
| `streamlit_app/` | 页面框架完整，依赖后端就绪 |

### 新增 Agent 的步骤

1. 在 `backend/agents/` 新建 `xxx_agent.py`，实现 `async def run(state: AgentState) -> AgentState`
2. 在 `backend/agents/graph.py` 注册节点并添加边
3. 在 `backend/agents/__init__.py` 导入模块
4. 若需新资源类型，在 `backend/models/schemas.py` 的 `ResourceType` 枚举中添加值，并在 `streamlit_app/components/resource_card.py` 的 `_render_content` 中添加渲染逻辑
