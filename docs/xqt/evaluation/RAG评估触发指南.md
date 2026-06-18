# RAG 评估日志触发指南

> 两份测试文件: `tests/test_rag_eval_logs.py`（mock 评估框架）| `tests/test_rag_system_eval.py`（真实 RAG 系统评测）

---

## 1. 测试文件对比

| | test_rag_eval_logs.py | test_rag_system_eval.py |
|---|---|---|
| **用途** | 测试评估框架本身 | 用评估系统评测当前 RAG 质量 |
| **检索数据** | Mock（内置中文场景） | 真实 retriever（需向量库有数据） |
| **LLM 调用** | Mock（无 API 费用） | 真实 LLM（消耗 API credits） |
| **依赖** | 无 | PostgreSQL + pgvector + 已索引文档 |
| **适合时机** | 随时运行，CI/CD | 上传文档后，想了解 RAG 效果时 |

---

## 2. 真实 RAG 系统评测（test_rag_system_eval.py）

### 2.1 概述

`tests/test_rag_system_eval.py` 用评估系统来评测当前 RAG 的检索+生成质量：

```
向量库知识点 → 真实 retriever 检索 → LLM 生成 → Judge 四维评估 → 报告
```

**两个测试类：**

| 测试类 | 消耗 API | 说明 |
|--------|----------|------|
| `TestRetrievalQuality` | 仅 embedding | 检索命中率、分数分布、延迟 |
| `TestFullRAGSystemEval` | embedding + 生成 + Judge | faithfulness、hallucination、completeness、P@5、引用准确性 |

### 2.2 前置步骤

```bash
# 1. 启动后端服务
uvicorn backend.main:app --reload --port 8000

# 2. 打开浏览器 → http://localhost:8000/app
#    上传知识文档（PDF/DOCX/Markdown/TXT），系统会自动构建向量索引

# 3. 确认向量库已有数据（可选）
python -m pytest tests/test_rag_system_eval.py::TestRetrievalQuality::test_db_stats -v -s
```

### 2.3 运行评测

```bash
# 仅检索质量评测（无 LLM Judge，仅消耗 embedding API）
python -m pytest tests/test_rag_system_eval.py::TestRetrievalQuality -v -s

# 完整端到端评测（检索 + 生成 + Judge，消耗 API credits）
python -m pytest tests/test_rag_system_eval.py::TestFullRAGSystemEval -v -s

# 全部运行
python -m pytest tests/test_rag_system_eval.py -v -s
```

### 2.4 自定义查询

编辑 `tests/test_rag_system_eval.py` 顶部的 `CUSTOM_QUERIES` 列表：

```python
CUSTOM_QUERIES: list[str] = [
    "什么是机器学习中的梯度下降？",
    "神经网络的激活函数有哪些？各自优缺点是什么？",
]
```

如果留空，脚本会自动从数据库的 section 字段中抽取知识点作为查询。

### 2.5 输出示例

```
==============================================================
检索质量汇总
==============================================================
查询命中率 (Hit Rate):     100%  (5/5)
平均分数:                  0.823
分数 P50:                  0.850
分数 P95:                  0.920
平均检索延迟:              45ms
==============================================================

最终评估汇总 (5 个查询)
==============================================================
Avg Faithfulness:  0.823
Avg Hallucination: 0.177
Avg Completeness:  0.640
[0] 梯度下降          faith=0.85 hallu=0.15 cover=0.60
[1] 激活函数          faith=0.90 hallu=0.10 cover=0.70
...
```

---

## 3. Mock 评估框架测试（test_rag_eval_logs.py）

### 3.1 概述

`tests/test_rag_eval_logs.py` 使用 mock 数据测试评估系统框架本身：

```
Collector → Judge → Reporter → 日志文件写入 (logs/rag_*.md + logs/rag_*.json)
```

使用 **mock LLM**，不产生 API 费用，无需数据库。

### 3.2 运行方式

```bash
# 全部测试
pytest tests/test_rag_eval_logs.py -v -s

# 核心端到端测试（生成完整日志文件）
pytest tests/test_rag_eval_logs.py::TestRAGEvalLogs::test_full_eval_pipeline_with_logs -v -s

# 报告内容格式验证
pytest tests/test_rag_eval_logs.py::TestRAGEvalLogs::test_report_content_validity -v -s

# 指标计算正确性验证
pytest tests/test_rag_eval_logs.py::TestRAGEvalLogs::test_metrics_in_report -v -s

# 日志文件格式验证（JSON + Markdown）
pytest tests/test_rag_eval_logs.py::TestRAGEvalLogs::test_log_file_format -v -s
```

无需额外配置。测试不依赖数据库、LLM API 密钥或外部服务。

### 3.3 评估场景 (5 个)

| 场景 | 知识点 | 质量等级 | 特点 |
|------|--------|----------|------|
| 0 | 梯度下降 | high | 完整引用标注 `[1][2][3]`，5 chunks |
| 1 | 神经网络激活函数 | high | 完整引用标注 `[1][2][3]`，含无关 chunk |
| 2 | 过拟合与正则化 | low | 生成内容过于简略（55 字符），完整度应低 |
| 3 | CNN 卷积神经网络 | high | 完整引用标注 `[1][2][3]` |
| 4 | Transformer 注意力机制 | low | 生成内容极其简略（40 字符），完整度应低 |

