# RAG 评估系统 v3.0 — 四层递进评估体系

> 最后更新：2026-05-27 | 代码：`backend/evaluation/` | 测试：`tests/test_evaluation_*.py`

---

## 一、一句话概述

这是一个**四层递进的 RAG 质量评估系统**，从每次请求的轻量健康检查（<5ms），到可配采样率的 LLM-as-Judge 评估，到黄金测试集的离线回归检测，到 A/B 实验框架——四层覆盖了从实时监控到深度分析的完整需求。开发阶段默认全量评估（100% 采样），不遗漏任何一条数据。

---

## 二、为什么需要它？— 与 v2.0 的差异

v2.0 是一个面向生产环境的"轻量监控"方案：10% 采样 + 内存存储 + 单 LLM 裁判。在开发阶段存在明显不足：

| v2.0 痛点 | v3.0 改进 |
|-----------|----------|
| 10% 采样：改一个参数要等很久才能看到效果 | **开发模式 100% 采样**：每次请求都评估 |
| 内存存储：服务重启历史全丢 | **PostgreSQL 持久化**：`rag_eval_result` 表 |
| 无测试集：每次评估的知识点随机，无法回归对比 | **黄金测试集**：10 条精选查询，CLI 批量评估 |
| 单 LLM 偏见：无法发现 LLM 自身的打分偏差 | **多 LLM 交叉验证**：Qwen + DeepSeek 互相校验 |
| 无可控实验：改 prompt/config 后不知道效果 | **A/B 实验框架**：同批查询两组对比 |
| 延迟是估算的：60%/40% 硬编码 | **真实分段计时**：embedding/DB query 分别采集 |
| 缺少快速检查：轻量变更也要等 10% 采样 | **健康检查**：每次请求 <5ms，阈值告警 |

---

## 三、四层体系总览

```
Layer 1: 健康检查（每次请求，<5ms）
  ├── 检索空结果率、chunk 分数分布、chunk 数量
  ├── embedding / DB query / 生成延迟
  └── 滑动窗口（100 条）→ 超出阈值 → WARNING 日志

Layer 2: LLM Judge（可配置采样率，开发默认 100%）
  ├── 4 个 Judge：相关性、忠实度、完整度、引用准确性
  ├── 多 LLM 交叉验证（可选，开发调试时启用）
  ├── 结果持久化到 PostgreSQL（rag_eval_result 表）
  └── 异步 fire-and-forget，不阻塞用户请求

Layer 3: 黄金测试集（CLI 按需触发 + 定时自动）
  ├── 10 条精选查询（backend/evaluation/golden_queries.yaml）
  ├── 每条含最低期望分数 + 预期覆盖方面
  ├── 离线批量评估：python -m backend.evaluation.golden --run
  ├── 回归检测：任一度量下降 >10% → 自动告警
  └── 结果存入 logs/golden_report_*.md

Layer 4: A/B 实验框架（开发阶段按需）
  ├── 同批查询分别跑两组 → 统计对比
  ├── 支持 retrieval-only 模式（仅对比检索质量）
  └── 报告自动生成到 logs/ab_report_*.md
```

---

## 四、Layer 1：健康检查

**文件**：`backend/evaluation/health_check.py`

### 设计原则

- **每次请求都采集**，不采样，不跳过
- **不调用 LLM**，纯数值计算，单次 <5ms
- **异常不影响主流程**：所有采集代码包裹在 try/except 中

### 采集指标

| 指标 | 来源 | 用途 |
|------|------|------|
| `n_retrieved` | 检索结果数 | 检测检索是否退化 |
| `n_empty_results` | 是否返回空（0/1） | 空结果率告警 |
| `score_p50 / min / max` | chunk 分数分布 | 检测分数是否异常偏低 |
| `embedding_latency_ms` | 向量化耗时 | 定位性能瓶颈 |
| `db_query_latency_ms` | 数据库查询耗时 | 定位性能瓶颈 |
| `draft_length` | 生成长度 | 检测生成是否异常（过长/过短） |
| `generation_latency_ms` | 生成耗时 | 定位性能瓶颈 |

