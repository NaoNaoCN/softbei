# 项目实现状态总览

**最后更新**: 2026-04-20

**总体进度**: 69/104 (66%)

---

## 📊 统计概览

| 模块 | 已实现 | 部分实现 | 未实现 | 完成率 |
|------|--------|----------|--------|--------|
| FastAPI 路由 | 5 | 1 | 12 | 28% |
| Agent 节点 | 5 | 0 | 11 | 31% |
| Profile 服务 | 0 | 0 | 5 | 0% |
| Resource 服务 | 0 | 0 | 8 | 0% |
| LLM 服务 | 6 | 0 | 2 | 75% |
| 向量数据库 | 7 | 0 | 0 | 100% |
| RAG 检索器 | 5 | 0 | 0 | 100% |
| RAG 加载器 | 4 | 0 | 4 | 50% |
| RAG 索引器 | 4 | 0 | 0 | 100% |
| 数据库模型 | 14 | 0 | 0 | 100% |

---

## 1. FastAPI 路由 (backend/main.py)

| 端点 | 方法 | 状态 | 备注 |
|------|------|------|------|
| `/health` | GET | ✅ | 系统健康检查 |
| `/auth/register` | POST | ✅ | 用户注册（含密码哈希） |
| `/auth/login` | POST | ❌ | 需实现 JWT 生成 |
| `/profile` | GET | ✅ | 调用 profile_svc.get_profile() |
| `/profile` | PUT | ✅ | 调用 profile_svc.create_or_update_profile() |
| `/profile/history` | GET | ✅ | 调用 profile_svc.get_profile_history() |
| `/chat/{session_id}` | POST | ✅ | 支持 SSE 流式和普通模式 |
| `/chat/sessions` | GET | ❌ | 需查询 chat_session 表 |
| `/kg/graph` | GET | ❌ | 需构建 kg_node + kg_edge 子图 |
| `/generate` | POST | ⚠️ | 创建任务，后台执行逻辑待补全 |
| `/generate/{task_id}/status` | GET | ✅ | 调用 resource_svc.get_task_status() |
| `/resources` | GET | ✅ | 调用 resource_svc.list_resources() |
| `/resources/{resource_id}` | GET | ✅ | 调用 resource_svc.get_resource() |
| `/resources/{resource_id}` | DELETE | ✅ | 调用 resource_svc.delete_resource() |
| `/resources/{resource_id}/quiz` | GET | ❌ | 需查询 quiz_item 表 |
| `/quiz/submit` | POST | ❌ | 需评分并写入 quiz_attempt |
| `/pathways` | GET | ❌ | 需查询 learning_path 表 |
| `/records` | POST | ✅ | 调用 resource_svc.record_learning() |

---

## 2. Agent 节点 (backend/agents/)

| 文件 | 函数 | 状态 | 备注 |
|------|------|------|------|
| graph.py | `build_graph()` | ✅ | LangGraph 拓扑完整 |
| graph.py | `get_graph()` | ✅ | 返回编译后图实例 |
| graph.py | `invoke()` | ✅ | 同步执行完整图 |
| graph.py | `stream_invoke()` | ✅ | 流式执行图事件 |
| planner_agent.py | `run()` | ❌ | 需实现意图分析 |
| planner_agent.py | `route_by_resource_type()` | ✅ | 条件路由逻辑完整 |
| profile_agent.py | `run()` | ❌ | 需从对话中提取画像 |
| profile_agent.py | `should_update_profile()` | ❌ | 需实现关键词匹配 |
| doc_agent.py | `run()` | ❌ | 需 RAG 检索 + LLM 生成 |
| mindmap_agent.py | `run()` | ❌ | 需生成 ECharts JSON |
| quiz_agent.py | `run()` | ❌ | 需生成测验题目 |
| quiz_agent.py | `save_quiz_items()` | ❌ | 需批量写入 quiz_item |
| code_agent.py | `run()` | ❌ | 需代码示例生成 |
| summary_agent.py | `run()` | ❌ | 需摘要生成 |
| safety_agent.py | `run()` | ❌ | 需内容幻觉检测 |
| safety_agent.py | `should_skip_safety()` | ✅ | 检查 draft_content 是否存在 |
| recommend_agent.py | `run()` | ❌ | 需 KG 查询 + 推荐逻辑 |

---

## 3. Profile 服务 (backend/services/profile.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `get_profile()` | ❌ | 需查询 student_profile 表 |
| `create_or_update_profile()` | ❌ | 需 upsert + 写入 profile_history |
| `get_profile_history()` | ❌ | 需查询 profile_history 表 |
| `merge_chat_updates()` | ❌ | 需将对话更新合并到画像 |
| `build_profile_context()` | ❌ | 需将画像格式化为 prompt 上下文 |

---

