# pgvector 向量索引选型：IVFFlat vs HNSW

## 一、当前状态

| 项目 | 当前值 |
|------|--------|
| 索引类型 | **IVFFlat** |
| 距离度量 | cosine (`vector_cosine_ops`) |
| `lists` 参数 | 100 |
| 检索 `probes` | 10（`SET LOCAL ivfflat.probes = 10`，见 `vector.py:281`） |
| 向量维度 | 1024（DashScope text-embedding-v4） |
| 预取策略 | 3× `n_results`（max 45），后接关键词 re-rank |
| 写入模式 | 按 `doc_id` 全量删除 → 批量 `INSERT ... ON CONFLICT DO UPDATE`（见 `indexer.py:59-64`） |

索引创建 SQL（`migrations/versions/8a3f2e1b4c5d_migrate_embedding_to_pgvector.py:34-38`）：
```sql
CREATE INDEX IF NOT EXISTS ix_document_chunk_embedding_ivfflat
ON document_chunk
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);
```

---

## 二、两种索引原理简述

### IVFFlat（Inverted File Flat）

1. 对全部向量运行 **K-means 聚类**，将空间划分为 `lists` 个桶
2. 查询时，先计算 query 向量到各聚类中心的距离，选取最近的 `probes` 个桶
3. 仅在选中的桶内做精确距离计算（而非全表扫描）
4. **新插入的数据不自动进入索引** — 落入"未索引堆"（unindexed heap），直到手动或定时 `REINDEX`

### HNSW（Hierarchical Navigable Small World）

1. 构建**多层图结构**：顶层稀疏（长距离跳转），底层稠密（精细搜索）
2. 插入时实时构建图的边（贪心搜索最近邻 → 建立连接）
3. 查询时从顶层入口点出发，逐层下钻到最近邻
4. **每个新插入的向量即时加入图结构**，无需额外重建步骤

---

## 三、本项目关键因素分析

### 3.1 写入模式：按文档全量替换

这是决定索引选型的**最核心因素**。观察 `indexer.py:58-64` 和 `indexer.py:73-94`：

```python
# 预清理：按 doc_id 删除旧 chunk
for doc_id in affected_doc_ids:
    await delete_by_doc_id(doc_id)       # DELETE FROM document_chunk WHERE doc_id = :doc_id
# 批量重新插入
await upsert_documents(ids=[...], documents=[...], embeddings=[...], metadatas=[...])
```

每次用户上传/更新文档时，流程是：
1. **DELETE** 该 `doc_id` 的所有旧 chunk
2. **INSERT** 该 `doc_id` 的新 chunk（每批 128 条，API batch 25 条）

**对 IVFFlat 的致命问题**：
- DELETE 操作删除已索引的行（没问题）
- 新 INSERT 的行进入 **unindexed heap**，不会被 IVFFlat 索引覆盖
- 检索时这些新 chunk 实际上被**排除在向量搜索之外** — 只有精确的 `probes` 个桶被扫描，而未索引堆不会被扫描
- 除非手动执行 `REINDEX INDEX ix_document_chunk_embedding_ivfflat`，否则索引逐渐"空心化"
- 当前代码**没有任何 REINDEX 机制**

**对 HNSW 的优势**：
- 每次 INSERT 时自动构建图的边，新向量即时可检索
- 不需要任何定期维护任务
- DELETE + INSERT 模式下，旧数据被移除、新数据即时可用

> 结论：当前写入模式与 IVFFlat 存在**结构性不匹配**，这是一个潜在的 bug — 增量上传的文档在向量检索中实际不可见。

### 3.2 数据规模

| 规模 | 文档块数 | 场景 |
|------|----------|------|
| 小 | < 10,000 | 开发/测试阶段，少量教材 |
| 中 | 10,000 ~ 100,000 | 部署后，多位教师上传资料 |
| 大 | > 100,000 | 全量课程库，极低概率 |

当前项目处于开发阶段，`lists=100` 适合 10K-100K 级别。

**在 < 100K 规模下，HNSW 和 IVFFlat 的绝对性能差异很小**（均为毫秒级），但 HNSW 免维护的特性在中小规模同样受益。

### 3.3 检索链路延迟要求

