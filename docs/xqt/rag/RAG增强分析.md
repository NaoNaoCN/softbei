# RAG 系统增强分析：元数据、关键词融合检索与实时更新

> 分析日期：2026-05-21 | 最后更新：2026-05-27
> 当前 RAG 方案：pgvector 向量检索 (HNSW) + jieba 关键词重排序 + JSONB 元数据

---

## 修订历史

| 日期 | 变更 |
|------|------|
| 2026-05-21 | 初版：分析三项增强（元数据、实时更新、关键词融合）的可行性 |
| 2026-05-25 | 更新：标注 Phase 1（元数据）已完成；更新索引方案为 HNSW；新增 HNSW 迁移说明 |
| 2026-05-25 | 更新：Phase 2b 层次 3（增量索引）实施，新增 content_hash 列 + index_chunks() 增量 diff 逻辑 |
| 2026-05-27 | **回退增量索引**：Web 上传流程每次生成新 Snowflake doc_id，chunk_id 无交集，增量 diff 无法命中旧数据，零收益。代码已回退为全量替换策略（delete_by_doc_id + embed all + upsert all）。详见 `INCREMENTAL_INDEXING.md` 第 6.3 节。 |
| 2026-05-27 | **更新关键词融合状态**：混合检索基础设施（retrieve_keyword + retrieve_hybrid + RRF 融合）已完整实现，但 `config.rag.hybrid.enabled: false`，当前未启用。实际使用的是 jieba + ILIKE 方案（非 PostgreSQL FTS 方案）。 |

---

## 1. 当前 RAG 架构回顾

在分析三项增强之前，先理清当前系统的数据流：

```
文档导入
  loader.py (解析 → 切分 → TextChunk, 自动填充 language + course 元数据)
    → indexer.py (全量替换: delete_by_doc_id → embed all → upsert all)
      → vector.py (INSERT ... ON CONFLICT DO UPDATE, metadata → JSONB 列)

语义检索（单路向量，当前默认）
  retriever.py::retrieve()
    → get_embedding(query)           # 查询向量化
    → query_documents()              # pgvector HNSW <=> 余弦距离, SET LOCAL hnsw.ef_search=100
    → _parse_results()               # 距离→相似度, 阈值过滤, 拆分固定字段/扩展元数据
    → _rerank_by_keyword_overlap()   # jieba 关键词重叠加权 (最高 +0.25)
    → _resolve_parent_chunks()       # 父块回填 + 去重
    → format_context()               # 格式化为 LLM prompt, 渲染 metadata 标签

混合检索（已实现，未启用）
  retriever.py::retrieve_hybrid()
    → 并行: retrieve() + retrieve_keyword()
    → _rrf_fusion_cross_path()       # RRF 跨路融合
    → _rerank_by_keyword_overlap()   # 重排序
    → _resolve_parent_chunks()       # 父块回填
```

当前 `document_chunk` 表字段：

```
┌────────────────┬──────────────┬──────────────────────────────┐
│ 字段            │ 类型          │ 用途                         │
├────────────────┼──────────────┼──────────────────────────────┤
│ id             │ BIGINT        │ 主键 (Snowflake)              │
│ chunk_id       │ VARCHAR(128)  │ 唯一业务标识 (UNIQUE)          │
│ doc_id         │ VARCHAR(128)  │ 所属文档                      │
│ collection_name│ VARCHAR(64)   │ 集合名 (默认 knowledge_base)   │
│ text           │ TEXT          │ 文本内容                      │
│ embedding      │ vector(1024)  │ 语义向量 (HNSW 索引)          │
│ source         │ VARCHAR(512)  │ 原始文件路径                   │
│ page           │ INTEGER       │ 页码 (PDF)                    │
│ section        │ VARCHAR(256)  │ 章节标题                      │
│ user_id        │ VARCHAR(64)   │ 用户隔离 (+ B-tree 索引)       │
│ metadata       │ JSONB         │ 扩展元数据 (GIN 索引) ✅       │
│ parent_chunk_id│ VARCHAR(128)  │ 父块引用 (父子切割)            │
│ is_parent      │ BOOLEAN       │ 是否为父块 (默认 false)        │
│ created_at     │ DATETIME      │ 创建时间                      │
└────────────────┴──────────────┴──────────────────────────────┘
```

