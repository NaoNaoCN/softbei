# RAG 系统优化升级方案

> 分析日期：2026-05-27 | 基于当前 `develop_html_postgreSQL` 分支代码

## 一、现状总览

当前 RAG 系统整体架构较为完善，已具备以下能力：

| 能力 | 状态 | 说明 |
|------|------|------|
| 父子切割 | 已启用 | parent 2000 chars / child 500 chars，Markdown 结构感知 |
| HNSW 索引 | 已启用 | m=16, ef_construction=200, 支持增量更新免维护 |
| 混合检索 | 已实现，**未启用** | 向量 + 关键词双路召回 + RRF 融合 |
| 查询改写 | 部分启用 | 去上下文化 + 画像感知已启用，多角度扩展未启用 |
| 关键词重排 | 已启用 | 基于 jieba 分词的轻量级 keyword overlap boost |
| 健康监控 | 已启用 | 滑动窗口指标采集 + 阈值告警，<5ms 开销 |
| LLM-as-Judge | 已启用 | 相关性/忠实度/完整性/引用准确性 四维评估 |
| 黄金测试集 | 已启用 | 10 条手写查询，回归检测 |
| A/B 实验 | 已实现 | 双配置对比，含指标 delta 报告 |
| 知识图谱 | 已实现，**未联动** | KG 独立构建，未与 RAG 检索融合 |

---

## 二、优化项清单

### 优先级说明
- **P0（立即执行）**：改动小、收益确定、无风险
- **P1（短期规划）**：需要一定开发量，但收益显著
- **P2（中期规划）**：需要模型/基础设施配合
- **P3（长期探索）**：前沿方案，需要验证可行性

---

### P0 — 立即执行（配置级改动）

#### 2.1 启用混合检索（已有代码，仅需改配置）

**当前状态**：`rag.hybrid.enabled = false`，实际只走纯向量检索。

**优化方案**：将 `rag.hybrid.enabled` 改为 `true`。

**收益分析**：
- 向量检索擅长语义泛化（如"梯度下降"能匹配"最优化方法"），但对专有名词、代码片段、公式编号等精确匹配能力弱
- 关键词检索（jieba + tsvector + ts_rank）擅长精确命中，与向量形成互补
- RRF 融合方案已实现，无需额外开发
- 预期 Recall@5 提升 10-20%，尤其对术语密集型查询

**风险**：极低。仅在配置层切换，出问题可秒级回滚。建议先在 A/B 实验框架中验证。

**改动位置**：`configs/config.yaml` → `rag.hybrid.enabled: true`

---

#### 2.2 启用多角度查询扩展

**当前状态**：`rag.query_rewrite_multi_query = false`，只生成单条改写查询。

**优化方案**：将 `rag.query_rewrite_multi_query` 改为 `true`。

**收益分析**：
- 将用户查询扩展为 3 条不同角度的子查询（概念定义、原理推导、应用示例、常见误区、概念关联），分别检索后 RRF 融合
- 对"解释反向传播"这类开放性查询效果显著：不同角度的子查询可能召回互补的信息片段
- 代码已完整实现（`_expand_queries()` + `retrieve_with_queries()` + RRF 融合），仅需改配置
- 代价：额外 1 次 LLM 调用（query expansion）+ 3 次 embedding 调用

**风险**：低。LLM 调用量增加约 30%，若成本敏感可设 `multi_query_count: 2`。建议 A/B 测试对比。

**改动位置**：`configs/config.yaml` → `rag.query_rewrite_multi_query: true`

---

### P1 — 短期规划（需少量开发）

#### 2.3 增加 Cross-Encoder 重排序

**当前状态**：仅有关键词重叠度的轻量级重排（`_rerank_by_keyword_overlap`），没有模型级精排。

**优化方案**：在关键词重排之后、父块回填之前，插入一道 Cross-Encoder 重排序。

```
当前流程：向量召回 → keyword boost → 父块回填 → 截断
优化流程：向量召回 → keyword boost → Cross-Encoder 精排 → 父块回填 → 截断
```

**具体实现**：
- 使用 BGE-Reranker-v2-m3（与 BGE-M3 embedding 配套，对中文友好）或 Cohere Rerank API
- 对 Top-K 候选（如 top 20）逐对计算 query-chunk 相关性分数
- 用 Cross-Encoder 分数替代原始向量分数进行排序