项目是**在线学习系统**，检索是同步链路的一部分：

```
用户请求 → embedding → 向量检索 → keyword re-rank → LLM 生成 → 返回
```

- `n_results=5`，预取 `3×5=15` 条
- 延迟要求：整个检索链路应在 **200ms 以内**
- HNSW `ef_search=100` 下 1024 维检索通常 **0.1-0.5ms**，IVFFlat `probes=10` 通常 **0.5-2ms**

绝对差距在毫秒级，但 HNSW 在高并发（多个 Agent 并行检索）下更稳定，因为它不需要扫描未索引堆。

### 3.4 内存占用

1024 维向量，HNSW 参数 `M=16`：

| 规模 | IVFFlat | HNSW (M=16) | 差异 |
|------|---------|-------------|------|
| 10K chunks | ~39 MB | ~44 MB | +13% |
| 50K chunks | ~195 MB | ~220 MB | +13% |
| 100K chunks | ~390 MB | ~440 MB | +13% |
| 500K chunks | ~1.95 GB | ~2.20 GB | +13% |

HNSW 额外内存用于存储图边（每个节点 ~2×M×16 bytes/层 × 约 log(N) 层）。在 10K-100K 规模下，额外开销仅 **5-50 MB**，对现代服务器完全可以忽略。

**结论**：内存差异在本项目规模下不是决策因素。

### 3.5 索引构建速度

| 操作 | IVFFlat | HNSW |
|------|---------|------|
| 初始全量构建（10K chunks） | ~2-5s（批量 + 训练聚类中心） | ~10-30s（逐条插入建图） |
| 增量插入（100 chunks） | ~0.1s（但不进入索引） | ~1-3s（实时建图边） |
| 重建索引（REINDEX） | ~2-5s | 不需要 |

IVFFlat 的批量构建更快。但 HNSW 的 "插入即索引" 省去了 REINDEX 的维护负担。对于本项目"按文档增量更新"的模式，HNSW 的构建速度劣势只在**首次全量索引**时感知，日常增量场景反而更快（无需后续 REINDEX）。

---

## 四、pgvector 中两种索引的实际表现对比

基于 pgvector 官方基准及社区实测，**1024 维余弦距离**场景：

| 指标 | IVFFlat (lists=100, probes=10) | HNSW (M=16, ef_construction=200, ef_search=100) |
|------|-------------------------------|------------------------------------------------|
| QPS（单连接） | ~500-1000 | ~2000-5000 |
| Recall@10 | ~0.90-0.95 | ~0.97-0.995 |
| 索引构建 | 快速（需训练） | 较慢（逐条插入） |
| 增量写入后可用性 | **需 REINDEX** | **即时可用** |
| 索引文件大小 | ≈ 向量数据 | ≈ 向量数据 + 15-25% |
| 参数调优复杂度 | lists, probes | M, ef_construction, ef_search |
| 并发查询稳定性 | 良好 | 优秀（无未索引堆扫描） |
| WAL 写入量 | 批量 INSERT 时较高 | 逐条 INSERT 时分散 |

---

## 五、本项目使用 IVFFlat 的实际问题

### 问题 1：增量索引后 chunk 不可检索

当前 `index_chunks()` 先 DELETE 再 INSERT，新数据落入 unindexed heap。除非在每次索引完成后手动 `REINDEX`，否则新文档的 chunk 在向量检索中**被静默忽略**。

验证方法：上传一个文档后，立即用该文档的内容做语义检索，观察是否能命中。预期：**可能无法命中**。

### 问题 2：无自动 REINDEX 机制

代码中没有任何定期或触发式的 REINDEX 逻辑。`init_vector_db()` 仅验证连通性，不做索引维护。

### 问题 3：lists=100 参数无自适应

`lists` 的推荐值是 `sqrt(N)` 到 `N/1000`（N=总行数）。100 对 10K 数据是合理的，但对 1K 或 100K 都不是最优。当前参数是硬编码的。

---

## 六、推荐方案：切换到 HNSW

### 6.1 推荐理由