### 告警阈值

基于最近 100 条记录的滑动窗口：

| 条件 | 告警信息 |
|------|---------|
| 空结果率 > 30% | `[HealthCheck] 空结果率偏高: X%` |
| 平均 P50 分数 < 0.3 | `[HealthCheck] 检索分数偏低` |
| P95 检索延迟 > 5000ms | `[HealthCheck] 检索延迟偏高` |

### 数据采集点

健康检查在 Collector 的 `flush()` 中自动触发：
```
collector.flush()
  └── _record_health_check(record)
       └── health_checker.record(...)
            └── _check_thresholds()  # 每 10 条以上开始检查
```

### API

```python
from backend.evaluation.health_check import health_checker

# 查看最近 20 条
records = health_checker.get_recent(20)

# 获取滑动窗口摘要
summary = health_checker.get_summary()
# {"status": "ok", "sample_count": 95, "empty_result_rate": 0.05, "avg_score_p50": 0.72, ...}
```

---

## 五、Layer 2：LLM Judge

**文件**：`backend/evaluation/judge.py`（增强自 v2.0）

### 采样率

采样率由 `config.evaluation.mode` 决定：

| 模式 | 采样率 | 说明 |
|------|--------|------|
| `development` | `evaluation.sampling.development`（默认 1.0=100%） | 每次请求都评估 |
| `production` | `evaluation.sampling.production`（默认 0.1=10%） | 保持原有行为 |

通过 session_id 哈希做确定性采样：同一 session 的所有轮次要么全评估，要么全不评估。

### 四个 Judge（保持不变）

| Judge | 评什么 | 评分方式 |
|-------|--------|---------|
| 相关性 (Relevance) | 每条 chunk 与查询的相关性 | 0/1/2 三级标注 |
| 忠实度 (Faithfulness) | AI 回答是否有依据 | 逐句标注 supported/unsupported |
| 完整度 (Completeness) | 知识点关键方面是否覆盖 | 两步：生成期望方面 → 逐项评估 |
| 引用准确性 (Citation) | [n] 引用标注是否正确 | accurate/inaccurate/vague |

### 新增：多 LLM 交叉验证

**文件**：`backend/evaluation/judge.py` — `RAGJudge._cross_validate()`

当 `config.evaluation.cross_validation.enabled = true` 时，在完成一轮 Judge（Qwen）后，自动启动第二轮（DeepSeek），仅对**忠实度和完整度**两个最关键维度重新打分。

若两轮评分的差异 > 0.3，标记 `cross_validation_disagreement = true`，提示人工抽检。

```
配置示例：
evaluation:
  cross_validation:
    enabled: true
    providers: ["qwen", "deepseek"]
```

注意：交叉验证会使 LLM 调用量翻倍（4 次 → 6 次），仅在开发调试关键变更时启用。

### 新增：持久化到 PostgreSQL

**文件**：`backend/evaluation/collector.py` — `RAGEvalCollector._persist_to_db()`

当 `config.evaluation.storage.persist_to_db = true` 时（默认开启），每次 Judge 评估完成后，将结果异步写入 `rag_eval_result` 表：

```
rag_eval_result 表结构：
├── 检索指标：n_retrieved, n_candidates, scores_min/p50/max,
│             embedding_latency_ms, db_query_latency_ms
├── Judge 评分：relevance_labels (JSONB), precision_at_5, recall_at_5,
│             ndcg_at_5, faithfulness_score, hallucination_rate,
│             completeness_score, citation_precision
├── 交叉验证：cross_validated, cross_validation_disagreement
├── 实验分组：experiment_group
├── 扩展元数据：extra_metadata (JSONB)
└── 时间戳：created_at
```

### 新增：A/B 实验分组标记

`evaluate_full()` 和 `record_generation()` 新增 `experiment_group` 参数，用于标记评估结果所属的实验分组。DB 表中 `experiment_group` 列支持按分组查询。

