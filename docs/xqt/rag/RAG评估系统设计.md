# RAG 效果评估与量化系统设计

本文档设计了一套可落地的 RAG 效果量化评估系统，覆盖从理论框架、指标体系、数据采集、评分方法到模块架构的完整方案。

---

## 一、为什么要量化评估 RAG

当前系统的 RAG 管线通过日志输出的信息有限：

```
[RAG] 检索到 5 条相关文档，最高分=0.87，最低分=0.62
```

仅凭这两条信息，无法回答以下关键问题：

- "检索到的这 5 条文档**真的**和用户问题相关吗？"
- "LLM 生成的答案**有没有忠实于**这些参考资料？"
- "参考资料中提到的关键概念，答案中**有没有遗漏**？"
- "这周的 RAG 质量和上周相比**是变好了还是变差了**？"
- "换了 embedding 模型之后，检索质量**到底提升了多少**？"

量化评估系统的目标就是回答这些问题。

---

## 二、评估维度与指标体系

RAG 系统的质量可以从五个维度评估，每个维度下有具体的可量化指标：

### 2.1 指标体系总览

```
┌──────────────────────────────────────────────────────────────────┐
│                     RAG 评估五维模型                               │
├──────────────┬──────────────┬──────────────┬──────────┬──────────┤
│   检索质量    │   生成忠实度  │  答案正确性   │ 用户体验  │ 系统效率  │
│  (Retrieval) │ (Faithfulness)│ (Correctness) │  (UX)    │  (Perf)  │
├──────────────┼──────────────┼──────────────┼──────────┼──────────┤
│ Precision@K  │ Faithfulness │ Fact Accuracy│ Quiz     │ Latency  │
│ Recall@K     │ Citation     │ Key Concept  │ Correct  │ Token    │
│ MRR          │ Precision    │ Coverage      │ Rate     │ Cost     │
│ NDCG         │ Hallucination│ Difficulty   │ Re-query │ Through- │
│ Hit Rate     │ Rate         │ Match        │ Rate     │ put      │
└──────────────┴──────────────┴──────────────┴──────────┴──────────┘
```

### 2.2 检索质量（Retrieval Quality）

**评估对象：** `retrieve()` → `retrieve_by_kp()` 的返回结果

| 指标 | 定义 | 计算方式 | 理想值 |
|------|------|---------|--------|
| **Precision@K** | Top-K 结果中相关 chunk 的占比 | `relevant_in_top_k / K` | > 0.6 |
| **Recall@K** | 所有相关 chunk 中被检索到的占比 | `retrieved_relevant / total_relevant` | > 0.7 |
| **MRR** | 第一个相关结果的排名的倒数均值 | `1 / rank_of_first_relevant` | > 0.5 |
| **NDCG@K** | 考虑排序位置加权的相关度得分 | 见下方公式 | > 0.6 |
| **Hit Rate** | Top-K 中至少有一条相关的查询占比 | `queries_with_hit / total_queries` | > 0.8 |
| **Cosine Score 分布** | 检索结果分数的统计分布 | P25 / P50 / P75 / P90 | P50 > 0.65 |

**相关度判断方式：**
- **方案A（低成本）：** 用 LLM-as-Judge 对每个 (query, chunk) 打 0/1/2 相关度分
- **方案B（零成本）：** 复用 `score_threshold` 过滤后的 score 作为弱标签
- **方案C（高成本但精确）：** 人工标注 50-100 条 (query, chunks) 作为 golden set

**NDCG@K 公式：**
```
DCG@K = Σ(i=1→K) (2^rel_i - 1) / log₂(i + 1)
NDCG@K = DCG@K / IDCG@K
```
其中 `rel_i` 是第 i 个结果的相关度评分（0/1/2），IDCG 是理想排序下的 DCG。

### 2.3 生成忠实度（Faithfulness）

**评估对象：** `draft_content` / `final_content` vs `retrieved_docs`

这是 RAG 最核心的质量维度——"LLM 有没有忠实使用参考资料"。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Faithfulness Score** | 答案中可被参考资料支持的陈述占比 | 逐句分解 → 逐句对比参考资料 → 统计可被支持的句子比例 |
| **Citation Precision** | LLM 标注的 `[n]` 引用是否确实与引用内容匹配 | 抽样检查引用处是否能在对应 chunk 中找到依据 |
| **Hallucination Rate** | 答案中无法在参考资料中找到依据的陈述占比 | `1 - Faithfulness Score` |
| **Source Coverage** | 检索到的参考资料中，有多少条被答案实际引用 | `cited_sources / total_retrieved_sources` |

