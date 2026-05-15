# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

第十五届中国软件杯 A3 赛题 — 个性化资源生成与学习多智能体系统。面向高等教育场景，通过 9 个 LangGraph Agent 协同为学生自动生成个性化学习资源。

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run database migrations (first time or after schema changes)
alembic upgrade head

# Run backend (frontend at http://localhost:8000/app)
uvicorn backend.main:app --reload --port 8000

# Build knowledge base vector index
python -m backend.rag.indexer

# Run all tests
pytest tests/ -v

# Run lightweight tests (no DB/LLM deps)
pytest tests/test_schemas.py -v

# Run a single test function
pytest tests/test_schemas.py::test_user_create -v
```

## Architecture

**Stack:** FastAPI (async) + HTML/CSS/JS frontend + LangGraph agents + PostgreSQL vector store (JSON + numpy cosine) + SQLAlchemy 2.0 (async ORM) + PostgreSQL

**LLM & Config:** Provider/model configured in `configs/config.yaml` via `${ENV_VAR}` substitution. Currently uses Qwen (`qwen3.5-flash`) via DashScope. Multi-provider support (spark/deepseek/qwen/openai) in `backend/services/llm.py`. Config is a module-level singleton: `from backend.config import config`.

**Required env vars** (see `.env.example`): `LLM_API_KEY`, `JWT_SECRET`, `DATABASE_URL` (PostgreSQL, e.g. `postgresql+asyncpg://user:pass@localhost:5432/softbei`).

### Agent Pipeline (LangGraph)

`backend/agents/graph.py` defines a 9-node StateGraph. All agents share `AgentState` (TypedDict in `backend/models/schemas.py`).

1. `profile_agent` — extracts/accumulates student profile. Routes to END (ask follow-up) or `planner_agent` (profile sufficient).
2. `planner_agent` — analyzes intent, fans out to up to 5 parallel generators.
3. `doc_agent`, `mindmap_agent`, `quiz_agent`, `code_agent`, `summary_agent` — run in parallel.
4. `safety_agent` — content safety check.
5. `recommend_agent` → END.

Resource generation is triggered via `POST /generate`, runs as a background task in `backend/services/generation.py`, and persists results to `ResourceMeta` + `QuizItem` tables.

### Database Layer

- **PostgreSQL** via `asyncpg` driver. Schema managed by **Alembic** (`migrations/`).
- ORM models in `backend/db/models.py`: `User`, `StudentProfile`, `ProfileHistory`, `ChatSession`, `ChatMessage`, `KGNode`, `KGEdge`, `ResourceMeta`, `GenerationBatch`, `GenerationTask`, `KGBuildTask`, `QuizItem`, `QuizAttempt`, `LearningPath`, `LearningPathItem`, `LearningRecord`
- Generic async CRUD in `backend/db/crud.py`: `insert`, `select`, `select_one`, `update_by_id`, `delete_by_id`, `count`. Supports relation loading via `loadRelations` param.
- Chat messages stored in static `chat_message` table.
- Connection pool: `pool_size=10 + max_overflow=20`, `pool_pre_ping=True`.

### RAG Pipeline

`backend/rag/loader.py` → `indexer.py` → `retriever.py`. Loader parses PDF/DOCX/Markdown/TXT into `TextChunk` objects. Indexer vectorizes with BGE-M3 into PostgreSQL `document_chunk` table. Retriever does semantic search via numpy cosine similarity with citation formatting.

### Frontend

HTML/CSS/JS frontend served via FastAPI StaticFiles at `/app`. Pages: `index`, `auth`, `chat`, `profile`, `generate`, `pathway`, `library`, `evaluate`. API layer in `html-test/assets/api.js`. Auth: JWT stored in localStorage, user_id passed as query param.

## Key Conventions

- **Pydantic v2** for all schemas (`backend/models/schemas.py`)
- **pytest-asyncio** with `asyncio_mode = auto` — no `@pytest.mark.asyncio` needed
- All DB operations are async (`async with get_session() as session`)
- Agent pattern: receive `AgentState` dict → call LLM → update state fields → return state

## Naming Conventions — ORM ↔ Schema Alignment

**`backend/db/models.py` is the single source of truth.** Schema field names must exactly match ORM field names. Never invent aliases in schemas; never use `model_validator` for field name mapping.

Full rules and checklist: [`docs/DATA_MODEL_CONVENTIONS.md`](docs/DATA_MODEL_CONVENTIONS.md)

### Quick reference

| Category | Correct | Forbidden |
|----------|---------|-----------|
| Creation timestamp | `created_at` | `submitted_at`, `recorded_at`, `added_at` |
| Update timestamp | `updated_at` | `modified_at`, `last_updated` |
| Primary key in schema | `id` | `task_id`, `record_id`, `path_id` |
| Error text | `error_message` | `error_msg`, `error`, `err` |
| Entity title | `title` (match ORM) | renaming to `name` in schema |
| Node type field | `node_type` (match ORM) | renaming to `type` in schema |

**When adding a new model**, verify:
1. All timestamps use `created_at` / `updated_at`
2. Every schema field name matches the ORM column name exactly
3. No `model_validator` used for field renaming
4. `main.py` manual schema construction references ORM field names directly
5. Frontend `.get("field_name")` keys match actual API response fields
