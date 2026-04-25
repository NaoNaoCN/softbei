# 项目任务清单与优化建议

**最后更新**: 2026-04-25
**项目**: A3 个性化学习多智能体系统

---

## 一、优先级分类

### P0 — 阻断问题（功能完全不可用）

| # | 任务 | 状态 | 描述 | 文件 |
|---|---|---|---|---|
| P0-1 | **实现后台资源生成任务** | ✅ 已完成 | `run_generation` 已实现，背景任务正常执行 | `backend/services/generation.py` |
| P0-2 | **生成内容持久化到 ResourceMeta** | ✅ 已完成 | `doc/summary/code` 写 content，`mindmap` 写 content_json，`quiz` 写 quiz_item 表 | `backend/services/generation.py` |

### P1 — 核心功能缺失（功能不完整）

| # | 任务 | 状态 | 描述 | 文件 |
|---|---|---|---|---|
| P1-1 | **实现 Spark embedding** | ❌ 未完成 | `_spark_embedding` 直接 `raise NotImplementedError` | `backend/services/llm.py` |
| P1-2 | **本地 embedding 模型缓存** | ✅ 已完成 | `_get_embedding_model()` 单例模式，不再每次重新加载模型 | `backend/services/llm.py` |
| P1-3 | **聊天消息持久化** | ❌ 未完成 | `POST /chat/{session_id}` 对话历史未写入 `ChatMessage` 表 | `backend/main.py:177` |
| P1-4 | **KG 节点数据导入** | ❌ 未完成 | 知识图谱节点/边无批量导入接口，`/kg/graph` 返回空 | `backend/rag/` |

### P2 — 明显 Bug

| # | 任务 | 状态 | 描述 | 文件 |
|---|---|---|---|---|
| P2-1 | **JWT_SECRET 硬编码** | ✅ 已完成 | 已迁移到 `configs/config.yaml` + `.env`，代码中无硬编码 | `backend/main.py:57` → `backend/config.py` |
| P2-2 | **pathway.py kp_name 回退错误** | ✅ 已完成 | 已在 `_item_to_out()` 中正确取 `item.kp.name` | `backend/services/pathway.py:207` |
| P2-3 | **LearningRecord.action 写死为 "view"** | ❌ 未完成 | `record_learning` 硬编码 `"action": "view"`，忽略传入值 | `backend/services/resource.py:175` |
| P2-4 | **多选题答案批改逻辑** | ❌ 未完成 | 多选题答案列表转字符串后与数据库不匹配 | `backend/main.py:365` |
| P2-5 | **前端静默失败** | ⚠️ 部分修复 | `col_refresh` 未定义、统计 API 修复、`cognitive_style` 索引已修复 | `streamlit_app/pages/*.py` |

### P3 — 体验与稳定性

| # | 任务 | 状态 | 描述 | 文件 |
|---|---|---|---|---|
| P3-1 | **LLM 调用日志/计费** | ❌ 未完成 | `response.usage` 未记录，无法统计 token 用量 | `backend/services/llm.py` |
| P3-2 | **用户画像推荐 API** | ❌ 未完成 | Agent 推荐结果仅存在 `state.metadata`，未暴露给前端 | `backend/main.py` |
| P3-3 | **单元测试覆盖率** | ⚠️ 部分完成 | db/、agents/、schemas、crud、rag 已有测试；services/、main.py 仍缺失 | `tests/` |
| P3-4 | **前端 session_state 清理** | ⚠️ 部分修复 | 退出登录只清理了 6 个 key，部分 key 未清理 | `streamlit_app/app.py:100` |

### P4 — 扩展功能

| # | 任务 | 状态 | 描述 |
|---|---|---|---|
| P4-1 | **Docker 部署** | ❌ 未完成 | 无 Dockerfile / docker-compose.yml |
| P4-2 | **CI/CD** | ❌ 未完成 | 无 GitHub Actions 流水线 |
| P4-3 | **Redis 会话缓存** | ❌ 未完成 | 无缓存层，高并发 DB 压力大 |
| P4-4 | **API 鉴权中间件** | ❌ 未完成 | 除 login 外所有 API 无 token 验证 |
| P4-5 | **CORS 限制** | ❌ 未完成 | `allow_origins=["*"]` 生产环境应限定 |

