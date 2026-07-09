# RAG 评估指标对比分析：当前系统 vs 标准方案

> 最后更新：2026-05-27 | 参照框架：RAGAs (RAG Assessment) | 基于 10 条黄金查询实测

---

## 一、概述

当前评估系统在**检索层**使用 Precision@K、Recall@K、MRR、NDCG@K、Hit Rate@K 五个指标，在**生成层**使用 Faithfulness（忠实度）、Completeness（完整度）、Citation Accuracy（引用准确性）三个 LLM-Judge 维度和衍生的 Hallucination Rate。

标准 RAGAs 框架在**检索层**以 Hit@K 和 MRR 为核心，在**生成层**以 Faithfulness、Answer Relevancy、Context Recall 为三大支柱。

本文档将逐项对比两者的定义、计算方式、差异点和内在联系。

---

## 二、检索层指标对比

### 2.1 Hit@K / Hit Rate@K

| 维度 | 当前系统 | 标准方案 |
|------|---------|---------|
| **名称** | Hit Rate@K | Hit@K |
| **公式** | `hit_queries / total_queries` | 同 |
| **输入** | `relevance_labels` (0/1/2) | `relevance_labels` (0/1) |
| **判定** | `any(r > 0 for r in labels[:k])` | 同 |
| **语义** | "至少搜到一条相关文档的查询占比" | 同 |

**结论：完全等价。** 两者定义和计算方式一致，仅有命名差异。当前系统的 Hit Rate@K 即标准 Hit@K。

### 2.2 MRR (Mean Reciprocal Rank)

| 维度 | 当前系统 | 标准方案 |
|------|---------|---------|
| **名称** | MRR | MRR |
| **公式** | `avg(1 / rank_of_first_relevant)` | 同 |
| **输入** | `relevance_labels_list` (0/1/2) | `relevance_labels_list` (0/1) |
| **秩为 1 时的值** | 1.0 | 1.0 |
| **无相关文档时** | 0.0 | 0.0 |

**结论：完全等价。** 定义、公式、边界条件处理完全一致。

### 2.3 当前系统有而标准方案没有的指标

| 指标 | 公式 | 价值 |
|------|------|------|
| **Precision@K** | `relevant_in_topK / K` | 衡量检索结果的"纯度"——搜出来的东西跑题率 |
| **Recall@K** | `relevant_in_topK / total_relevant` | 衡量检索的"覆盖力"——该搜的都搜出来没有 |
| **NDCG@K** | `DCG@K / IDCG@K` | 比 MRR 更精准——高度相关排前面比分值高，部分相关排后面分值低 |

**联系**：
- Hit@K = "有没有"（二值判断），是最低要求
- Precision@K = "纯不纯"（精确率），每多一条无关结果都会拉低
- Recall@K = "全不全"（召回率），取决于知识库中相关文档总数
- MRR = "快不快"（第一命中位置），第一个正确答案排第 1 则满分
- NDCG@K = "好不好"（排序质量），综合考虑位置和相关性等级

> **关于 P@5 的聚合值**：黄金测试集报告中展示的 `avg_precision_at_5` 是所有查询 P@5 的**算术平均值**。每条查询的 P@5 必定是 0.2 的整数倍（分子为 0-5 之间的整数，分母固定为 5），但 10 条查询的平均值可以是任意小数（如 0.960 = 9 条 1.0 + 1 条 0.6 的平均）。这与"班级平均分 87.3，不意味着有人考了 87.3 分"同理。

**建议：保留全部五个。** 它们回答不同的问题，构成了检索质量的完整画像。Hit@K 和 MRR 是"最低线"，Precision 和 Recall 是"基本面"，NDCG 是"精排线"。

---

## 三、生成层指标对比

### 3.1 Faithfulness（忠实度）

#### 当前系统实现