**Faithfulness 逐句评估流程：**

```
分解 LLM 输出为独立陈述
        │
        ▼
  ┌─────────────────────────┐
  │ 陈述1: "梯度下降是一种   │──→ 在 retrieved_docs[0] 中找到原文"...通过迭代优化参数"
  │ 陈述2: "学习率通常取     │──→ 在 retrieved_docs[2] 中找到原文
  │        0.01"             │
  │ 陈述3: "牛顿法比梯度     │──→ 未在任何参考资料中找到 ← 幻觉
  │        下降快三倍"       │
  └─────────────────────────┘
        │
        ▼
   Faithfulness = 2/3 = 0.67
```

**实现方式：** 用 LLM 做逐句验证（见第四节 judge.py 设计），每次评估约消耗 1000-2000 tokens。

### 2.4 答案正确性（Answer Correctness）

**评估对象：** `final_content` 的事实准确性

不同于 Faithfulness（关注"有没有依据"），Correctness 关注"依据本身对不对、答案是否完整"。

| 指标 | 定义 | 计算方式 |
|------|------|---------|
| **Fact Accuracy** | 答案中的事实陈述是否准确 | LLM-as-Judge 逐事实比对 golden answer 或权威来源 |
| **Key Concept Coverage** | 知识点关键概念被答案覆盖的比例 | 预定义知识点 → 关键概念映射表，检查答案中出现了几个 |
| **Completeness Score** | 答案对该知识点"应讲内容"的覆盖度 | LLM 判断："给定知识点 X，一份合格答案应包含 A/B/C，该答案包含了 A/C，得分 2/3" |
| **Difficulty Match** | 答案难度是否匹配学生画像 | LLM 评估答案难度是否与画像中的认知水平和学习阶段匹配 |

**Key Concept Coverage 示例：**

```
知识点: "反向传播算法"
关键概念: [链式法则, 梯度计算, 前向传播, 损失函数, 权重更新, 学习率]

LLM 答案中出现的概念: [链式法则, 梯度计算, 权重更新]
Coverage = 3/6 = 0.50
```

### 2.5 用户体验信号（UX Signals）

**评估对象：** 用户行为数据（已有数据表可直接利用）

| 指标 | 定义 | 数据来源 | 含义 |
|------|------|---------|------|
| **Quiz Correct Rate** | 基于 RAG 生成题目后的答题正确率 | `quiz_attempt.is_correct` | 间接反映生成内容的可理解性 |
| **Re-query Rate** | 同一会话内对同一知识点的追问比例 | `chat_message` 连续消息分析 | 高追问率 → 首次答案不够清晰 |
| **Content Completion Rate** | 用户查看完生成内容的比例 | `learning_record.action = "complete"` | 低完成率 → 内容质量或长度不合适 |
| **Avg. View Duration** | 用户在生成内容上的平均停留时间 | `learning_record.duration_seconds` | 极短 → 内容无价值；极长 → 内容难懂 |
| **Resource Reuse Rate** | 同一资源被多次访问的比例 | `learning_record` 按 `resource_id` 聚合 | 高复用率 → 资源质量好 |

**这些是零额外成本的信号——数据已经在产生，只需要一个查询/聚合层。**

### 2.6 系统效率（System Efficiency）

| 指标 | 定义 | 当前状态 |
|------|------|---------|
| **Embedding Latency (P50/P95)** | 单次 embedding 调用的延迟分布 | 未采集，只有日志 |
| **DB Query Latency** | pgvector 向量检索耗时 | 未采集 |
| **End-to-End Retrieval Latency** | 从 `retrieve()` 调用到返回结果的总延迟 | 未采集 |
| **Tokens per Query** | 每次 RAG 检索+生成消耗的总 token | 未采集 |
| **Embedding vs Generation Cost Ratio** | embedding 费用与 LLM 生成费用的比例 | 未采集 |

---

## 三、数据采集方案

### 3.1 现有可用数据源

系统已有的数据表为评估提供了丰富的基础信号：

```sql
-- 已有的隐式质量信号
quiz_attempt:    is_correct, score, kp_id      -- 答题正确率 → 代理"内容有效性"
learning_record: action, duration_seconds       -- 用户行为 → 代理"内容价值"
chat_message:    role, content, created_at      -- 对话流 → 检测追问模式
resource_meta:   resource_type, content, title  -- 生成内容 → 离线分析
generation_task: status, error_message          -- 生成成功率
```

### 3.2 新增采集点