---

## 二、已完成的优化（供参考）

### 配置体系重构
- `config.yaml` 所有敏感值改为 `${ENV_VAR}` 引用，可安全提交到 git
- `backend/config.py` 统一管理所有配置，无零散硬编码
- `.env.example` 作为环境变量 KEY 清单
- `llm.py` 所有 provider 配置从 `config` 读取，移除了零散的 `os.environ` 调用

### Embedding 模型缓存
```python
_embedding_model = None

def _get_embedding_model():
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(config.embedding.model)
    return _embedding_model
```

### 单元测试覆盖（2026-04-25 完成）

**已覆盖模块（180 个测试）：**

| 模块 | 测试文件 | 测试数 |
|---|---|---|
| `backend/db/database.py` | `test_database.py` | 5 |
| `backend/db/models.py` | `test_models.py` | 14 |
| `backend/db/vector.py` | `test_vector.py` | 10 |
| `backend/db/crud.py` | `test_crud.py` | 54 |
| `backend/rag/` | `test_rag.py` | ~12 |
| `backend/models/schemas.py` | `test_schemas.py` | ~9 |
| `backend/agents/graph.py` | `test_graph.py` | 8 |
| `backend/agents/profile_agent.py` | `test_profile_agent.py` | 13 |
| `backend/agents/planner_agent.py` | `test_planner_agent.py` | 10 |
| `backend/agents/doc_agent.py` | `test_doc_agent.py` | 4 |
| `backend/agents/mindmap_agent.py` | `test_mindmap_agent.py` | 4 |
| `backend/agents/quiz_agent.py` | `test_quiz_agent.py` | 7 |
| `backend/agents/code_agent.py` | `test_code_agent.py` | 4 |
| `backend/agents/summary_agent.py` | `test_summary_agent.py` | 4 |
| `backend/agents/safety_agent.py` | `test_safety_agent.py` | 7 |
| `backend/agents/recommend_agent.py` | `test_recommend_agent.py` | 7 |

**仍缺失测试：**
- `backend/services/llm.py`（embedding、chat_completion）
- `backend/services/profile.py`
- `backend/services/resource.py`
- `backend/services/pathway.py`
- `backend/services/generation.py`
- `backend/main.py`（API 路由）

---

## 三、待修复 Bug 说明

### P2-3: LearningRecord.action 写死

`backend/services/resource.py:175` 硬编码 `"action": "view"`，应改为：
```python
"action": getattr(data, "action", "view") or "view",
```

### P2-4: 多选题批改

`backend/main.py:submit_quiz` 批改逻辑应处理列表答案：
```python
if isinstance(body.user_answer, list):
    user_answer_str = ",".join(sorted(body.user_answer)).lower()
```

---

## 四、当前系统架构（供参考）

```
[Streamlit Frontend] --HTTP--> [FastAPI Backend] --SQLAlchemy--> [MySQL]
      |                           |                         + ChromaDB
      |                           +-- [LangGraph Agent] --RAG--> [docs/]
      |                           |                              ( KGNode/KGEdge )
      |                           +-- [LLM Service] ---------> [Spark/DeepSeek/Qwen]
```

## 五、数据库模型清单（13张表）

| 表名 | 用途 |
|---|---|
| `user` | 用户账户 |
| `student_profile` | 学生画像 |
| `profile_history` | 画像变更历史 |
| `chat_session` | 对话会话 |
| `chat_message` | 对话消息（未持久化） |
| `kg_node` | 知识图谱节点 |
| `kg_edge` | 知识图谱边 |
| `resource_meta` | 资源元数据 |
| `generation_task` | 生成任务状态 |
| `quiz_item` | 测验题目 |
| `quiz_attempt` | 答题记录 |
| `learning_path` | 学习路径 |
| `learning_path_item` | 路径知识点项 |
| `learning_record` | 学习记录 |