```
流程：
1. LLM 将 answer 拆解为独立的陈述句（statements）
2. LLM 逐句判断：能在 reference docs 里找到依据吗？
   → "supported" / "unsupported"
3. faithfulness = supported_count / total_statements
4. hallucination_rate = 1.0 - faithfulness
```

关键特征：
- **单次 LLM 调用**完成拆解 + 判断
- 每句附带 `evidence` 字段（定位到 reference 中的具体段落）
- LLM 直接输出 0.0-1.0 的 faithfulness 分数
- temperature=0.0 保证一致性

#### RAGAs 实现

```
流程：
1. LLM 将 answer 拆解为独立的 claims（声明）
2. 对每条 claim，LLM 判断：能在 context 里找到依据吗？
   → "支持" / "不支持"（或 "Yes" / "No"）
3. faithfulness = supported_claims / total_claims
```

#### 对比

| 维度 | 当前系统 | RAGAs |
|------|---------|-------|
| 拆解方式 | LLM 一次完成拆解+判断 | LLM 拆解 claims → 逐条判断（可分步） |
| 判断粒度 | 语句级（sentence） | 声明级（claim），一个句子可能含多条 claim |
| 证据定位 | 有（evidence 字段） | 有（verifiable by design） |
| 输出格式 | `{"statements": [...], "faithfulness": X}` | claims 列表 + 逐条 verdict |
| 幻觉率衍生 | Hallucination Rate = 1.0 - faithfulness | 同 |

**差异分析**：

1. **拆解粒度**：RAGAs 的 claim 比当前系统的 statement 更细。一个复合句 "梯度下降通过计算损失函数的梯度来更新参数" 在 RAGAs 中可能被拆为两条 claim（"梯度下降计算梯度" + "梯度下降更新参数"），而当前系统可能作为一个 statement 整体判断。更细粒度意味着更精准的幻觉检测。

2. **证据链**：当前系统对每句 statement 输出 `evidence` 字段，比 RAGAs 多了溯源能力。这是一个优势——可以定位到具体哪段 reference 支撑了哪句话。

3. **本质一致性**：两者的核心逻辑完全一致——**将回答拆成原子断言，逐条到上下文中找依据**。命名相同（都叫 Faithfulness），意义相同，只是实现粒度略有差异。

**联系：两者等价位 90%+。** 当前系统的 Faithfulness 可以作为 RAGAs Faithfulness 的直接等价物使用。如需更精细的 claim 级拆解，只需调优 Judge 2 的 prompt，无需架构改动。

---

### 3.2 Answer Relevancy（答案相关性）

#### 当前系统：无直接等价指标

当前系统评估的是 **Chunk Relevance**（检索相关性），而非 Answer Relevancy（答案相关性）：

```
当前 Chunk Relevance 问的是：
  "搜出来的文档和问题相关吗？" → 这是检索评估

Answer Relevancy 问的是：
  "生成的答案和问题相关吗？" → 这是生成评估
```

它们是不同层面的东西。一段完美相关的检索结果可以被 LLM 写成一个跑题的答案，反之也可以从一个不太相关的文档中提炼出相关的回答。

#### RAGAs Answer Relevancy 算法

```
流程：
1. LLM 从生成的 answer 中反向生成 N 条问题（"这个答案能回答哪些问题？"）
   例如 answer="梯度下降通过迭代更新参数来最小化损失函数"
        → 反向问题：["什么是梯度下降？", "梯度下降如何工作？", "损失函数是什么？"]
2. 将反向问题的 embeddings 与原始 query 的 embedding 做余弦相似度
3. answer_relevancy = mean(cos_sim(q_reverse_i, q_original))
```

关键特征：
- **不依赖 reference context**：只看 answer 和 query 的关系
- **需要 embedding 模型**：计算反向问题与原始问题的语义相似度
- **LLM 仅用于问题生成**：评分用向量相似度而非 LLM 判断，更稳定可复现

#### 为什么需要它