---

## 六、Layer 3：黄金测试集

**文件**：`backend/evaluation/golden_dataset.py`、`golden_queries.yaml`

### 设计理念

黄金测试集包含 **10 条精选查询**，覆盖不同的知识点类型和难度。每条查询有明确的**最低期望分数**，评估结果低于阈值时自动告警。

### 测试集结构

```yaml
# backend/evaluation/golden_queries.yaml
queries:
  - id: "gradient_descent_definition"
    kp_name: "梯度下降"
    query: "什么是梯度下降？它的基本原理是什么？"
    expected_aspects:           # 用于完整度 Judge
      - "梯度下降的定义"
      - "梯度的数学含义"
      - "学习率的作用"
      - "迭代更新的公式"
      - "收敛条件"
    min_faithfulness: 0.7       # 最低忠实度
    min_completeness: 0.6       # 最低完整度
    tags: ["definition", "mathematics"]
```

### 覆盖的知识点

| 查询 | 知识点 | 类型 |
|------|--------|------|
| gradient_descent_definition | 梯度下降 | 定义+数学 |
| backpropagation | 反向传播 | 算法+数学 |
| overfitting | 过拟合 | 概念+实践 |
| activation_function | 激活函数 | 概念+对比 |
| cnn_basics | 卷积神经网络 | 架构 |
| loss_function | 损失函数 | 数学+实践 |
| transformer_attention | Transformer 注意力 | 架构 |
| batch_normalization | 批归一化 | 技术 |
| sgd_variants | 优化器 | 对比+实践 |
| data_augmentation | 数据增强 | 技术+实践 |

### CLI 用法

```bash
# 运行完整评估
python -m backend.evaluation.golden --run

# 指定自定义测试集
python -m backend.evaluation.golden --run --dataset path/to/custom.yaml

# 仅查看测试集概要
python -m backend.evaluation.golden --info
```

### 回归检测

每次运行后，结果摘要自动保存到 `logs/golden_last_run.json`。下次运行时自动对比：

- 任一度量（faithfulness/completeness/precision）的**下降幅度 > 10%** → 标记 `regression_detected = true`
- 在报告中输出具体退化指标和幅度
- CLI 返回非零退出码（可接入 CI）

报告输出到 `logs/golden_report_YYYYMMDD_HHMMSS.md`。

---

## 七、Layer 4：A/B 实验框架

**文件**：`backend/evaluation/ab_experiment.py`

### 设计理念

开发阶段频繁调整 RAG 参数（切分大小、检索条数、score_threshold、prompt 等），需要一个可控的方式来比较"改之前"和"改之后"的效果。

### 两种运行模式

1. **在线模式**：在 Agent 管道中设置 `experiment_group`，生产自动打标，评估结果写入 DB，事后用 Reporter 对比
2. **离线模式**：CLI 工具对相同黄金查询集跑两组，直接生成对比报告（不需要实际用户请求）

### CLI 用法

```bash
# 完整 A/B 对比（检索 + 生成 + Judge）
python -m backend.evaluation.ab \
    --group-a baseline \
    --group-b chunk_size_800 \
    --queries backend/evaluation/golden_queries.yaml

# 仅对比检索质量（不跑 LLM Judge，速度更快）
python -m backend.evaluation.ab \
    --group-a baseline \
    --group-b hybrid_enabled \
    --queries backend/evaluation/golden_queries.yaml \
    --retrieval-only
```

### 对比报告

报告包含每个指标的组 A/组 B 值、Delta、变化百分比：

```
## 指标对比

| 指标 | baseline | chunk_size_800 | Delta | 变化% |
|------|----------|---------------|-------|-------|
| avg_n_retrieved | 5.000 | 4.800 | -0.200 | -4.0% |
| avg_score | 0.720 | 0.745 | +0.025 | +3.5% |
| avg_faithfulness | 0.820 | 0.835 | +0.015 | +1.8% |
| avg_completeness | 0.680 | 0.710 | +0.030 | +4.4% |
```