需要在 RAG 管线中嵌入以下采集逻辑：

#### 采集点 1：检索阶段（`retriever.py:retrieve()`）

```python
# 在返回结果前采集
retrieval_record = {
    "query": query,
    "kp_name": kp_name,
    "timestamp": datetime.utcnow(),
    "embedding_latency_ms": embedding_time_ms,
    "db_query_latency_ms": db_query_time_ms,
    "n_candidates": prefetch_count,
    "n_results": len(chunks),
    "scores": [c.score for c in chunks],        # 完整分数分布
    "score_stats": {                              # 分位数
        "min": min(scores), "p25": ..., "p50": ..., "p75": ..., "max": max(scores)
    },
    "chunk_ids": [c.chunk_id for c in chunks],
    "doc_ids": [c.doc_id for c in chunks],
}
```

#### 采集点 2：格式化阶段（`retriever.py:format_context()`）

```python
context_record = {
    "tokens_estimated": estimated_tokens,
    "chunks_included": len(parts),
    "chunks_truncated": len(chunks) - len(parts),
    "source_diversity": len(set(c.source for c in included_chunks)),
}
```

#### 采集点 3：Agent 生成后（各 Agent `run()` 方法）

```python
generation_record = {
    "agent": agent_name,          # "doc_agent" / "quiz_agent" / ...
    "kp_name": kp_name,
    "draft_length": len(draft_content),
    "generation_latency_ms": llm_time_ms,
    "has_rag_context": len(retrieved_docs) > 0,
    "n_retrieved": len(retrieved_docs),
}
```

#### 采集点 4：SafetyAgent 审核后（`safety_agent.py:run()`）

```python
safety_record = {
    "passed": passed,
    "issues_count": len(issues),
    "issues": issues,             # 结构化问题列表
    "retrieved_count": len(state.retrieved_docs),
}
```

### 3.3 采集策略：采样 vs 全量

| 采集内容 | 策略 | 原因 |
|---------|------|------|
| 检索延迟 / score 分布 / token 用量 | **全量** | 数据量小，写入成本极低 |
| LLM-as-Judge 评估（Faithfulness 等） | **采样 10%** | 每次评估额外消耗 1000-2000 tokens |
| 用户行为信号 | **全量** | 数据已在数据库中，只做聚合查询 |

### 3.4 存储方案

```sql
-- 检索评估记录表（轻量，全量采集）
CREATE TABLE rag_retrieval_eval (
    id BIGINT PRIMARY KEY,
    session_id BIGINT,
    user_id BIGINT,
    kp_name VARCHAR(256),
    query TEXT,
    timestamp TIMESTAMP,
    embedding_latency_ms INTEGER,
    db_query_latency_ms INTEGER,
    n_candidates INTEGER,
    n_results INTEGER,
    scores DOUBLE PRECISION[],
    chunk_ids VARCHAR(128)[],
    doc_ids VARCHAR(128)[],
    score_p50 DOUBLE PRECISION,
    score_p75 DOUBLE PRECISION
);

-- 生成评估记录表（采样采集，含 LLM-as-Judge 结果）
CREATE TABLE rag_generation_eval (
    id BIGINT PRIMARY KEY,
    session_id BIGINT,
    retrieval_eval_id BIGINT REFERENCES rag_retrieval_eval(id),
    agent_type VARCHAR(32),
    kp_name VARCHAR(256),
    timestamp TIMESTAMP,
    -- 自动采集
    draft_length INTEGER,
    generation_latency_ms INTEGER,
    has_rag_context BOOLEAN,
    n_retrieved INTEGER,
    safety_passed BOOLEAN,
    safety_issues_count INTEGER,
    -- LLM-as-Judge 评估结果
    faithfulness_score DOUBLE PRECISION,
    hallucination_rate DOUBLE PRECISION,
    citation_precision DOUBLE PRECISION,
    concept_coverage DOUBLE PRECISION,
    completeness_score DOUBLE PRECISION,
    judge_raw_response JSON
);
```

---

## 四、LLM-as-Judge 评估器设计

### 4.1 设计原理

LLM-as-Judge 是当前业界评估 RAG 系统最实用的方法。核心思想：**用同一个 LLM（或更便宜的 LLM）充当评估者**，对检索结果和生成内容打分。

为什么有效：
- 生成和评估使用**不同的 System Prompt**——生成要求"创造内容"，评估要求"找错误"（与 SafetyAgent 同理）
- 评估用低 temperature（0.0-0.1），追求确定性输出
- 评估任务被拆解为小的、结构化的是/否判断，而非开放式评分