**向量索引方案**：已于 2026-05-25 从 IVFFlat 切换到 **HNSW**（`M=16, ef_construction=200, ef_search=100`），详见 `migrations/versions/6f9a2b3c4d5e_switch_ivfflat_to_hnsw.py`。HNSW 支持"插入即索引"，无需定期 REINDEX。

---

## 2. 增强一：元数据字段 ✅ 已完成

> 实施日期：2026-05-21（迁移 `5d8e1f2a3b4c`）
> 当前状态：**全链路已实现**，从 loader 到 retriever 的 format_context 均已打通。

### 2.1 实现方案

在 `document_chunk` 表添加 `metadata JSONB` 列 + GIN 索引：

```sql
ALTER TABLE document_chunk ADD COLUMN metadata JSONB DEFAULT '{}';
CREATE INDEX ix_document_chunk_metadata ON document_chunk USING GIN (metadata);
```

### 2.2 当前实现状态（逐组件核实）

| 组件 | 文件 | 状态 |
|------|------|:----:|
| ORM 模型 | `models.py` — `mapped_column("metadata", JSONB, default=dict)` | ✅ |
| Alembic 迁移 | `migrations/versions/5d8e1f2a3b4c` — JSONB 列 + GIN 索引 | ✅ |
| Loader 自动填充 | `loader.py` — 自动检测 `language`, 提取 `course` | ✅ |
| Indexer 传递 | `indexer.py` — `**c.metadata` 合并到 metadatas | ✅ |
| Vector DB 写入 | `vector.py` — `_convert_metadata_to_columns` 序列化 JSONB | ✅ |
| Vector DB 读取 | `vector.py` — `query_documents` 返回 metadata | ✅ |
| Retriever 传递 | `retriever.py` — `RetrievedChunk.metadata: dict` | ✅ |
| Retriever 解析 | `retriever.py` — `_parse_results` 拆分固定/扩展字段 | ✅ |
| Context 渲染 | `retriever.py` — `format_context` 渲染中文标签 | ✅ |

### 2.3 Context 中的元数据渲染

`format_context()` 已将 metadata 字段渲染为中文标签，示例输出：

```
[1] （来源：notes.md，第2页 [定义, 中文, 进阶]）
梯度下降是一种迭代优化算法...
```

| metadata key | 中文标签映射 |
|-------------|-------------|
| `chunk_type` | `definition→定义`, `theorem→定理`, `example→示例`, `exercise→习题`, `summary→总结` |
| `language` | `zh→中文`, `en→英文`, `mixed→中英混合` |
| `difficulty` | `beginner→入门`, `intermediate→进阶`, `advanced→高级` |

### 2.4 待扩展的能力

以下能力已有基础设施但尚未充分利用：

- **检索时按元数据过滤**：`retrieve()` 的 `where` 参数已支持过滤，但缺少白名单校验。当前调用方未主动使用。
- **自动填充更多元数据**：`loader.py` 目前仅自动填充 `language` 和 `course`，`chunk_type`、`difficulty` 等字段可通过 LLM 分类调用在索引时填充。
- **知识库分析**：可利用 JSONB GIN 索引统计内容类型分布、难度分布。

### 2.5 安全加固建议

为 `_build_where_clause` 添加列名白名单（`{"user_id", "doc_id", "collection_name", "metadata"}`），防止 SQL 注入风险。当前 `where` 参数的 key 名直接拼入 SQL，虽然调用方均为内部 Agent 代码，但作为数据库接口应做防御性校验。

---

## 3. 增强二：实时更新

### 3.1 现状分析