| 因素 | 权重 | IVFFlat | HNSW | 说明 |
|------|:----:|:-------:|:----:|------|
| 增量写入后即时可用 | **极高** | ❌ | ✅ | 当前写入模式与 IVFFlat 结构性不匹配 |
| 免维护 | 高 | ❌ | ✅ | 无需 REINDEX、无需 lists 调参 |
| 检索精度 | 高 | 中等 | 高 | Recall@10 从 0.93 → 0.98 |
| 检索速度 | 中 | 良好 | 更好 | QPS 提升 2-5× |
| 内存占用 | 低 | 略低 | 稍高 | 差异 < 15%，在可接受范围 |
| 构建速度 | 低 | 更快 | 稍慢 | 仅首次全量构建时感知 |

### 6.2 新迁移脚本

创建 Alembic 迁移文件，将 IVFFlat 替换为 HNSW：

```sql
-- 删除旧 IVFFlat 索引
DROP INDEX IF EXISTS ix_document_chunk_embedding_ivfflat;

-- 创建 HNSW 索引
CREATE INDEX IF NOT EXISTS ix_document_chunk_embedding_hnsw
ON document_chunk
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 200);
```

### 6.3 参数说明

| 参数 | 推荐值 | 含义 |
|------|--------|------|
| `m` | 16 | 每个节点的最大邻居数。16 是精度/内存/构建速度的黄金平衡点。增大到 32 可提升 ~2% recall 但内存翻倍 |
| `ef_construction` | 200 | 构建时搜索宽度，控制索引质量。200 在构建速度和索引质量之间平衡，可提高到 400 以获得更好的索引质量（构建时间增加约 50%） |

### 6.4 代码改动

**`backend/db/vector.py`**：将 IVFFlat 的 `SET LOCAL ivfflat.probes` 改为 HNSW 的 `SET LOCAL hnsw.ef_search`：

```python
# 原代码（vector.py:23）
_IVFFLAT_PROBES: int = 10

# 改为
_HNSW_EF_SEARCH: int = 100

# 原代码（vector.py:281）
await conn.execute(text(f"SET LOCAL ivfflat.probes = {_IVFFLAT_PROBES}"))

# 改为
await conn.execute(text(f"SET LOCAL hnsw.ef_search = {_HNSW_EF_SEARCH}"))
```

`ef_search=100` 是 pgvector 推荐的高精度设定，可根据实际延迟要求调低（`ef_search=40` 更快但 recall 略降）。

### 6.5 迁移步骤

1. 创建新 Alembic 迁移文件（见 6.2）
2. 若测试环境数据可丢弃：直接 `alembic upgrade head`
3. 若需保留数据：先 `pg_dump document_chunk`，迁移后重新索引
4. 更新 `vector.py` 中的 session 参数（见 6.4）
5. 运行 `pytest tests/ -v` 验证

---

## 七、IVFFlat 的唯一适用场景（不推荐但供参考）

如坚持使用 IVFFlat，则必须：

1. **每次 `index_chunks()` 后调用 REINDEX**：
   ```python
   await conn.execute(text("REINDEX INDEX CONCURRENTLY ix_document_chunk_embedding_ivfflat"))
   ```
   注意：`REINDEX CONCURRENTLY` 会锁表，高频上传时不可接受（每次上传锁表 5-30 秒）。

2. **根据数据量动态调整 lists**：
   ```python
   lists = max(10, int(sqrt(doc_count)))  # pgvector 推荐公式
   ```
   需要在每次索引后评估是否需要调整。

这两项改动加起来的工作量**已经超过切换到 HNSW 的成本**，且效果更差。

---

## 八、结论

| 场景 | 推荐 |
|------|------|
| 当前项目（按文档增量更新、< 100K chunks、在线检索） | **HNSW** |
| 纯静态数据、一次性批量加载、无增量写入 | IVFFlat |
| 超大规模（> 1M chunks）、内存敏感、接受定期维护 | IVFFlat |

**对本项目而言，切换到 HNSW 是"修复 bug"级别的变更，而非性能优化。** 当前 IVFFlat + 增量删除/插入的模式导致新上传文档的向量块在检索中不被索引，这是一个功能性缺陷。HNSW 的"插入即索引"特性从根本上解决了这个问题。

---

*文档生成日期：2026-05-25*
