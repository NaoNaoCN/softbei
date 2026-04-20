# 个性化资源生成与学习多智能体系统

> 第十五届中国软件杯大学生软件设计大赛 · A3 赛题

基于多智能体（Multi-Agent）架构，为学生提供**个性化学习资源生成**、**知识图谱导航**和**智能学习路径规划**的 AI 学习助手。

---

## 目录

- [系统概述](#系统概述)
- [核心功能](#核心功能)
- [技术架构](#技术架构)
- [Agent 系统](#agent-系统)
- [项目结构](#项目结构)
- [快速开始](#快速开始)
- [环境变量](#环境变量)
- [API 文档](#api-文档)
- [数据库设计](#数据库设计)
- [知识图谱](#知识图谱)
- [开发指南](#开发指南)

---

## 系统概述

本系统以**讯飞星火大模型**为核心 LLM，结合 LangGraph 状态机、RAG 检索增强生成和向量数据库，通过 10 个协作 Agent 实现：

- 从对话中自动构建并更新**学生个性化画像**
- 按需生成 5 种类型的**定制化学习资源**
- 对生成内容进行**幻觉检测与来源引用**，保障内容质量
- 基于知识图谱依赖关系，规划**个性化学习路径**

```
用户输入
   │
   ▼
ProfileAgent ──→ PlannerAgent
                     │
          ┌──────────┼──────────┐
          ▼          ▼          ▼
      DocAgent  MindmapAgent  QuizAgent  CodeAgent  SummaryAgent
          └──────────┼──────────┘
                     ▼
               SafetyAgent（幻觉过滤）
                     │
                     ▼
             RecommendAgent（推荐下一步）
```

---

## 核心功能

| 功能 | 说明 |
|------|------|
| **学生画像** | 8 维度画像（专业、目标、认知风格、薄弱点等），对话式自动更新 |
| **资源生成** | 学习文档 / 思维导图 / 测验题目 / 代码示例 / 知识总结，异步生成+进度轮询 |
| **知识图谱** | 5 层节点（课程→章节→知识点→子点→概念）+ 4 种关系，ECharts 可视化 |
| **学习路径** | 基于图谱依赖关系，结合画像生成有序学习计划 |
| **学习评估** | 多题型测验（单选/多选/填空/问答），自动批改，弱点追踪 |
| **防幻觉** | RAG 来源引用 + SafetyAgent 二次审核 + 置信度过滤 |

---

## 技术架构

```
┌─────────────────────────────────────┐
│         Streamlit 前端              │
│  app.py  │  5 个页面  │  3 个组件  │
└──────────────────┬──────────────────┘
                   │ HTTP / SSE
┌──────────────────▼──────────────────┐
│           FastAPI 后端              │
│  main.py（路由） │ models/schemas   │
├──────────┬───────┴────────┬─────────┤
│  agents/ │   services/   │  rag/   │
│ LangGraph│ LLM/Profile/  │Loader/  │
│  状态机  │   Resource    │Indexer/ │
│          │               │Retriever│
├──────────┴───────┬────────┴─────────┤
│       db/        │                  │
│  PostgreSQL      │   ChromaDB       │
│  (SQLAlchemy)    │   (向量库)       │
└──────────────────┴──────────────────┘
```

**技术选型：**

| 层级 | 技术 |
|------|------|
| 前端 | Streamlit 1.35+, streamlit-echarts |
| 后端 | FastAPI + Uvicorn（异步） |
| Agent | LangGraph 0.1+, LangChain 0.2+ |
| LLM | 讯飞星火（主）/ OpenAI 兼容接口（备） |
| 向量库 | ChromaDB（本地持久化） |
| Embedding | BGE-M3（本地）/ 讯飞 Embedding API |
| 关系库 | PostgreSQL（生产）/ SQLite（开发） |
| ORM | SQLAlchemy 2.x 异步 |

---

## Agent 系统

| Agent | 职责 | 触发条件 |
|-------|------|----------|
| `ProfileAgent` | 从对话提取并更新学生画像 | 每次对话首先执行 |
| `PlannerAgent` | 分析意图，决定资源类型和目标知识点 | ProfileAgent 之后 |
| `DocAgent` | RAG 检索 + 生成 Markdown 学习文档 | 意图=文档 |
| `MindmapAgent` | 生成 ECharts tree JSON 思维导图 | 意图=思维导图 |
| `QuizAgent` | 生成多题型测验题目集 | 意图=测验 |
| `CodeAgent` | 生成代码示例或编程练习 | 意图=代码 |
| `SummaryAgent` | 生成要点式复习总结 | 意图=总结 |
| `SafetyAgent` | 幻觉检测、来源核查、内容修正 | 所有生成 Agent 之后 |
| `RecommendAgent` | 推荐下一步学习的知识点 | SafetyAgent 之后 |

---

## 项目结构

```
softbei/
├── README.md
├── requirements.txt
│
├── backend/                        # FastAPI 后端
│   ├── main.py                     # 路由声明、lifespan、中间件
│   ├── models/
│   │   └── schemas.py              # Pydantic v2 请求/响应模型、AgentState
│   ├── agents/
│   │   ├── graph.py                # LangGraph 状态机（节点注册 & 路由）
│   │   ├── profile_agent.py
│   │   ├── planner_agent.py
│   │   ├── doc_agent.py
│   │   ├── mindmap_agent.py
│   │   ├── quiz_agent.py
│   │   ├── code_agent.py
│   │   ├── summary_agent.py
│   │   ├── safety_agent.py
│   │   └── recommend_agent.py
│   ├── rag/
│   │   ├── loader.py               # 文档解析 & 文本切分
│   │   ├── indexer.py              # 批量嵌入 & 写入向量库
│   │   └── retriever.py            # 语义检索 & 引用格式化
│   ├── services/
│   │   ├── llm.py                  # LLM 调用封装（流式/非流式/嵌入）
│   │   ├── profile.py              # 学生画像 CRUD
│   │   └── resource.py             # 资源元数据 & 任务追踪
│   └── db/
│       ├── postgres.py             # 数据库连接池 & 会话依赖
│       └── vector.py               # ChromaDB 封装
│
├── streamlit_app/                  # Streamlit 前端
│   ├── app.py                      # 全局配置 & 会话状态
│   ├── pages/
│   │   ├── 1_profile.py            # 学生画像页
│   │   ├── 2_generate.py           # 资源生成页
│   │   ├── 3_pathway.py            # 学习路径 & 知识图谱页
│   │   ├── 4_library.py            # 资源库页
│   │   └── 5_evaluate.py           # 学习评估页
│   └── components/
│       ├── mindmap.py              # ECharts 思维导图 & 知识图谱渲染
│       ├── quiz_card.py            # 题目卡片（展示 & 交互双模式）
│       └── resource_card.py        # 资源卡片统一预览
│
├── knowledge_base/                 # 知识库原始文档
│   └── ai_intro/                   # 示例课程：人工智能导论
│       ├── chapters/               # 章节文档（PDF/MD/DOCX）
│       ├── knowledge_points.json   # 知识点节点定义（16 个示例）
│       └── dependencies.json       # 知识点依赖关系（边列表）
│
├── tests/
│   ├── test_schemas.py             # Pydantic 模型测试
│   └── test_rag.py                 # RAG 逻辑测试
│
└── docs/
    ├── A3_需求分析与技术方案.md
    └── A1_需求分析与技术方案.md
```

---

## 快速开始

### 前置要求

- Python 3.11+
- （可选）PostgreSQL 14+，不配置则自动使用 SQLite

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制下方内容新建 `.env` 文件并填入 API Key（详见[环境变量](#环境变量)一节）：

```bash
cp .env.example .env   # 或手动创建
```

### 3. 启动后端

```bash
uvicorn backend.main:app --reload --port 8000
```

启动后访问 `http://localhost:8000/docs` 查看自动生成的 API 文档。

### 4. 启动前端

```bash
streamlit run streamlit_app/app.py
```

默认在 `http://localhost:8501` 打开。

### 5. 索引知识库（首次运行）

将课程文档放入 `knowledge_base/ai_intro/chapters/`，然后执行：

```bash
python -c "
import asyncio
from backend.db.vector import init_vector_db
from backend.rag.indexer import index_directory

init_vector_db()
asyncio.run(index_directory('knowledge_base/ai_intro/chapters'))
print('索引完成')
"
```

### 6. 运行测试

```bash
pytest tests/ -v
```

---

## 环境变量

| 变量名 | 必填 | 默认值 | 说明 |
|--------|------|--------|------|
| `SPARK_API_KEY` | **是** | — | 讯飞星火 API Key |
| `SPARK_BASE_URL` | 否 | `https://spark-api-open.xf-yun.com/v1` | 讯飞星火接口地址 |
| `SPARK_MODEL` | 否 | `generalv3.5` | 讯飞星火模型版本 |
| `DATABASE_URL` | 否 | `sqlite+aiosqlite:///./dev.db` | 数据库连接串（PostgreSQL 格式：`postgresql+asyncpg://user:pass@host/db`） |
| `CHROMA_PERSIST_DIR` | 否 | `./chroma_data` | ChromaDB 持久化目录 |
| `CHROMA_COLLECTION` | 否 | `knowledge_base` | 默认向量集合名 |
| `USE_SPARK_EMBEDDING` | 否 | `false` | `true` 则调用讯飞嵌入 API，否则使用本地 BGE-M3 |
| `DB_ECHO` | 否 | `false` | `true` 则打印 SQL 日志 |

---

## API 文档

后端启动后访问 `http://localhost:8000/docs`（Swagger UI）或 `http://localhost:8000/redoc`。

主要端点概览：

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `POST` | `/auth/register` | 注册 |
| `POST` | `/auth/login` | 登录，返回 JWT |
| `GET` | `/profile` | 获取当前画像 |
| `PUT` | `/profile` | 更新画像 |
| `POST` | `/chat/{session_id}` | 向 Agent 发送消息（支持 `?stream=true` SSE） |
| `GET` | `/kg/graph` | 获取知识图谱子图 |
| `POST` | `/generate` | 触发资源生成（异步） |
| `GET` | `/generate/{task_id}/status` | 轮询生成进度 |
| `GET` | `/resources` | 列举资源（支持类型/知识点过滤） |
| `POST` | `/quiz/submit` | 提交答题，返回批改结果 |
| `GET` | `/pathways` | 获取学习路径 |
| `POST` | `/records` | 记录学习行为 |

---

## 数据库设计

共 13 张表，核心关系如下：

```
user
 ├── chat_session          (1:N)
 ├── student_profile       (1:1)
 │    └── profile_history  (1:N，版本快照)
 ├── learning_path         (1:N)
 │    └── learning_path_item → kg_node
 ├── resource_meta         (1:N)
 │    ├── generation_task   (异步任务追踪)
 │    ├── quiz_item
 │    │    └── quiz_attempt (答题记录)
 │    └── learning_record   (学习行为)
kg_node ←→ kg_edge          (自关联，知识图谱)
```

详细 DDL 及数据样例见 [`docs/A3_需求分析与技术方案.md`](docs/需求分析与技术方案/A3_需求分析与技术方案.md) 第 4.4 节。

---

## 知识图谱

节点共 5 层类型，边共 4 种关系：

```
节点类型（由粗到细）
Course → Chapter → KnowledgePoint → SubPoint → Concept

边关系
IS_PART_OF  父子从属（子 → 父）
REQUIRES    先修依赖（后 → 前）
RELATED_TO  横向关联
CONTAINS    包含具体概念
```

知识点数据存储于 `knowledge_base/<course>/knowledge_points.json` 和 `dependencies.json`，启动时可通过脚本批量导入数据库。

---

## 开发指南

### 实现一个新的 Agent

1. 在 `backend/agents/` 中新建 `xxx_agent.py`，定义 `async def run(state: AgentState) -> AgentState`
2. 在 `backend/agents/graph.py` 中注册节点并添加边：
   ```python
   graph.add_node("xxx_agent", xxx_agent.run)
   graph.add_edge("planner_agent", "xxx_agent")
   ```
3. 在 `backend/main.py` 导入（若需独立 API 端点）

### 添加新资源类型

1. 在 `backend/models/schemas.py` 的 `ResourceType` 枚举中添加新值
2. 新建对应的 Agent 文件
3. 在 `planner_agent.route_by_resource_type` 的路由映射中添加
4. 在 `streamlit_app/components/resource_card.py` 的 `_render_content` 中添加渲染逻辑

### 切换向量数据库

仅需替换 `backend/db/vector.py` 的实现，保持 `upsert_documents` / `query_documents` / `delete_documents` 接口签名不变，所有上层代码无需修改。