报告输出到 `logs/ab_report_*.md`。

---

## 八、配置总览

### config.yaml

```yaml
evaluation:
  mode: "development"                  # "development" | "production"
  health_check_enabled: true           # Layer 1 开关

  sampling:
    development: 1.0                   # 开发模式 LLM Judge 采样率
    production: 0.1                    # 生产模式 LLM Judge 采样率

  cross_validation:
    enabled: false                     # 多 LLM 交叉验证
    providers: ["qwen", "deepseek"]

  golden_dataset:
    path: "backend/evaluation/golden_queries.yaml"
    auto_run_interval_hours: 24

  ab_experiment:
    enabled: false
    groups: []

  storage:
    persist_to_db: true                # 持久化到 PostgreSQL
    retention_days: 90                 # 保留天数
```

### 切换模式

```bash
# 方法 1：直接改 config.yaml 的 evaluation.mode
# 方法 2：环境变量（如需要可扩展到 _resolve_env_vars）
```

---

## 九、数据流全景

```
用户请求进入
    │
    ▼
agents/utils.py: retrieve_for_agent()
    │
    ├── [embedding 计时] → embedding_latency_ms（真实分段计时）
    ├── [DB query 计时]  → db_query_latency_ms（真实分段计时）
    ├── collector.start_query()
    ├── collector.record_retrieval(scores, chunks, latencies)
    │
    ▼
agents/graph.py: _collect_generation_eval()
    │
    ├── collector.record_generation(agent_type, draft_len, gen_latency,
    │                                experiment_group)
    │
    ├── _maybe_trigger_async_judge()
    │       │
    │       ├── collector.decide_sample(session_id)  ← config 决定采样率
    │       │       │
    │       │       ├── 未命中 → return（仅保留元数据）
    │       │       │
    │       │       └── 命中 → asyncio.create_task(_run_judge())
    │       │                    │
    │       │                    ├── RAGJudge.evaluate_full()
    │       │                    │     ├── Judge 1: 相关性（并行）
    │       │                    │     ├── Judge 2: 忠实度（并行）
    │       │                    │     ├── Judge 3: 完整度（并行）
    │       │                    │     ├── Judge 4: 引用准确性（条件）
    │       │                    │     └── 交叉验证（可选，串行追加）
    │       │                    │
    │       │                    ├── 写回 collector._current_generation
    │       │                    │
    │       │                    └── collector.flush()
    │       │                          │
    │       │                          ├── _record_health_check() → Layer 1
    │       │                          ├── _persist_to_db()       → Layer 2 DB
    │       │                          └── _records.append()      → 内存
    │       │
    │       └── 用户请求返回（不等 Judge 完成）
    │
    ▼
离线评估（独立于请求流）
    │
    ├── python -m backend.evaluation.golden --run   → Layer 3
    └── python -m backend.evaluation.ab ...          → Layer 4
```

---

## 十、API 接口

| 端点 | 方法 | 用途 | 说明 |
|------|------|------|------|
| `/eval/rag/query` | POST | 对指定知识点执行完整四维评估 | v2.0 兼容 |
| `/eval/rag/report?period=daily` | GET | 生成日报或周报 | 可从 DB 读取 |
| `/eval/rag/records?n=20` | GET | 查看最近 N 条评估记录 | v2.0 兼容 |
| `/eval/rag/health` | GET | 查看健康检查摘要 | **新增** |

---

## 十一、文件索引

### 新文件（v3.0 新增）

| 文件 | 职责 |
|------|------|
| `backend/evaluation/health_check.py` | Layer 1：每次请求的轻量指标采集 + 滑动窗口告警 |
| `backend/evaluation/golden_dataset.py` | Layer 3：黄金测试集管理 + 批量评估 + 回归检测 |
| `backend/evaluation/golden_queries.yaml` | 10 条精选黄金查询 |
| `backend/evaluation/ab_experiment.py` | Layer 4：A/B 实验框架 + 对比报告 |
| `migrations/versions/a1b2c3d4e5f6_add_rag_eval_result.py` | rag_eval_result 持久化表 |