### 4.2 四类评估 Judge

#### Judge 1：检索相关性评估（Chunk Relevance）

```python
SYSTEM_PROMPT = """你是一位 RAG 检索质量评估专家。
给定一个用户查询和一条检索到的文本片段，判断该片段是否与查询相关。

查询：{query}
文本片段：{chunk_text}

请判断：
- 2分（高度相关）：该片段直接回答了查询，或包含了查询主题的核心信息
- 1分（部分相关）：该片段与查询话题相关，但不是直接答案
- 0分（无关）：该片段与查询无关

仅返回 JSON：{"score": 0|1|2, "reason": "一句话理由"}
"""
```

**调用方式：** 对每次检索的 top-K 结果，逐 chunk 调用此 Judge。一次评估 = K 次 LLM 调用，每次约 500 tokens。

**应用：** 计算 Precision@K、Recall@K、NDCG@K。

#### Judge 2：忠实度评估（Faithfulness）

```python
SYSTEM_PROMPT = """你是一位事实核查专家。
给定一段参考资料和 AI 生成的答案，逐句检查答案中的陈述是否能在参考资料中找到依据。

参考资料：
{retrieved_docs}

AI 生成答案：
{generated_content}

请将答案拆解为独立的陈述句，逐句判断：
- "supported": 该陈述可以在参考资料中找到直接或间接依据
- "unsupported": 该陈述在参考资料中找不到依据（可能是捏造）

返回 JSON：
{
  "statements": [
    {"text": "陈述原文", "verdict": "supported|unsupported", "evidence": "依据片段或null"}
  ],
  "faithfulness": 0.0-1.0,
  "issues": ["发现的问题"]
}
"""
```

**调用方式：** 生成完成后异步调用（不阻塞用户响应）。每次约 1500-2500 tokens。

#### Judge 3：完整度评估（Completeness）

```python
SYSTEM_PROMPT = """你是一位课程内容评审专家。
对于知识点"{kp_name}"，一份合格的学习资料应涵盖以下方面的内容。请评估 AI 生成答案的覆盖程度。

应涵盖的关键方面（根据知识点类型动态生成）：
{expected_aspects}

AI 生成答案：
{generated_content}

对每个方面判断是否被覆盖（"covered" / "partial" / "missing"），返回 JSON：
{
  "aspects": [
    {"aspect": "方面名", "coverage": "covered|partial|missing", "evidence": "相关段落"}
  ],
  "completeness": 0.0-1.0
}
"""
```

**注意：** `expected_aspects` 可通过 LLM 动态生成——先问 LLM "知识点 X 的学习资料应该包含哪些方面？"，再用回答作为评估标准。

#### Judge 4：引用准确性评估（Citation Accuracy）

```python
SYSTEM_PROMPT = """你是一位学术引用审核员。
AI 生成的答案中有 [n] 形式的引用标注。请检查每个引用处的内容是否确实能在对应的参考资料中找到。

答案中引用 [1] 处的上下文：{citation_context_1}
参考资料 [1] 的内容：{reference_chunk_1}

判断：
- "accurate": 引用处的陈述与参考资料一致
- "inaccurate": 引用处的陈述在参考资料中找不到，或含义被曲解
- "vague": 引用太模糊，无法判断

返回 JSON：{"verdict": "accurate|inaccurate|vague", "explanation": "理由"}
"""
```

### 4.3 评估执行策略