当前索引流程采用**全量替换策略**：

```python
# indexer.py::index_chunks — 全量替换
# 1. 收集所有唯一 doc_id
unique_doc_ids = set(c.doc_id for c in chunks if c.doc_id)

# 2. 对每个 doc_id 先删除旧数据
for doc_id in unique_doc_ids:
    await delete_by_doc_id(doc_id, collection_name=collection_name)

# 3. 父块写入（无嵌入）
# 4. 子块嵌入 + upsert（分批，每批 ≤10 条）
```

### 3.2 增量索引：已回退 ❌

> 实施日期：2026-05-25 | 回退日期：2026-05-27

增量索引（基于 content_hash MD5 的三阶段 diff）已于 2026-05-25 实施，但在 2026-05-27 **回退**。

**回退原因**：Web 上传流程每次生成新的 Snowflake doc_id（`doc_{hex(snowflake)[:N]}`），导致同一文件重复上传时 chunk_id 完全不同（chunk_id = `{doc_id}_{index}`），增量 diff 的 old_ids ∩ new_ids = ∅，所有 chunk 被标记为 INSERT，**增量 skip 数为 0**。只有 CLI 流程（`index_file`/`index_directory`，doc_id = 文件名 stem）能触发增量 skip。

这意味着在项目的主要使用场景（Web 上传）中，增量索引的 hash diff 机制完全无法发挥作用。详细分析见 `INCREMENTAL_INDEXING.md` 第 6.3 节。

**回退内容**：
- 移除 `content_hash` 列及复合索引 `ix_document_chunk_doc_id_hash`
- 移除 `get_chunk_hashes_by_doc_id()` 函数
- `index_chunks()` 简化为全量替换（delete → embed → upsert）
- 删除迁移文件 `7a1b2c3d4e5f_add_content_hash.py`

### 3.3 实时更新的三个层次

```
层次 1: 手动触发重新索引
  └─ 用户上传/修改文档 → API 调用 → 全量重索引
  └─ 状态: ✅ 已实现

层次 2: 文件变更检测 + 自动触发
  └─ 监控文件系统 → 检测到修改 → 自动重索引
  └─ 状态: ❌ 未实现

层次 3: 增量更新（只重索引变化的 chunk）
  └─ diff 文档内容 → 只更新变化部分 → 无需全量重索引
  └─ 状态: ❌ 已回退（Web 上传流程无法触发增量 skip）
```

### 3.4 增量更新的前置条件

如果要重新启用增量索引，需先解决 doc_id 稳定性问题。推荐方案：

| 方案 | doc_id 来源 | 优点 | 缺点 |
|------|------------|------|------|
| A: 文件内容哈希 | `"doc_" + md5(file_bytes)` | 天然幂等 | 文件内容变了 doc_id 也变，旧数据变孤儿 |
| B: user_id + 原始文件名 | `"doc_{user_id}_{original_name}"` | 简单直观 | 改名后视为新文档 |
| C: ResourceMeta.kp_id 复用 | 检测同名文件时复用已有 kp_id | 与 ResourceMeta 表对齐 | 需额外查表逻辑 |
| D: 前端显式声明"更新" | 上传时传入已有 doc_id | 语义明确 | 需前端配合 |

推荐 **C + D 结合**：前端提供"更新文档"入口传已有 `doc_id`；后端在上传接口中检测是否已有同名文档并提供复用选项。

### 3.5 关于 HNSW 索引的特别说明

HNSW 的最大优势是**插入即索引**——每个新插入的向量即时加入图结构，无需任何后台维护任务。

HNSW 的参数配置（`vector.py`）：

| 参数 | 值 | 说明 |
|------|-----|------|
| `M` | 16 | 每个节点的最大邻居数，精度/内存/速度的平衡点 |
| `ef_construction` | 200 | 构建时搜索宽度，控制索引质量 |
| `ef_search` | 100 | 查询时搜索宽度，SET LOCAL 会话级设定 |