### 修改文件（v3.0 增强）

| 文件 | 变更 |
|------|------|
| `backend/evaluation/collector.py` | config 驱动采样率、experiment_group、DB 持久化、健康检查集成 |
| `backend/evaluation/judge.py` | 多 LLM 交叉验证、experiment_group 参数 |
| `backend/evaluation/models.py` | 新增 HealthCheckRecord、GoldenQuery、GoldenEvalResult、GoldenRegressionReport、ABExperimentResult |
| `backend/evaluation/reporter.py` | fetch_records_from_db()、compare_ab_groups() |
| `backend/evaluation/__init__.py` | 导出所有新模块 |
| `backend/db/models.py` | 新增 RAGEvalResult ORM 模型 |
| `backend/config.py` | 新增 EvaluationConfig（含 6 个子配置类） |
| `configs/config.yaml` | 新增 evaluation 配置段 |
| `backend/agents/utils.py` | 检索子阶段分别计时 |
| `backend/agents/graph.py` | experiment_group、generation_latency_ms 采集 |

### 不变文件（v2.0 保留）

| 文件 | 说明 |
|------|------|
| `backend/evaluation/metrics.py` | 8 个纯函数指标，无需修改 |
| `backend/main.py` | API 端点保持兼容 |

---

## 十二、测试覆盖

v2.0 的 5 个测试文件保持不变：

| 测试文件 | 测什么 |
|---------|--------|
| `test_evaluation_metrics.py` | 8 个指标函数的计算逻辑 |
| `test_evaluation_models.py` | 数据模型的序列化/验证 |
| `test_evaluation_judge.py` | 4 个 Judge + 联合评估 |
| `test_evaluation_collector.py` | Collector 完整生命周期 |
| `test_evaluation_reporter.py` | 报告生成、渲染、文件写入 |

新增测试建议（待实现）：
- `test_evaluation_health_check.py` — 健康检查阈值逻辑
- `test_evaluation_golden.py` — 黄金测试集加载、评估、回归检测
- `test_evaluation_ab.py` — A/B 实验执行和报告

---

## 十三、从 v2.0 迁移指南

### 如果你已经部署了 v2.0

1. **拉取代码**：所有 API 端点向后兼容
2. **运行迁移**：`alembic upgrade head`（创建 `rag_eval_result` 表）
3. **更新配置**：将 `evaluation` 段添加到 `configs/config.yaml`
4. **设置模式**：开发阶段设 `evaluation.mode: "development"`（100% 采样）
5. **（可选）启用交叉验证**：仅调试关键变更时开启，用完关掉

### 如果你想回退到 v2.0 行为

在 `config.yaml` 中设置：
```yaml
evaluation:
  mode: "production"
  health_check_enabled: false
  storage:
    persist_to_db: false
```

即可回到 10% 采样 + 纯内存存储的 v2.0 行为。

---

## 十四、关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 持久化方案 | PostgreSQL `rag_eval_result` 表 | 与项目技术栈一致，支持 SQL 聚合查询趋势 |
| 健康检查范围 | 仅数值指标，不调用 LLM | <5ms，不能影响用户体验 |
| 黄金测试集规模 | 10 条精选查询 | 覆盖典型场景，评估成本可控（~40 次 LLM 调用/次运行） |
| 多 LLM 交叉验证 | Qwen + DeepSeek 双裁判 | 两个不同模型同时出错概率极低，仅验证关键维度 |
| 开发默认采样率 | 100% | 开发阶段需要每一条数据来快速迭代 |
| A/B 实验执行方式 | 同步顺序执行 | 需要严格控制变量，异步无法保证公平对比 |
| 评估与请求解耦 | `asyncio.create_task` fire-and-forget | 用户请求不受 Judge 耗时影响 |

---

> 文档版本：v3.0 | 最后更新：2026-05-27 | 模块：`backend/evaluation/`