**收益分析**：
- Cross-Encoder 比 Bi-Encoder（向量检索）精度高 10-30%，因为 query 和 chunk 在模型内部做了全交互
- 代价：对 pre-fetch 的 N 个候选做 N 次推理，延迟增加约 100-300ms（本地部署）或 API 调用耗时
- 建议作为可选增强（`rag.rerank.cross_encoder.enabled`），可按场景决定是否启用

**改动范围**：
- `backend/rag/retriever.py`：新增 `_rerank_by_cross_encoder()` 函数
- `backend/services/llm.py`：新增 `rerank()` 函数（若用 API）
- `configs/config.yaml`：新增 `rag.rerank` 配置段

---

#### 2.4 知识图谱增强检索（GraphRAG 轻量版）

**当前状态**：知识图谱（`backend/services/kg_builder.py`）独立构建了 KGNode + KGEdge，但与 RAG 检索完全独立运作，检索时未利用图谱信息。

**优化方案**：在检索时利用知识图谱做**上下文扩充**，不改变现有检索流程：

```
用户查询 → 向量检索 Top-K chunks
         → 从 chunks 中提取知识点名称
         → 在 KG 中查找这些知识点的邻居节点（1-hop / 2-hop）
         → 将邻居节点的描述文本作为附加上下文注入 prompt
```

**具体实现**：
1. 从检索到的 chunk.text 中提取知识点名称（可用 jieba 分词后匹配 KGNode.name）
2. 查询 KGEdge 获取与这些知识点关联的节点（REQUIRES、RELATED_TO、IS_PART_OF）
3. 检索邻居节点的 KGNode.description，作为补充上下文
4. 在 `format_context()` 中增加可选参数 `kg_extra_nodes` 来追加图谱片段

**收益分析**：
- 解决"知识孤岛"问题：当前检索只能返回与查询直接相似的 chunk，遗漏了概念间的前置依赖和关联概念
- 例如：学习"反向传播"时，图谱可以自动关联"链式法则"、"梯度下降"等前置知识点，即使它们在文本中距离很远
- 对学生学习场景价值特别大，因为学习一个知识点通常需要理解其前置依赖

**改动范围**：
- `backend/rag/retriever.py`：新增 `retrieve_with_kg()` 函数
- `backend/db/vector.py`：新增 `get_kg_neighbors()` 查询函数
- `configs/config.yaml`：新增 `rag.graphrag` 配置段

---

#### 2.5 元数据感知检索（Metadata-Aware Filtering）

**当前状态**：chunk 已有丰富的元数据标签（chunk_type: 定义/定理/示例、language: 中文/英文、difficulty: 入门/进阶/高级），但检索时完全未使用。

**优化方案**：将元数据转化为检索时的过滤或加权条件。

**使用场景示例**：
- 学生是初学者 → 优先返回 `difficulty=beginner` 的 chunk
- 需要代码示例 → 优先返回 `chunk_type=example` 的 chunk
- 纯中文环境 → 过滤掉 `language=en` 的 chunk

**具体实现**：
1. 检索接口增加 `metadata_filter` 参数（`where` 子句的语义扩展）
2. 在 RRF 融合阶段，对匹配期望元数据的 chunk 做小幅加权（如 +0.05）
3. 在 Agent 调用 RAG 时传入学生的认知水平作为过滤条件

**改动范围**：
- `backend/rag/retriever.py`：`retrieve()` 增加 `metadata_preference` 参数
- `backend/db/vector.py`：`query_documents()` 支持 metadata 过滤
- `backend/agents/utils.py`：`retrieve_context()` 从 student_profile 提取偏好

---

#### 2.6 动态 Top-K 选择

**当前状态**：固定返回 `n_results=5` 条，不考虑分数分布。

**优化方案**：根据检索结果的质量动态决定返回条数。

**规则**：
- 如果 Top-1 分数 > 0.85（强相关）且 Top-1 与 Top-2 差距 > 0.1 → 只返回 Top-1（信息足够，避免冗余干扰）
- 如果前 5 条分数相近（差距 < 0.05）→ 多返回 3 条（结果不确定，给 LLM 更多选择）
- 默认仍为 5 条