---

## 4. 增强三：关键词检索融合

### 4.1 现状分析

当前系统已有两层关键词参与：

**第一层：关键词召回路径（retrieve_keyword）** ✅ 已实现

```python
# retriever.py::retrieve_keyword
# jieba 精确模式分词 → 过滤停用词和单字 → PostgreSQL ILIKE 匹配
keywords = _tokenize_keywords(query)  # jieba.lcut, 去停用词, 去单字
# → query_keyword() 对每个关键词执行 text ILIKE '%kw%'
# → 按匹配关键词数量 (match_count) 降序排列
```

**第二层：关键词重排序（_rerank_by_keyword_overlap）** ✅ 已实现

```python
# retriever.py::_rerank_by_keyword_overlap
# 计算每个 chunk 命中 query 关键词的数量，按重叠比例加权
boost = min(overlap / max(len(keywords), 1), 1.0) * 0.25  # 最高 +0.25
```

### 4.2 混合检索（retrieve_hybrid）✅ 已实现，未启用

`retrieve_hybrid()` 已完整实现（`retriever.py`），并行执行向量召回 + 关键词召回，RRF 跨路融合后返回 Top-K：

```
用户查询: "反向传播算法的数学推导"

向量路径 (retrieve):                      关键词路径 (retrieve_keyword):
  HNSW embedding <=> query_vector           jieba 分词 → ILIKE 匹配
  → cosine_similarity → score_sem           → match_count → score_kw
                    \               /
                     RRF (Reciprocal Rank Fusion)
                     k=60, weights: vector=1.0, keyword=1.0
                              │
                     _rerank_by_keyword_overlap
                              │
                     _resolve_parent_chunks
                              │
                         排序返回
```

**当前未启用的原因**：`config.rag.hybrid.enabled: false`。打开开关即可使用。

```yaml
# configs/config.yaml
rag:
  hybrid:
    enabled: false          # true = 混合检索, false = 仅向量检索（当前默认）
    paths: [vector, keyword]
    rrf_k: 60
    vector_weight: 1.0
    keyword_weight: 1.0
```

### 4.3 与设计文档中 PostgreSQL FTS 方案的区别

原始设计文档（第 4.3 节）提出使用 PostgreSQL `tsvector`/`tsquery` + jieba 分词。**实际实现采用了更轻量的 jieba + ILIKE 方案**：

| 对比维度 | 原始方案（tsvector） | 实际实现（ILIKE） |
|----------|-------------------|-------------------|
| SQL 复杂度 | 需 tsvector 列 + GIN 索引 | 直接 ILIKE，无额外列 |
| 分词 | jieba → `to_tsvector('simple', tokens)` | jieba → `text ILIKE '%kw%'` |
| 排序 | `ts_rank()` | `match_count`（匹配到的关键词数量） |
| 精度 | 词级匹配 + 权重 | 子串匹配（更宽松） |
| 性能 | GIN 索引加速 | 全表扫描（当前数据量可接受） |

ILIKE 方案的优势是零 schema 变更、实现简单。当数据量增长到 ILIKE 性能不足时，可升级为 tsvector 方案（需新建列 + GIN 索引）。

### 4.4 RRF 融合策略

当前 `_rrf_fusion_cross_path()` 实现（`retriever.py`）：

- 各路分别按排名计算 RRF 分数：`w / (k + rank)`
- 按 `chunk_id` 去重：同 chunk 出现在多路时，保留更高原始分数的 chunk 对象，累加 RRF 分
- 权重可配置：`vector_weight` 和 `keyword_weight`，当前均为 1.0

### 4.5 收益评估

| 收益 | 说明 |
|------|------|
| **召回率提升** | 向量检索可能漏掉精确术语匹配的 chunk，关键词路径填补这个漏洞 |
| **精确匹配** | 学生搜索"Sigmoid 函数求导"时，即使语义向量不够近，关键词也能命中 |
| **零额外依赖** | jieba 纯 Python 分词 + ILIKE 匹配，无需 PG 扩展 |
| **配置灵活** | `hybrid.enabled` 一键开关，权重和路径均可按场景调整 |