```
┌──────────────────────────────────────────────────────────────┐
│                     评估执行流程                              │
├──────────────────────────────────────────────────────────────┤
│                                                              │
│  用户请求 → Agent Pipeline → 返回结果给用户                   │
│                  │                    ↑                      │
│                  │ (同步采集)         │                      │
│                  ▼                    │                      │
│          ┌─────────────┐              │                      │
│          │ Collector   │              │                      │
│          │ 采集检索数据和│             │                      │
│          │ 生成元数据   │             │                      │
│          └──────┬──────┘              │                      │
│                 │                     │                      │
│                 ▼                     │                      │
│          ┌─────────────┐              │                      │
│          │ Sample 10%  │              │                      │
│          │ 按 session  │              │                      │
│          │ 哈希采样    │              │                      │
│          └──────┬──────┘              │                      │
│                 │                     │                      │
│                 ▼                     │                      │
│          ┌─────────────┐              │                      │
│          │ Judge       │ 异步后台执行  │                      │
│          │ 1.检索相关性 │              │                      │
│          │ 2.忠实度    │              │                      │
│          │ 3.完整度    │              │                      │
│          │ 4.引用准确性 │              │                      │
│          └──────┬──────┘              │                      │
│                 │                     │                      │
│                 ▼                     │                      │
│          ┌─────────────┐              │                      │
│          │ Reporter    │ ─────────────┘                      │
│          │ 汇总生成报告 │   → 反馈到配置调优                   │
│          └─────────────┘                                     │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

关键设计决策：
- **Judge 评估异步执行**：不阻塞用户响应
- **采样率可配**：默认 10%，高峰期可降至 5%
- **按 session 哈希采样**：同一次会话的多个轮次要么全评估，要么全不评估，保证会话内数据完整性

---

## 五、模块架构设计

### 5.1 文件结构

```
backend/evaluation/
├── __init__.py          # 导出公共接口
├── models.py            # 评估数据模型（Pydantic）
├── collector.py         # 数据采集器：在 RAG 管线中埋点
├── metrics.py           # 指标计算：Precision/Recall/MRR/NDCG
├── judge.py             # LLM-as-Judge 四类评估器
├── reporter.py          # 报告生成：控制台/JSON/HTML
└── golden_set.py        # Golden Dataset 管理
```

### 5.2 核心模块说明

#### models.py — 评估数据模型

```python
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class RetrievalEvalRecord(BaseModel):
    """单次检索的评估快照"""
    query: str
    kp_name: str
    timestamp: datetime
    embedding_latency_ms: float
    db_query_latency_ms: float
    n_candidates: int
    n_results: int
    scores: list[float]         # 完整分数分布
    chunk_ids: list[str]
    doc_ids: list[str]

class GenerationEvalRecord(BaseModel):
    """单次生成的评估快照"""
    agent_type: str
    kp_name: str
    draft_length: int
    generation_latency_ms: float
    has_rag_context: bool
    n_retrieved: int
    safety_passed: bool
    safety_issues_count: int
    # LLM-as-Judge 字段（异步填充）
    faithfulness_score: Optional[float] = None
    hallucination_rate: Optional[float] = None
    concept_coverage: Optional[float] = None
    completeness_score: Optional[float] = None

class RAGEvalReport(BaseModel):
    """周期性评估报告"""
    period_start: datetime
    period_end: datetime
    total_queries: int
    # 检索质量汇总
    precision_at_5: float
    recall_at_5: float
    mrr: float
    ndcg_at_5: float
    score_p50: float
    # 生成质量汇总
    avg_faithfulness: float
    avg_hallucination_rate: float
    avg_concept_coverage: float
    # 系统效率
    p50_retrieval_latency_ms: float
    p95_retrieval_latency_ms: float
    # 用户体验
    quiz_correct_rate: float
    re_query_rate: float
    # 变化趋势（与上期对比）
    delta_vs_previous: dict[str, float]
```

#### collector.py — 数据采集器

```python
class RAGEvalCollector:
    """RAG 评估数据采集器（模块级单例）"""

    def __init__(self):
        self._current_query: Optional[RetrievalEvalRecord] = None
        self._records: list[RetrievalEvalRecord] = []

    def start_query(self, query: str, kp_name: str):
        """在 retrieve() 开始时调用"""
        self._current_query = RetrievalEvalRecord(
            query=query, kp_name=kp_name,
            timestamp=datetime.utcnow(),
            ...
        )

    def record_retrieval(self, scores, chunk_ids, latencies):
        """检索完成后调用，填充分数和延迟"""
        ...

    def record_generation(self, agent_type, draft_length, latency):
        """Agent 生成完成后调用"""
        ...

    def flush(self) -> RetrievalEvalRecord:
        """结束当前查询，返回完整记录"""
        ...

# 模块级单例
collector = RAGEvalCollector()
```

**集成方式——在 `retrieve_context()` 中埋点：**

```python
# backend/agents/utils.py 中的修改
async def retrieve_context(kp_name, user_id, agent_label):
    from backend.evaluation.collector import collector

    collector.start_query(query=kp_name, kp_name=kp_name)

    # ... 原有检索逻辑 ...

    collector.record_retrieval(
        scores=[c.score for c in chunks],
        chunk_ids=[c.chunk_id for c in chunks],
        latencies={"embedding": emb_ms, "db_query": db_ms},
    )
    return context, retrieved_texts
```

#### metrics.py — 指标计算

```python
def precision_at_k(relevance_labels: list[int], k: int) -> float:
    """Precision@K: Top-K 中相关结果占比"""
    return sum(1 for r in relevance_labels[:k] if r > 0) / k