## 4. Resource 服务 (backend/services/resource.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `get_resource()` | ❌ | 需查询 resource_meta 表 |
| `list_resources()` | ❌ | 需分页查询（含过滤） |
| `delete_resource()` | ❌ | 需删除资源及级联数据 |
| `create_generation_task()` | ❌ | 需写入 generation_task 记录 |
| `get_task_status()` | ❌ | 需查询 generation_task 表 |
| `update_task_progress()` | ❌ | 需更新任务进度/状态 |
| `record_learning()` | ❌ | 需写入 learning_record |
| `list_learning_records()` | ❌ | 需查询 learning_record 表 |

---

## 5. LLM 服务 (backend/services/llm.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `chat_completion()` | ✅ | 含重试 + Qwen 配额自动切换 |
| `stream_chat_completion()` | ✅ | 流式版本，含配额处理 |
| `get_embedding()` | ✅ | 路由到本地 BGE-M3 或 Spark API |
| `_local_embedding()` | ✅ | 使用 sentence-transformers BGE-M3 |
| `_spark_embedding()` | ❌ | 需调用 Spark Embedding API |
| `_make_client()` | ✅ | OpenAI 兼容客户端工厂 |
| `_is_quota_error()` | ✅ | 检测 Qwen 配额耗尽 |
| `_QwenModelPool` | ✅ | 模型池含耗尽追踪 |

---

## 6. 向量数据库 (backend/db/vector.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `init_vector_db()` | ✅ | 初始化 ChromaDB 持久化客户端 |
| `get_collection()` | ✅ | 返回默认集合 |
| `get_or_create_collection()` | ✅ | 获取或创建命名集合 |
| `upsert_documents()` | ✅ | 批量 upsert 含 embedding |
| `query_documents()` | ✅ | 向量相似度搜索 |
| `delete_documents()` | ✅ | 按 ID 删除 |
| `health_check()` | ✅ | 检查向量库可用性 |

---

## 7. RAG 管道

### 加载器 (backend/rag/loader.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `load_file()` | ✅ | 文件格式分发器 |
| `load_directory()` | ✅ | 递归目录扫描 |
| `split_text()` | ✅ | 含 overlap 的文本分块 |
| `_load_pdf()` | ❌ | 需 pypdf 解析 |
| `_load_docx()` | ❌ | 需 python-docx 解析 |
| `_load_markdown()` | ❌ | 需 Markdown 章节分割 |
| `_load_txt()` | ❌ | 需文本文件加载 |
| `TextChunk` | ✅ | 文本块数据结构 |

### 检索器 (backend/rag/retriever.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `retrieve()` | ✅ | 语义搜索含阈值过滤 |
| `retrieve_by_kp()` | ✅ | 知识点专项检索 |
| `format_context()` | ✅ | 格式化结果含来源引用 |
| `_parse_results()` | ✅ | 转换 ChromaDB 结果 |
| `RetrievedChunk` | ✅ | 检索块数据结构 |

### 索引器 (backend/rag/indexer.py)

| 函数 | 状态 | 备注 |
|------|------|------|
| `index_chunks()` | ✅ | 批量 embedding + 向量库 upsert |
| `index_file()` | ✅ | 加载文件并索引 |
| `index_directory()` | ✅ | 递归目录索引 |
| `_embed_batch()` | ✅ | 并发 embedding（含信号量） |

---

## 8. 数据库模型 (backend/db/models.py)

| 表 | 状态 | 备注 |
|----|------|------|
| `user` | ✅ | 用户账户 |
| `student_profile` | ✅ | 学生画像 |
| `profile_history` | ✅ | 画像版本历史 |
| `chat_session` | ✅ | 对话会话 |
| `chat_message` | ✅ | 对话消息 |
| `kg_node` | ✅ | 知识图谱节点 |
| `kg_edge` | ✅ | 知识图谱边 |
| `resource_meta` | ✅ | 学习资源元数据 |
| `generation_task` | ✅ | 异步生成任务追踪 |
| `quiz_item` | ✅ | 测验题目 |
| `quiz_attempt` | ✅ | 测验提交记录 |
| `learning_path` | ✅ | 个性化学习路径 |
| `learning_path_item` | ✅ | 路径条目含进度 |
| `learning_record` | ✅ | 学习活动日志 |

---

## 🎯 关键缺口

1. **所有数据库 CRUD 操作** (profile, resource 服务) - 0% 完成
2. **所有 Agent 节点逻辑**（除路由外） - 31% 完成
3. **文档加载器** (PDF, DOCX, Markdown, TXT) - 50% 完成
4. **大部分依赖服务的 FastAPI 端点** - 28% 完成

---

## 📝 更新日志

| 日期 | 更新内容 |
|------|----------|
| 2026-04-20 | 初始化实现状态表 |
| 2026-04-20 | 完成 `/auth/register` 端点实现 |