**收益**：减少 LLM 输入 token 消耗（高置信度时）或提高召回覆盖率（低置信度时）。

**改动范围**：`backend/rag/retriever.py` → `_dynamic_top_k()` 函数，在截断前执行。

---

### P2 — 中期规划

#### 2.7 上下文压缩（LLM-based Context Compression）

**当前状态**：`format_context()` 超过 `context_max_tokens` 时直接截断后续 chunk，可能丢失关键时刻。

**优化方案**：引入 LLM 驱动的上下文压缩（类似 LangChain `ContextualCompressionRetriever`）：

```
检索 Top-K → 将每个 chunk 与 query 送入轻量 LLM → 提取与 query 相关的句子 → 拼接压缩结果
```

**优势**：
- 每个 chunk（2000 chars 父块）中可能只有 30% 与当前查询相关，直接注入会浪费 token 预算并引入噪声
- 压缩后可以在相同 token 预算内塞入更多 chunk 的信息

**代价**：每次检索额外 K 次快速 LLM 调用。建议使用便宜的小模型（如 qwen-turbo）做压缩。

---

#### 2.8 持久化缓存层

**当前状态**：缓存仅限制在单次请求生命周期内（Python dict），请求结束后失效。

**优化方案**：引入 Redis 作为 RAG 缓存层。

**缓存策略**：
- **Embedding 缓存**：`cache_key = md5(query)` → 复用已计算的 embedding 向量（最直接的成本节省）
- **检索结果缓存**：`cache_key = md5(query + user_id)` → TTL 1 小时，对高频知识点（如期末复习期间）有效
- **改写结果缓存**：`cache_key = md5(user_message + kp_name)` → TTL 30 分钟

**收益分析**：
- 高校场景中，同一知识点的查询高度重复（如多个学生同时学习"梯度下降"）
- embedding 缓存可减少 30-50% 的 API 调用
- 检索结果缓存可进一步减少 DB 查询

**风险**：缓存失效策略需要仔细设计（文档更新时需清除相关缓存）。

---

#### 2.9 Embedding 模型评估与选型

**当前状态**：使用 DashScope `text-embedding-v4`（1024 维），BGE-M3 路径已废弃但代码残留。

**优化方案**：
1. 使用现有的黄金测试集 + A/B 框架，对候选 embedding 模型做基准测试
2. 候选模型：
   - **BGE-M3**（本地部署，支持中英多语言，1024 维，可微调，零成本但需 GPU）
   - **GTE-Qwen2-7B-instruct**（当前 MTEB 中文榜单 Top，但模型大）
   - **stella-base-zh-v3-1792d**（轻量级中文专用，MTEB 高分）
   - 继续使用 **text-embedding-v4**（API，零运维）
3. 对比指标：Recall@5、MRR、NDCG@5、P50 分数

**关键决策点**：本地部署（零边际成本但需 GPU 运维）vs API（按量付费但零运维）。

---

#### 2.10 关键词检索升级：BM25

**当前状态**：关键词路径使用 PostgreSQL tsvector + ts_rank，基于 TF-IDF。

**优化方案**：用 BM25 替代/补充 ts_rank。BM25 对文档长度有更好的归一化，且参数可调（k1, b）。

**实现选择**：
- **pg_bm25（ParadeDB）**：PostgreSQL 扩展，原生集成，支持 BM25 + 混合搜索
- **Elasticsearch**：独立部署，功能全面但运维成本高
- **自建 BM25 索引**：用 `rank_bm25` 库在应用层构建，适合小规模（<10万 chunk）

**建议**：当前数据量在万级以下，用 `rank_bm25` 库在应用层实现即可，无需引入新基础设施。

---

### P3 — 长期探索

#### 2.11 命题式索引（Proposition Indexing / DenseX 思路）

**问题**：当前父块的 2000 字符原始文本直接作为检索单元。长文本的 embedding 往往被"稀释"，检索精度下降。

**方案**：将每个父块通过 LLM 预处理为多条**原子命题**（如"梯度下降的收敛速度依赖于学习率的选择"），每条命题独立 embedding + 索引。