### 3.4 Mock 机制

- `_build_mock_chat_completion()` 根据 prompt 关键词路由到对应的 mock 响应
- `MockRetrievedChunk` 模拟 `backend.rag.retriever.RetrievedChunk` 的接口
- Judge 评估通过 `patch("backend.evaluation.judge.chat_completion", mock_llm)` 注入

Mock LLM 返回的固定评分：
- faithfulness: **0.85**
- completeness: **0.60** (aspects=5, covered=2)
- chunk_relevance: **2** (高度相关)
- citation_accuracy: **accurate**

---

### 3.5 日志输出

#### 输出位置

运行后，`logs/` 目录下生成以下文件：

```
logs/
├── rag_<知识点>_<时间戳>.md        # 每个场景的单次评估报告（Markdown）
├── rag_<知识点>_<时间戳>.json      # 每个场景的单次评估数据（JSON）
├── rag_scene_<N>_<知识点>_<时间戳>.md   # write_eval_result 输出的场景报告
├── rag_scene_<N>_<知识点>_<时间戳>.json
├── rag_comparison_test_<时间戳>.md      # 汇总报告（Markdown）
└── rag_comparison_test_<时间戳>.json    # 汇总报告（JSON）
```

#### Markdown 报告内容

单次评估报告（`rag_<知识点>_*.md`）包含：
- 查询信息（query、kp_name、时间戳）
- 检索质量汇总（P@5、MRR、NDCG@5、Hit Rate、Score P50）
- 生成质量汇总（Faithfulness、Hallucination Rate、Concept Coverage）
- 逐 chunk 相关性评分
- Faithfulness 逐句验证结果
- 引用准确性检查结果

汇总报告（`rag_comparison_test_*.md`）包含：
- 基本统计（总查询数、时间范围）
- 检索质量表格（含参考值和达标状态）
- 生成质量表格
- 系统效率表格（P50/P95 延迟）
- 变化趋势（与上期对比）

#### JSON 报告内容

JSON 文件包含完整的结构化数据，适合程序化处理或接入监控系统。

---

## 4. 在项目代码中手动触发评估

如果需要在真实业务流程中触发评估日志，参考以下关键调用点：

### 5.1 接入点: `backend/services/generation.py`

```python
from backend.evaluation.collector import get_collector
from backend.evaluation.judge import get_judge
from backend.evaluation.reporter import write_eval_result

# --- 检索阶段 ---
collector = get_collector()
collector.start_query(query=query, kp_name=kp_name, user_id=user_id, session_id=session_id)
collector.record_retrieval(
    scores=scores,
    chunk_ids=chunk_ids,
    chunk_texts=chunk_texts,
    doc_ids=doc_ids,
    embedding_latency_ms=emb_ms,
    db_query_latency_ms=db_ms,
)

# --- 生成阶段 ---
collector.record_generation(
    agent_type="doc_agent",
    draft_length=len(content),
    generation_latency_ms=gen_ms,
    safety_passed=True,
)

# --- 评估阶段 ---
judge = get_judge()
result = await judge.evaluate_full(
    query=query,
    kp_name=kp_name,
    retrieved_chunks=retrieved_chunks,
    generated_content=content,
    include_citation_check=has_citations,
)

# --- 写入日志 ---
write_eval_result(result, label=kp_name)

# --- 刷新 Collector ---
gen_record = collector.flush()
```

### 4.2 查看 Collector 状态

```python
from backend.evaluation.collector import get_collector

collector = get_collector()
records = collector.get_recent_records(limit=20)
for r in records:
    print(f"kp={r.kp_name}, faith={r.faithfulness_score}, P@5={...}")
```

### 4.3 生成周期性汇总报告

```python
from backend.evaluation.reporter import RAGReporter
from backend.evaluation.collector import get_collector

collector = get_collector()
records = collector.get_recent_records(limit=100)

reporter = RAGReporter()
report = reporter.generate_report(records)

# 输出 Summary
print(reporter.to_summary(report))

# 输出 Markdown
print(reporter.to_markdown(report))
```

---

## 5. 相关文件索引

| 文件 | 职责 |
|------|------|
| `tests/test_rag_system_eval.py` | **真实 RAG 系统评测**（检索+生成+Judge） |
| `tests/test_rag_eval_logs.py` | Mock 评估框架触发测试 |
| `backend/evaluation/collector.py` | 检索+生成快照采集 |
| `backend/evaluation/judge.py` | LLM-as-Judge 四维度评估 |
| `backend/evaluation/reporter.py` | 报告生成 + 日志写入 |
| `backend/evaluation/models.py` | 评估数据模型 |
| `backend/evaluation/metrics.py` | 检索指标计算 |
| `backend/rag/retriever.py` | RAG 检索器 |
| `docs/design/rag/RAG_EVALUATION_SYSTEM_DESIGN.md` | 评估系统设计文档 |
| `docs/design/rag/RAG_EVALUATION_SYSTEM.md` | 评估系统使用指南 |