def recall_at_k(relevance_labels: list[int], total_relevant: int, k: int) -> float:
    """Recall@K: 所有相关结果中被检索到的比例"""
    if total_relevant == 0:
        return 0.0
    return sum(1 for r in relevance_labels[:k] if r > 0) / total_relevant

def mrr(relevance_labels_list: list[list[int]]) -> float:
    """MRR: 第一个相关结果排名的倒数均值"""
    reciprocal_ranks = []
    for labels in relevance_labels_list:
        for i, rel in enumerate(labels, 1):
            if rel > 0:
                reciprocal_ranks.append(1.0 / i)
                break
        else:
            reciprocal_ranks.append(0.0)
    return sum(reciprocal_ranks) / len(reciprocal_ranks)

def ndcg_at_k(relevance_labels: list[int], k: int) -> float:
    """NDCG@K: 位置加权的归一化折损累积增益"""
    import math
    dcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(relevance_labels[:k]))
    ideal = sorted(relevance_labels, reverse=True)
    idcg = sum((2**rel - 1) / math.log2(i + 2) for i, rel in enumerate(ideal[:k]))
    return dcg / idcg if idcg > 0 else 0.0

def hallucination_rate(faithfulness_result: dict) -> float:
    """从 Faithfulness Judge 的结果中计算幻觉率"""
    statements = faithfulness_result.get("statements", [])
    if not statements:
        return 0.0
    unsupported = sum(1 for s in statements if s["verdict"] == "unsupported")
    return unsupported / len(statements)

def quiz_correct_rate(attempts: list) -> float:
    """从 QuizAttempt 计算正确率"""
    if not attempts:
        return 0.0
    return sum(1 for a in attempts if a.is_correct) / len(attempts)

def score_distribution(scores: list[float]) -> dict:
    """计算分数分位数"""
    import numpy as np
    return {"p25": np.percentile(scores, 25), "p50": np.percentile(scores, 50),
            "p75": np.percentile(scores, 75), "p90": np.percentile(scores, 90)}
```

#### judge.py — LLM 评估器

```python
class RAGJudge:
    """RAG LLM-as-Judge 评估器"""

    def __init__(self, provider: str = "qwen", temperature: float = 0.0):
        self.provider = provider
        self.temperature = temperature

    async def judge_chunk_relevance(self, query: str, chunk_text: str) -> dict:
        """Judge 1: 单 chunk 相关性评分 (0/1/2)"""
        ...

    async def judge_faithfulness(self, retrieved_docs: list[str],
                                  generated_content: str) -> dict:
        """Judge 2: 忠实度评估（逐句比对）"""
        ...

    async def judge_completeness(self, kp_name: str, generated_content: str,
                                  expected_aspects: list[str] = None) -> dict:
        """Judge 3: 完整度评估"""
        ...

    async def judge_citation_accuracy(self, citation_context: str,
                                       reference_chunk: str) -> dict:
        """Judge 4: 引用准确性评估"""
        ...

    async def evaluate_full(self, query: str, kp_name: str,
                            retrieved_chunks: list[RetrievedChunk],
                            generated_content: str) -> dict:
        """完整评估流程（顺序执行四个 Judge）"""
        ...
```

#### reporter.py — 报告生成

```python
class RAGReporter:
    """RAG 评估报告生成器"""

    async def generate_daily_report(self) -> RAGEvalReport:
        """生成日报：过去 24 小时的指标"""
        ...

    async def generate_period_report(self, start: datetime, end: datetime) -> RAGEvalReport:
        """生成周报/月报"""
        ...

    async def compare_reports(self, report_a: RAGEvalReport,
                              report_b: RAGEvalReport) -> dict:
        """对比两期报告，计算 delta"""
        ...

    def to_markdown(self, report: RAGEvalReport) -> str:
        """将报告渲染为 Markdown"""
        ...

    def to_html(self, report: RAGEvalReport) -> str:
        """将报告渲染为 HTML 仪表盘"""
        ...
```

#### golden_set.py — Golden Dataset

```python
class GoldenDataset:
    """评估用 Golden Dataset：人工标注的 (查询, 知识点, 关键概念, 相关chunk_id) 集合"""

    def __init__(self, path: str = "data/rag_golden_set.json"):
        self.entries: list[GoldenEntry] = self._load(path)

    def get_entry(self, kp_name: str) -> Optional[GoldenEntry]:
        """按知识点名称查找 golden entry"""
        ...

    def evaluate_retrieval(self, kp_name: str, retrieved_chunk_ids: list[str]) -> dict:
        """基于 golden set 评估一次检索的 Precision/Recall"""
        ...

    def add_entry(self, entry: GoldenEntry):
        """添加新的 golden entry（人工标注后）"""
        ...