| 场景 | Faithfulness 能发现 | Answer Relevancy 能发现 |
|------|-------------------|------------------------|
| AI 编造了不存在的公式 | 是（逐句核实） | 可能（如果编造公式导致跑题） |
| AI 忠实复述了参考资料，但答非所问 | **否**（每句话都有依据） | **是**（答案关联的问题 ≠ 用户问的问题） |
| AI 引用了相关但非核心的内容 | **否** | **是** |

#### 当前系统的部分替代：Completeness

当前系统的 Completeness 从**相反方向**部分回答了类似问题——它问的是"该讲的内容都讲了吗"，而 Answer Relevancy 问的是"讲的内容都和问题有关吗"。

| 指标 | 方向 | 问什么 |
|------|------|--------|
| Answer Relevancy | 答案 → 问题 | "这个答案是在回答我的问题吗？" |
| Completeness | 知识点 → 答案 | "这个知识点该讲的内容，答案覆盖到了吗？" |

两者互补但不重叠。

**结论：Answer Relevancy 是当前系统的空白。** 建议增加此指标，防止"忠实但跑题"的答案逃过检测。

---

### 3.3 Context Recall（上下文召回）

#### 当前系统：Completeness（近似的替代）

```
当前 Completeness 流程：
1. LLM 动态生成知识点的 4-8 个"应涵盖方面"
   例如 "梯度下降" → ["定义", "数学原理", "学习率", "优化变体", "常见误区"]
2. LLM 逐方面判断答案覆盖程度：covered / partial / missing
3. completeness = (covered + 0.5 × partial) / total_aspects
```

#### RAGAs Context Recall 算法

```
流程：
1. LLM 从 reference context 中提取所有关键 claims
   例如 context="梯度下降通过...学习率控制步长...可能陷入局部最优"
        → claims: ["使用迭代更新", "学习率控制步长", "可能陷入局部最优"]
2. LLM 判断每条 claim 是否在 answer 中被体现
3. context_recall = attributed_claims / total_claims
```

#### 关键差异

| 维度 | 当前 Completeness | RAGAs Context Recall |
|------|------------------|---------------------|
| **参照物** | LLM 生成的"理想知识点清单" | **实际检索到的 reference context** |
| **可验证性** | 低（依赖 LLM 对知识点的认知） | **高**（context 是 concrete 的，可直接对比） |
| **评估对象** | answer 对知识体系的覆盖 | answer 对**本次检索结果**的利用率 |
| **动态性** | 知识点不变则评估维度不变 | 每次检索的 context 不同，评估维度随之变化 |

#### 深度分析

当前系统的 Completeness 有一个根本性问题：**LLM 生成的"应涵盖方面"可能与实际检索到的 context 不匹配**。

例如：
- Context 包含了梯度下降的数学推导，但 LLM 认为"应涵盖方面"包括 Python 代码示例
- 结果：即使 answer 完美复述了 context 的所有内容，completeness 仍然不高
- 这不是 answer 的问题，而是 LLM 的"期望清单"和实际可用资源之间的错位

RAGAs 的 Context Recall 则没有这个问题——它直接检查"context 里有的内容，answer 引用了多少"。这是从"应该讲什么"（知识驱动）到"能用什么讲了什么"（数据驱动）的视角转换。

**结论：Completeness 和 Context Recall 回答不同的问题，建议两者共存。**
- Completeness → "这个知识点的讲解是否全面"（面向学习效果）
- Context Recall → "检索到的资料是否被充分利用"（面向 RAG 效率）

---

## 四、指标矩阵总览

### 当前系统已覆盖的指标

| 层 | 指标 | 标准等价性 | 状态 |
|----|------|-----------|------|
| 检索 | Hit@K / Hit Rate@K | **完全等价** | 已有 |
| 检索 | MRR | **完全等价** | 已有 |
| 检索 | Precision@K | 标准辅助指标 | 已有 |
| 检索 | Recall@K | 标准辅助指标 | 已有 |
| 检索 | NDCG@K | 标准辅助指标 | 已有 |
| 生成 | Faithfulness | **高度等价（~90%）** | 已有 |
| 生成 | Hallucination Rate | 标准衍生指标 | 已有 |
| 生成 | Citation Accuracy | 独有优势 | 已有 |