- 检索时匹配的是精炼的命题而非原始文本 → 提高 precision
- 检索命中后追溯原始父块 → 保持 recall

代价：索引构建时的 LLM 调用量大幅增加（每个 chunk 约 5-10 次 LLM 调用）。

---

#### 2.12 Late Chunking / ColBERT 风格检索

**问题**：当前 embedding 是把整个 chunk（500 chars）压缩为一个 1024 维向量，丢失了细粒度的 token 级匹配信息。

**方案**：Late Chunking 为每个 token 生成独立向量，检索时做 token 级匹配（MaxSim），然后聚合到 chunk 得分。

- ColBERT 是该思路的代表方案
- 国内也有类似方案（如 Jina-ColBERT-v2 支持中文）
- 需要更换 embedding 模型和索引结构（需要存储多向量）

---

#### 2.13 查询分类与自适应路由

**方案**：在查询改写之前加入轻量级查询分类器，根据查询类型选择最优检索策略：

| 查询类型 | 检索策略 | 示例 |
|---------|---------|------|
| 事实型（factual） | 关键词优先，high score threshold | "什么是L2正则化" |
| 概念型（conceptual） | 向量优先，多角度扩展 | "比较CNN和Transformer" |
| 代码型（code） | 关键词优先，低 score threshold | "如何在PyTorch中实现dropout" |
| 导航型（navigational） | KG 优先，父块 context 宽 | "学反向传播之前需要掌握什么" |

分类器可以用少量样本 fine-tune 一个 Bert 级别的小模型，延迟 < 10ms。

---

#### 2.14 Self-Reflection / 迭代检索

**方案**：允许 LLM 在生成答案后自检，如果发现信息不足，发起补充检索。

```
检索 → 生成 → LLM 自评是否完整 → 若不完整，生成补充查询 → 二次检索 → 补充生成
```

可利用现有的 faithfulness + completeness judge 做触发判断。

---

#### 2.15 用户反馈闭环

**方案**：在前端收集用户对生成答案的隐式/显式反馈，用于持续优化检索。

- **隐式**：用户在某个资源上停留时间、是否追问（说明上次检索不足）
- **显式**：点赞/点踩、纠错按钮
- 反馈数据存入 `LearningRecord`，定期分析高频低分查询，补充到黄金测试集

---

## 三、实施路线图

```
Phase 1（本周）:  P0-2.1 启用混合检索
                  P0-2.2 启用多角度查询扩展
                  → 通过 A/B 实验框架验证收益

Phase 2（2周）:   P1-2.3 Cross-Encoder 重排序
                  P1-2.5 元数据感知检索
                  P1-2.6 动态 Top-K
                  → 预期检索精度提升 15-25%

Phase 3（1月）:   P1-2.4 GraphRAG 联动
                  P2-2.7 上下文压缩
                  P2-2.8 持久化缓存
                  → 预期上下文质量 + 成本优化

Phase 4（持续）:  P2-2.9 Embedding 选型
                  P2-2.10 BM25 升级
                  P3-2.11~2.15 前沿探索
```

---

## 四、风险与注意事项

1. **混合检索**：关键词路径依赖 jieba 分词准确度，英文术语+中文混合查询可能分词不准。建议在混合检索的 keyword 路径中同时保留原始查询的子串匹配。

2. **多查询扩展**：会增加 LLM + embedding API 调用的延迟和成本。建议设置超时（如 3s），超时则回退到单查询。

3. **GraphRAG**：KG 构建是异步后台任务，若 KG 尚未构建完成则无法增强检索，需要优雅降级。KG 节点重名问题（不同文档中的"概述"、"总结"等通用标题）需要特殊处理。

4. **缓存一致性**：文档更新后，相关的 embedding 缓存和检索结果缓存需要主动失效，否则会返回过期内容。

5. **Cross-Encoder 延迟**：如果使用 API 形式的 Cross-Encoder（如 Cohere Rerank），会增加 200-500ms 延迟。对实时性要求高的场景，需要做异步化或降级处理。

6. **不要过度优化**：每次新增一个优化模块都应在 A/B 框架中验证收益。有些优化项可能互相抵消（如多查询扩展 + 混合检索可能导致过多的候选，RRF 融合效果反而下降）。