@dataclass
class GoldenEntry:
    kp_name: str
    query: str
    expected_concepts: list[str]    # 答案应包含的关键概念
    relevant_chunk_ids: list[str]   # 应该被检索到的 chunk ID
    difficulty: str                 # "basic" | "intermediate" | "advanced"
```

### 5.3 评估触发方式

```python
# 方式一：编程接口
from backend.evaluation import RAGJudge, RAGReporter

judge = RAGJudge()
result = await judge.evaluate_full(
    query="梯度下降",
    kp_name="梯度下降",
    retrieved_chunks=chunks,
    generated_content=draft_content,
)

# 方式二：FastAPI 端点（手动触发评估）
@app.post("/eval/rag/query", tags=["evaluation"])
async def evaluate_single_query(kp_name: str, ...):
    """对单个知识点做完整的 RAG 评估"""
    ...

# 方式三：后台定时任务（自动周期性评估）
# 在 main.py lifespan 中启动，每天凌晨执行
async def scheduled_eval_task():
    while True:
        await asyncio.sleep(86400)  # 24 小时
        report = await RAGReporter().generate_daily_report()
        logger.info(f"[Eval] 日报:\n{report.to_markdown()}")
```

---

## 六、Golden Dataset 构建策略

Golden Dataset 是离线评估的"标准答案"，让自动化评估有一个可信的参照系。

### 6.1 规模与成本

| 阶段 | 规模 | 标注方式 | 用途 |
|------|------|---------|------|
| **种子集** | 20 条 | 开发者手动标注 | 冒烟测试、评估框架验证 |
| **基础集** | 50-100 条 | 开发者 + 领域助教 | 周期性评估、模型切换 ABC 测试 |
| **扩展集** | 200-500 条 | 半自动（LLM 预标注 + 人工修正） | 全维度评估 |

### 6.2 Golden Entry 示例

```json
{
  "kp_name": "反向传播算法",
  "query": "解释反向传播算法的原理",
  "expected_concepts": [
    "链式法则",
    "梯度计算",
    "前向传播",
    "损失函数对权重的偏导数",
    "误差从输出层向输入层传播"
  ],
  "relevant_chunk_ids": [
    "doc_abc123_0",
    "doc_abc123_1",
    "doc_abc123_2"
  ],
  "difficulty": "intermediate"
}
```

### 6.3 半自动标注流程

```
1. 从生产日志中抽样 200 条真实查询
       ↓
2. LLM 自动预标注：
   - 生成 expected_concepts（用 LLM 列出知识点应包含的关键概念）
   - 标记 relevant_chunk_ids（用现有检索 + LLM 相关性判断）
       ↓
3. 人工复核：修正预标注中的错误（预计 30% 需修正）
       ↓