### 当前系统的空白

| 层 | 指标 | 标准重要性 | 说明 |
|----|------|-----------|------|
| 生成 | **Answer Relevancy** | 高 | 检测"忠实但跑题"的答案，当前无覆盖 |
| 生成 | **Context Recall** | 高 | 检测检索到的 context 是否被充分利用，当前 Completeness 是近似替代 |

### 独有指标（相对标准方案的优势）

| 指标 | 价值 |
|------|------|
| NDCG@K | 比 MRR 更精准的排序质量评估 |
| Citation Accuracy | 验证 [n] 引用标注，标准方案无此维度 |
| Completeness | 面向学习场景的关键维度（答案是否覆盖知识点全貌） |
| Completeness-aspects 动态生成 | 适配任意知识点，无需人工维护 checklist |

---

## 五、建议：填补空白的实现路径

### 5.1 增加 Answer Relevancy（建议优先级：高）

**实现难度：中**。需要 Embedding API 调用，但不需要额外训练或标注。

```
方案：
1. Judge 5（新增）：Answer Relevancy Judge
   - 输入：query, generated_answer
   - Step 1：LLM 从 answer 反向生成 3-5 条问题
     Prompt: "这个答案可以回答哪些问题？列出 3-5 个"
   - Step 2：将反向问题的 embeddings 与原始 query embedding 做 cosine similarity
   - 输出：answer_relevancy = mean(cos_sim_i)

2. 集成到 evaluate_full() 中，与 Judge 2/3 并行执行
3. 在 GenerationEvalRecord 中增加 answer_relevancy 字段
```

**估计成本**：每次额外 1 次 LLM 调用（生成反向问题）+ 5 次 Embedding 调用。

### 5.2 增加 Context Recall（建议优先级：中）

**实现难度：低**。可以复用现有 Judge 基础设施。

```
方案：
1. Judge 6（新增）：Context Recall Judge
   - 输入：retrieved_contexts, generated_answer
   - Step 1：LLM 从 context 中提取 N 条关键信息
     Prompt: "以下是从知识库检索到的参考资料，请从中提取所有关键信息点"
   - Step 2：LLM 逐条判断每个信息点是否在 answer 中被体现
   - 输出：context_recall = attributed / total

2. 与现有 Completeness 并存（它们回答不同的问题）
3. 在 GenerationEvalRecord 中增加 context_recall 字段
```

**估计成本**：每次额外 2 次 LLM 调用。

### 5.3 维持现有独有优势

| 指标 | 维持理由 |
|------|---------|
| Completeness | 学习场景核心维度，与 Context Recall 互补 |
| Citation Accuracy | 标准方案无此维度，是显式 RAG 场景的重要评估 |
| NDCG@K | 比 MRR+Hit@K 更完整地刻画排序质量 |

---

## 六、指标选择速查表

### 日常开发（快速迭代）

```
layer_1_fast = [Hit@K, MRR, Faithfulness, Hallucination]
理由：4 个指标即可覆盖检索和生成的最关键维度
```

### 发版前评估（全面检查）

```
layer_2_full = [
    Hit@K, MRR, Precision@K, Recall@K, NDCG@K,  # 检索 5 件套
    Faithfulness, Hallucination,                   # 生成基础
    Answer Relevancy, Context Recall,              # 生成补充（新增）
    Completeness, Citation Accuracy                # 独有优势
]
```

### CI 回归检测（黄金测试集）

```
golden_check = [Faithfulness, Completeness, Answer Relevancy]
理由：聚焦生成质量回归，检索质量用单独的 retrieval_health_check
```

---

