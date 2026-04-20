# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Context

第十五届中国软件杯大学生软件设计大赛 · A3 赛题：个性化资源生成与学习多智能体系统

A multi-agent learning system that generates personalized educational resources (docs, mindmaps, quizzes, code examples, summaries) based on 8-dimensional student profiles. Uses LangGraph to orchestrate 9 specialized agents with RAG-enhanced generation and hallucination detection.

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Start backend (dev mode with auto-reload)
uvicorn backend.main:app --reload --port 8000

# Start frontend
streamlit run streamlit_app/app.py

# Run all tests
pytest tests/ -v

# Run single test file
pytest tests/test_schemas.py -v

# Run specific test
pytest tests/test_rag.py::TestSplitText::test_overlap_preserved -v

# Index knowledge base documents (first-time setup)
python -c "
import asyncio
from backend.db.vector import init_vector_db
from backend.rag.indexer import index_directory
init_vector_db()
asyncio.run(index_directory('knowledge_base/ai_intro/chapters'))
"
```

## Environment Variables

Minimal config (dev mode with SQLite + local embedding):
```
SPARK_API_KEY=<required>
```

Production config:
```
DATABASE_URL=mysql+aiomysql://user:pass@host/db
CHROMA_PERSIST_DIR=./chroma_data
USE_SPARK_EMBEDDING=false
```

Multi-provider LLM support (set `LLM_PROVIDER` to switch):
```
LLM_PROVIDER=spark|deepseek|qwen|openai
SPARK_API_KEY=<key>
DEEPSEEK_API_KEY=<key>
QWEN_API_KEY=<key>
OPENAI_API_KEY=<key>
```

## Architecture

### Request Flow
```
User → Streamlit (8501) → FastAPI (8000) → LangGraph → Agents → LLM/ChromaDB/Database
```

### LangGraph Agent Pipeline

All requests flow through a single state machine (`backend/agents/graph.py`):

```
profile_agent → planner_agent → [doc|mindmap|quiz|code|summary]_agent
  → safety_agent → recommend_agent → END
```

**Key routing logic:**
- `planner_agent.route_by_resource_type()` determines which generation agent to invoke
- If no resource generation needed, routes directly to `recommend_agent`
- `safety_agent` performs hallucination detection on all generated content

**State management:**
- Agents communicate via `AgentState` (defined in `backend/models/schemas.py`)
- Critical fields: `user_message`, `profile`, `kp_id`, `resource_type`, `retrieved_docs`, `draft_content`, `final_content`
- `draft_content` → `safety_agent` → `final_content` (with `safety_passed` flag)

### Database Layer

**13 tables** (SQLAlchemy 2.x async ORM in `backend/db/models.py`):
- User & auth: `user`, `chat_session`
- Profile: `student_profile`, `profile_history`
- Learning: `learning_path`, `learning_path_item`, `learning_record`
- Resources: `resource_meta`, `generation_task`, `quiz_item`, `quiz_attempt`
- Knowledge graph: `kg_node`, `kg_edge`

**Database setup:**
- `backend/db/database.py` — async engine singleton, `get_session()` dependency
- SQLite auto-creates tables via `init_db()`; MySQL/PostgreSQL requires manual migration
- `backend/db/vector.py` — ChromaDB wrapper with `upsert_documents`, `query_documents`, `delete_documents`

### RAG Pipeline

```
loader.py (parse + split_text) → indexer.py (embed + ChromaDB)
  → retriever.py (semantic search) → generation agents
```

- `split_text(text, chunk_size=512, overlap=64)` is a pure function with unit tests
- Supports PDF, DOCX, Markdown via `_load_pdf`, `_load_docx`, `_load_markdown`
- Embedding: local BGE-M3 (default) or Spark API (if `USE_SPARK_EMBEDDING=true`)

### LLM Service Layer

`backend/services/llm.py` provides unified interface for multiple providers:
- **Primary**: 讯飞星火 (Spark) via OpenAI-compatible SDK
- **Fallbacks**: DeepSeek, Qwen (with auto-failover on quota exhaustion), OpenAI
- **Functions**: `chat_completion()`, `stream_chat_completion()`, `get_embedding()`
- **Qwen failover**: Automatically switches models when quota exhausted (configured via `QWEN_MODELS` env var)

### Knowledge Base Structure

`knowledge_base/ai_intro/` contains example course materials:
- `chapters/` — source documents (PDF/MD/DOCX)
- `knowledge_points.json` — 16 knowledge node definitions with metadata
- `dependencies.json` — prerequisite relationships between knowledge points

## Implementation Status

| Module | Status |
|--------|--------|
| Schemas, database, vector DB | ✅ Complete |
| LLM service (chat/stream) | ✅ Complete |
| LLM service (embedding) | ⚠️ Stubs (`_local_embedding`, `_spark_embedding`) |
| RAG loader (split_text) | ✅ Complete |
| RAG loader (PDF/DOCX parsers) | ⚠️ Stubs |
| RAG indexer/retriever | ⚠️ Framework complete, depends on embedding |
| All 9 agents | ❌ `NotImplementedError` with TODO comments |
| Services (profile, resource) | ❌ Stubs |
| Streamlit frontend | ⚠️ Framework complete, depends on backend |

## Adding New Agents

1. Create `backend/agents/xxx_agent.py` with `async def run(state: AgentState) -> AgentState`
2. Register node and edges in `backend/agents/graph.py`
3. Import in `backend/agents/__init__.py`
4. If adding new resource type: update `ResourceType` enum in `schemas.py` and add rendering logic in `streamlit_app/components/resource_card.py`

## API Endpoints

15+ FastAPI routes in `backend/main.py`:
- Auth: `/auth/register`, `/auth/login`
- Profile: `GET/PUT /profile`
- Chat: `POST /chat/{session_id}` (supports SSE streaming)
- Knowledge graph: `GET /kg/graph`
- Generation: `POST /generate`, `GET /generate/{task_id}/status`
- Resources: `GET /resources`, `GET /resources/{id}`
- Quiz: `POST /quiz/submit`
- Pathways: `GET /pathways`