---

## 5. 三项增强的优先级与依赖关系

```
           ┌──────────────────┐
           │   元数据字段       │  ← ✅ 已完成 (2026-05-21)
           │   Phase 1         │
           └────────┬─────────┘
                    │ 提供 chunk_type、difficulty 等字段
                    ▼
┌──────────────────────┬──────────────────────┐
│    实时更新           │   关键词融合检索       │
│    优先级 P2          │   优先级 P2           │
│    依赖：稳定的 doc_id │    依赖：无            │
│    当前：全量替换      │    当前：已实现，未启用  │
└──────────────────────┴──────────────────────┘
```

### 实施路线

| 阶段 | 内容 | 预估工作量 | 状态 |
|------|------|-----------|:----:|
| **Phase 1** | 元数据字段 — JSONB 列 + 自动填充 + 检索过滤 + Context 渲染 | 2-3 天 | ✅ 已完成 |
| **Phase 2a** | 关键词融合 — jieba + ILIKE + RRF 混合检索 | 3-4 天 | ✅ 已实现（`hybrid.enabled: false`） |
| **Phase 2b** | 增量索引 — content_hash + 三阶段 diff | 2-3 天 | ❌ 已回退 |

### Phase 1 已交付能力

| 能力 | 说明 |
|------|------|
| JSONB 元数据列 | `document_chunk.metadata` + GIN 索引，支持高效 JSONB 路径查询 |
| 自动语言检测 | loader 解析时自动标记 `zh`/`en`/`mixed` |
| 自动课程标记 | loader 从文件路径的父目录名提取 `course` 字段 |
| 全链路透传 | loader → indexer → vector DB → retriever → format_context |
| Context 标签渲染 | `[定义, 中文, 进阶]` 等中文标签展示给 LLM |

### Phase 2a 已交付能力（待启用）

| 能力 | 说明 |
|------|------|
| 关键词召回路径 | `retrieve_keyword()` — jieba 分词 + ILIKE 匹配 |
| 混合检索入口 | `retrieve_hybrid()` — 并行多路召回 + RRF 融合 |
| RRF 融合算法 | `_rrf_fusion_cross_path()` — 可配置权重和 k 值 |
| jieba 重排序 | `_rerank_by_keyword_overlap()` — 最高 +0.25 加权 |
| 配置开关 | `config.rag.hybrid.enabled` — 一键启用/关闭 |

启用方式：将 `configs/config.yaml` 中 `rag.hybrid.enabled` 设为 `true`，并在调用方将 `retrieve()` 替换为 `retrieve_hybrid()`。

---

## 6. 与 pgvector 的兼容性总结

全部在 pgvector 内实现，无需引入新的数据库组件：

| 增强 | 依赖的 PG 能力 | 是否需要新扩展 | 状态 |
|------|---------------|:---:|:----:|
| 元数据字段 | JSONB 列 + GIN 索引 | 否 | ✅ 已完成 |
| 混合检索（关键词路径） | ILIKE 子串匹配 | 否 | ✅ 已实现，未启用 |
| 混合检索（RRF 融合） | 纯 Python 层 | 否 | ✅ 已实现，未启用 |
| 中文分词 | jieba (Python) → ILIKE | 否 | ✅ 已实现 |
| 增量索引 | content_hash + diff | 否 | ❌ 已回退 |
| 向量检索 | pgvector HNSW (M=16, ef_construction=200) | vector 扩展 | ✅ 已完成 |
| 父子切割 | parent_chunk_id + is_parent | 否 | ✅ 已实现 |

这正是 pgvector 选型的核心优势——当 RAG 系统需要进化时，PostgreSQL 生态提供了 SQL 标准的能力，所有增强都在同一个数据库中完成，不需要引入新服务。