## 七、总结

| 维度 | 当前系统 vs 标准方案 | 差距 |
|------|-------------------|------|
| Hit@K / MRR | 完全等价 | 无差距 |
| Faithfulness | 高度等价（90%+），多 evidence 溯源 | 无差距，有优势 |
| Answer Relevancy | **无覆盖** | 中等差距，建议新增 |
| Context Recall | Completeness 是近似替代，但视角不同 | 小差距，建议新增 |

当前系统的检索指标已经**完全覆盖**标准方案的 Hit@K 和 MRR，且额外拥有 Precision、Recall、NDCG 三个更精细的指标。

生成层的 Faithfulness 与标准方案基本等价，独有的 Citation Accuracy 和 Completeness 是面向学习场景的差异化优势。

**两个明确空白**：Answer Relevancy（防止"忠实但跑题"）和 Context Recall（衡量检索资料利用率），建议分阶段补充。

---

## 八、黄金测试集评估实践

### 8.1 评估架构（文件化）

评估结果**不再持久化到 PostgreSQL**，改为纯文件输出。每次运行 `python -m backend.evaluation.golden_dataset --run` 在 `logs/` 下生成一个精简报告文件。

```
评估流程：
1. 加载 golden_queries.yaml（10 条查询，覆盖 10 个知识点）
2. 逐条执行：向量检索 → LLM 生成回答 → LLM Judge 打分
3. _build_report() 聚合逐条结果 → avg 三指标 + 通过率
4. _detect_regression() 对比 logs/golden_last_run.json
5. RAGAnalyzer.analyze_golden_report() 分析瓶颈/模式/建议
6. format_compact_report() → 输出 logs/golden_eval_{timestamp}.md
```

### 8.2 报告结构（精简版）

每份报告只包含 4 个板块：

| 板块 | 内容 |
|------|------|
| **核心指标** | Faithfulness / Completeness / P@5 的当前值、阈值、PASS/FAIL 状态 |
| **未通过查询** | 逐条列出未达标查询，标明 faith + comp 各自通过情况 |
| **分析结论** | 瓶颈排序、关键发现（1-3 条）、趋势判断 |
| **改进建议** | 按优先级（HIGH/MEDIUM/LOW）给出可操作建议 |

### 8.3 阈值配置

来自 `backend/evaluation/analyzer.py:_THRESHOLDS`：

| 指标 | 阈值 | 方向 | 说明 |
|------|------|------|------|
| Faithfulness | 0.70 | high（越高越好） | 低于 0.70 触发 FAIL |
| Completeness | 0.60 | high（越高越好） | 低于 0.60 触发 FAIL |
| P@5 | 0.60 | high（越高越好） | 低于 0.60 触发 FAIL |

瓶颈严重程度分级：
- **critical**: 当前值与阈值的差距 < -0.15
- **warning**: 差距 < 0（即低于阈值但不超过 0.15）
- **ok**: 差距 ≥ 0（高于阈值）

### 8.4 逐查询评估流程

每条 GoldenQuery 的评估路径（`golden_dataset.py:run_golden_evaluation()`）：

```
1. retrieve_by_kp(kp_name, n_results=5) → 5 个 chunk
2. 拼接 context + prompt，LLM 生成 answer（temperature=0.3, max_tokens=2000）
3. judge.evaluate_full(query, kp_name, chunks, answer) → LLM Judge 打分
   - Judge 1 (P@5): 对 5 个 chunk 逐条标注 relevance (0/1/2)
   - Judge 2 (Faithfulness): 拆解 answer 为 statements，逐句判断 supported/unsupported
   - Judge 3 (Completeness): LLM 动态生成知识点的 4-8 个方面，判断 covered/partial/missing
4. faith_pass = faithfulness_score >= query.min_faithfulness
   comp_pass = completeness_score >= query.min_completeness
5. 聚合为 GoldenEvalResult
```

### 8.5 回归检测