4. 入库：写入 golden_set.json
```

---

## 七、评估结果的应用

### 7.1 配置调优决策支持

| 指标异常 | 诊断方向 | 建议调整 |
|---------|---------|---------|
| Precision@5 < 0.4 | 检索到的 chunk 很多不相关 | 提高 `score_threshold`（如 0.5→0.6） |
| Recall@5 < 0.5 | 相关 chunk 未被检索到 | 降低 `score_threshold` 或增加 `n_results` |
| MRR < 0.3 | 最相关的 chunk 排名靠后 | 调整 re-rank 权重或引入混合检索 |
| Hallucination Rate > 0.3 | LLM 大量编造内容 | 增强 Prompt 约束，提高 `context_max_tokens` |
| Concept Coverage < 0.5 | 答案遗漏关键概念 | 增加检索返回数量，或用 MMR 提升多样性 |
| P95 Latency > 3s | 检索环节有性能瓶颈 | 调整 IVFFlat probes，优化 DB 索引 |

### 7.2 A/B 测试框架

当系统做了变更（如换 embedding 模型、调整 chunk_size），可对比变更前后的评估指标：

```
┌─────────────────────────────────────────────┐
│             A/B 评估对照表                   │
├──────────────┬──────────┬──────────┬─────────┤
│    指标       │ 变更前   │  变更后  │  Delta  │
├──────────────┼──────────┼──────────┼─────────┤
│ Precision@5  │   0.58   │   0.63   │  +8.6%  │
│ Recall@5     │   0.62   │   0.61   │  -1.6%  │
│ Faithfulness │   0.78   │   0.81   │  +3.8%  │
│ P50 Latency  │  420ms   │  380ms   │  -9.5%  │
│ Token Cost   │  3200    │  2800    │ -12.5%  │
└──────────────┴──────────┴──────────┴─────────┘
```

### 7.3 告警规则

| 告警条件 | 严重级别 | 建议动作 |
|---------|---------|---------|
| Faithfulness < 0.5 持续 1 天 | P1 | 检查 embedding API / LLM 是否异常 |
| P95 Latency > 5s | P2 | 检查 DB 连接池、API 网络 |
| Quiz Correct Rate 周环比下降 > 20% | P2 | 检查近期内容质量变化 |
| 连续 10 次检索返回 0 结果 | P1 | 检查向量库是否损坏/为空 |

---

## 八、实施路线

### Phase 1：零成本信号聚合（1-2 天）

**目标：** 先把已有数据利用起来，不引入任何新模块。

- 从 `quiz_attempt` 按 `kp_id` 聚合正确率 → `quiz_correct_rate`
- 从 `learning_record` 统计 view/complete/quiz 行为分布 → 内容使用模式
- 从 `chat_message` 检测同一 session 内的连续追问 → `re_query_rate`
- 从 `safety_agent` 日志聚合 `passed` 比例和 `issues` 类型分布

**产出：** 一个 SQL 查询脚本或简单的 Python 统计脚本，可手动运行。

### Phase 2：采集器 + 检索指标（2-3 天）

**目标：** 建立实时采集管道，开始计算检索质量指标。

- 实现 `backend/evaluation/collector.py`：在 `retrieve()` 和 `retrieve_context()` 中埋点
- 实现 `backend/evaluation/metrics.py`：Precision@K、Recall@K、MRR、NDCG、分数分布
- 实现检索延迟采集（embedding + DB query 分段计时）
- 在日志中输出结构化评估数据（`[Eval]` 标签）

**产出：** 每次检索都有完整的 metrics 日志，可接入日志分析。

### Phase 3：LLM-as-Judge 评估（3-4 天）

**目标：** 引入自动化的生成质量评估。

- 实现 `backend/evaluation/judge.py`：Faithfulness + Completeness + Citation Accuracy
- 实现采样策略（10% 采样，异步执行）
- 建立 `rag_generation_eval` 表持久化评估结果
- 实现 `reporter.py` 日报生成

**产出：** 每天自动输出一份 Markdown 格式的 RAG 质量报告。

### Phase 4：Golden Dataset + A/B 测试（3-5 天）

**目标：** 建立可信的离线评估基准。

- 构建 50 条基础 Golden Dataset
- 实现基于 Golden Set 的自动化回归测试
- 实现 A/B 对照评估（变更前 vs 变更后）
- FastAPI 评估端点 + 简单的前端仪表盘

**产出：** `pytest tests/eval/` 可验证 RAG 质量不下滑。

---

## 九、总结

### 9.1 核心设计原则

1. **渐进式建设**：先从零成本信号开始（Phase 1），再逐步引入自动化评估（Phase 2-4），避免一开始就过度设计
2. **异步评估**：LLM-as-Judge 不阻塞用户请求——评估是后台任务，用户无感知
3. **多维交叉验证**：不依赖单一指标，用检索+忠实度+正确性+用户行为四个维度交叉验证
4. **评估即文档**：评估结果本身就是 RAG 系统健康度的"体检报告"，可追溯、可对比

### 9.2 关键取舍

| 取舍 | 选择 | 理由 |
|------|------|------|
| Golden Set vs LLM-as-Judge | **两者互补** | Golden Set 做精准回归测试，Judge 做日常监控 |
| 全量 vs 采样 | **分层策略** | 轻量指标全量，Judge 评估采样 10% |
| 实时 vs 离线 | **离线为主** | Judge 评估不需要毫秒级实时，T+1 日报即可 |
| 自建 vs 外接框架 | **自建** | RAGAS/TruLens 等框架引入额外依赖，本项目体量不大，自建更可控 |

### 9.3 预期效果

完成 Phase 1-3 后，系统将具备：
- 每次请求的 RAG 质量可**追溯**（哪个 chunk 被检索、分数多少、LLM 有没有忠实引用）
- 每天一份自动化的**质量日报**（关键指标 + 与前一日对比）
- 配置变更后可做**A/B 对照**（换模型/改参数前后，指标是变好了还是变差了）
- 质量问题可**告警**（幻觉率飙升、检索延迟异常 → 自动通知）

---

*文档版本：v1.0*
*最后更新：2026-05-20*
