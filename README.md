# 个性化资源生成与学习多智能体系统

第十五届中国软件杯大学生软件设计大赛 · A3 赛题
出题企业：科大讯飞股份有限公司

---

## 项目简介

本系统面向高等教育场景，以**人工智能导论**课程为切入点，通过多智能体协同为学生自动生成个性化学习资源，并根据学习行为动态更新学生画像和学习路径。

核心能力：
- 对话式学习画像构建（8 个维度，自然语言采集，无需填表）
- 5 种个性化资源自动生成：知识讲解文档、思维导图、练习题、代码案例、要点总结
- 基于知识图谱的学习路径规划与资源推送
- RAG 增强生成，内容溯源至课程知识库，防止幻觉

---

## 技术架构

```
Streamlit 前端（5 页面）
        ↕ REST API
FastAPI 后端
  ├── LangGraph 多智能体编排（9 个 Agent）
  ├── RAG 检索层（ChromaDB + BGE-M3）
  └── 数据层（SQLAlchemy + SQLite/MySQL）
```

**主要依赖**

| 层次 | 技术 |
|------|------|
| 前端 | Streamlit、ECharts |
| 后端 | FastAPI、Uvicorn |
| Agent 编排 | LangGraph |
| LLM | 讯飞星火 API（OpenAI 兼容） |
| Embedding | BGE-M3（本地）/ 讯飞 Embedding API |
| 向量库 | ChromaDB（本地持久化） |
| 关系库 | SQLite（开发）/ MySQL（生产） |

---

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境

复制配置模板并填写 API Key：

```bash
cp configs/config.yaml.example configs/config.yaml
```

`configs/config.yaml` 中需要设置：

```yaml
llm:
  api_key: "your_spark_api_key"   # 讯飞星火 API Key
database:
  url: "sqlite+aiosqlite:///./dev.db"  # 开发环境用 SQLite
```

或通过环境变量覆盖：

```bash
export LLM_API_KEY=your_spark_api_key
export DB_PASSWORD=your_db_password   # 仅 MySQL 模式需要
```

### 3. 构建知识库索引

```bash
python -m backend.rag.indexer
```

### 4. 启动后端

```bash
uvicorn backend.main:app --reload --port 8000
```

### 5. 启动前端

```bash
streamlit run streamlit_app/app.py
```

访问 `http://localhost:8501`

---

## 项目结构

```
softbei/
├── backend/
│   ├── main.py              # FastAPI 入口，15+ 个路由
│   ├── agents/
│   │   ├── graph.py         # LangGraph 状态机（9 节点）
│   │   ├── profile_agent.py # 画像提取 + 完整性路由
│   │   ├── planner_agent.py # 意图分析，决定资源类型和知识点
│   │   ├── doc/mindmap/quiz/code/summary_agent.py
│   │   ├── safety_agent.py  # 内容安全校验
│   │   └── recommend_agent.py
│   ├── rag/
│   │   ├── loader.py        # PDF/DOCX/Markdown 解析与分块
│   │   ├── indexer.py       # 向量化入库（并发 8 线程）
│   │   └── retriever.py     # 语义检索 + 引用格式化
│   ├── services/
│   │   ├── llm.py           # LLM 统一调用层（多 provider + 重试）
│   │   └── profile.py       # 画像 CRUD
│   ├── db/
│   │   ├── models.py        # 13 张 ORM 表
│   │   └── database.py      # 异步连接池
│   └── models/schemas.py    # 所有 Pydantic v2 模型
├── streamlit_app/
│   ├── app.py               # 全局配置、侧边栏、onboarding 引导
│   ├── pages/
│   │   ├── 1_profile.py     # 画像查看与编辑
│   │   ├── 2_generate.py    # 资源生成（异步任务 + 进度轮询）
│   │   ├── 3_pathway.py     # 知识图谱可视化 + 学习路径
│   │   ├── 4_library.py     # 资源库浏览与管理
│   │   └── 5_evaluate.py    # 测验与评估
│   └── components/
│       ├── mindmap.py       # ECharts 思维导图组件
│       ├── quiz_card.py     # 练习题卡片
│       └── resource_card.py
├── knowledge_base/
│   └── ai_intro/            # 人工智能导论课程知识库
│       ├── knowledge_points.json
│       └── dependencies.json
├── configs/
│   ├── config.yaml          # 运行时配置（不提交）
│   └── config.yaml.example  # 配置模板
└── tests/
    ├── test_schemas.py      # 无外部依赖，可直接运行
    └── test_rag.py          # 测试文档分块逻辑
```

---

## Agent 流水线

每次用户发送消息，LangGraph 按以下拓扑执行：

```
profile_agent
  ├─ 画像不足 → 生成追问 → END   （多轮对话累积画像）
  └─ 画像足够 → planner_agent
                ↙  ↙  ↙  ↘  ↘
           doc mindmap quiz code summary
                ↘  ↘  ↘  ↙  ↙
                 safety_agent
                      ↓
               recommend_agent → END
```

`profile_agent` 在每轮对话中持续提取和累积画像字段，画像达到最低要求（有学习目标或知识基础信息）后才放行到资源生成流程。

---

## 运行测试

```bash
# 无外部依赖，直接运行
pytest tests/test_schemas.py tests/test_rag.py -v
```

---

## AI 工具使用说明

本项目开发过程中使用了以下科大讯飞相关工具：

- **讯飞星火大模型 API**：系统主力 LLM，用于所有 Agent 的内容生成、画像提取和意图分析
- **讯飞 Embedding API**（可选）：通过 `USE_SPARK_EMBEDDING=true` 启用，替代本地 BGE-M3

---

## 提交物清单

- [ ] 演示 PPT
- [ ] 完整源码 + 知识库数据集 + 配置文件
- [ ] 智能体演示视频（≤7 分钟）
- [ ] 配套文档（需求分析 + 技术开发说明）
- [ ] AI Coding 工具使用说明