对比 `logs/golden_last_run.json`（上次运行保存的快照）：

```
任一度量下降 > 10% → regression_detected = True
- faithfulness: last_val → current_val (delta%)
- completeness: last_val → current_val (delta%)
- precision_at_5: last_val → current_val (delta%)
```

---

## 九、父子切割策略对指标的影响

### 9.1 策略说明

父子切割将文档分为两个层级：

| 层级 | 大小 | 嵌入 | 用途 |
|------|------|------|------|
| **子块 (child)** | 500 字符 | 是 | 向量检索（小粒度精确匹配） |
| **父块 (parent)** | 2000 字符 | 否 | LLM 上下文（大粒度完整语义） |

检索流程：query → 向量搜索匹配子块 → 通过 `parent_chunk_id` 回填父块文本 → LLM 获得更完整的上下文。

### 9.2 实测对比（10 条黄金查询，2026-05-27）

| 指标 | 无父子切割 | 启用父子切割 | 变化 |
|------|-----------|-------------|------|
| P@5（子块级） | 0.900 | 0.960 | **+6.7%** |
| Faithfulness | — | 0.887 | — |
| Completeness | — | 0.417 | — |

关键发现：父子切割提升了检索精度（P@5），因为较小的子块更容易与 query 语义匹配。但 Completeness 仍然偏低（0.417），说明知识库内容本身存在缺口，非切分策略能解决。

### 9.3 配置项

`configs/config.yaml` → `rag.parent_chunking`:

```yaml
parent_chunking:
  enabled: true
  parent_max_chars: 2000       # 父块最大字符数
  child_chunk_size: null       # null=使用 rag.chunk_size (500)
  child_chunk_overlap: 100     # 子块重叠字符数
  score_weight: "max"          # 子块分数聚合为父块分数的方式
  parent_split_lookback: 400   # 父块切分安全边界
```

---

## 十、当前系统实测数据（2026-05-27）

### 10.1 核心指标

| 指标 | 当前值 | 阈值 | 状态 |
|------|--------|------|------|
| Faithfulness | 0.887 | 0.70 | PASS |
| Completeness | 0.417 | 0.60 | **FAIL** |
| P@5 | 0.960 | 0.60 | PASS |
| 通过率 | 10% (1/10) | — | — |

### 10.2 瓶颈诊断

首要瓶颈是 **Completeness**（0.42 vs 阈值 0.60，差距 -0.18 → critical）。

相关性模式检测：
- `kb_coverage_issue`: **True**（P@5 > 0.60 但 Completeness < 0.50）
- 诊断结论：检索精度好（P@5=0.96）但完整度不足 → **知识库内容存在缺口**，非检索策略问题

### 10.3 查询分类

| 类别 | 数量 | 含义 |
|------|------|------|
| strong | 1 | Faithfulness + Completeness 双达标 |
| retrieval_weak | 4 | Faithfulness 达标，Completeness 不达标 |
| generation_weak | 1 | Faithfulness 不达标，Completeness 达标 |
| both_weak | 4 | 双侧不达标 |

9/10 的查询在 Completeness 维度不达标，验证了 KB 覆盖不足是系统性问题。

### 10.4 改进路线图

按优先级排序：

1. **[HIGH]** 为薄弱知识点扩充文档资源（当前零通过率知识点：梯度下降、反向传播、过拟合、激活函数、卷积神经网络等）
2. **[HIGH]** 增大知识库文档覆盖广度（当前 KB 仅覆盖 AI 入门级别，深度不足）
3. **[MEDIUM]** 增大 `n_results` 从 5 到 8-10，以增加检索广度补偿 KB 不足
4. **[MEDIUM]** 调整 chunk_size 或父子切割参数，确保每个 chunk 语义完整

---

> 文档版本：v2.0 | 最后更新：2026-05-27 | 参照：RAGAs v0.1.x | 实测数据：golden_eval_20260527_081215
