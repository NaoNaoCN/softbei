# 2GB 内存环境下运行瓶颈分析

## 概述

项目核心内存消耗者：

| 组件 | 估算占用 | 是否必需常驻 |
|------|----------|-------------|
| BGE-M3 embedding 模型 | 2.0–2.5 GB | 首次 embedding 时加载，常驻 |
| PostgreSQL 服务 | 128–400 MB | 是（可外部部署） |
| Python 运行时 + FastAPI | 80–150 MB | 是 |
| numpy 矩阵（检索时） | 1–50 MB | 临时，检索时分配 |
| 文档解析（PDF） | 50–500 MB | 临时，导入时分配 |
| **峰值总计** | **2.5–3.5+ GB** | — |

**结论：2GB 内存严重不足，BGE-M3 模型加载即 OOM。**

---

## 瓶颈 1：BGE-M3 embedding 模型（致命，~2.2 GB）

### 问题

`backend/services/llm.py:81-89` 加载 `BAAI/bge-m3`：

```python
_embedding_model = SentenceTransformer(config.embedding.model)
```

BGE-M3 基于 XLM-RoBERTa（约 568M 参数），float32 精度下：

| 算项 | 大小 |
|------|------|
| 模型权重（float32） | 568M × 4 = **2.17 GB** |
| 优化器状态 | 0（推理模式） |
| 词表 + tokenizer | ~50 MB |
| 推理中间张量 | ~100–300 MB（取决于输入长度） |
| **加载后总占用** | **~2.3–2.5 GB** |

仅此一项就超出了 2GB 的限制。当前配置 `use_spark: true` 使用 API embedding 可规避，但若 API 失败会自动降级到本地 BGE-M3（见下文），本地模型加载仍会触发 OOM。

### 当前降级链路

```
_api_embedding (API)
  └─ 失败 → _local_embedding (BGE-M3 本地)
       └─ 加载模型 → OOM
```

### 建议

1. **强制 API embedding，禁止降级加载本地模型**：`use_spark: true` + 移除降级逻辑中的模型加载
2. **换用小模型**：如 `all-MiniLM-L6-v2`（~80MB，384维），但语义质量下降明显
3. **外部化**：将 embedding 服务独立部署到有足够内存的机器

---

## 瓶颈 2：PostgreSQL 常驻内存（~128–400 MB）

### 问题

PostgreSQL 默认配置会占用大量内存：

| 参数 | 默认值 | 占用 |
|------|--------|------|
| `shared_buffers` | 128 MB | 128 MB |
| `work_mem` | 4 MB | 4 MB × 并发查询数 |
| `max_connections` | 100 | 每个连接 ~2–3 MB |
| `wal_buffers` | 16 MB | 16 MB |
| `effective_cache_size` | 4 GB | 仅规划用，不分配 |
| **基础常驻** | — | **~150–200 MB** |
| **峰值（含查询排序）** | — | **~300–400 MB** |

当前连接池配置：`pool_size=10, max_overflow=20`，最多 30 个连接，连接开销 ~60–90 MB。

### 建议

```ini
# postgresql.conf 精简配置
shared_buffers = 32MB
work_mem = 1MB
maintenance_work_mem = 16MB
max_connections = 20
wal_buffers = 4MB
```

应用侧连接池：
```yaml
database:
  pool_size: 3        # 从 10 降
  max_overflow: 5     # 从 20 降
```

---

## 瓶颈 3：numpy 矩阵峰值内存（索引/检索时）

### 3.1 索引写入

**位置**：`backend/rag/indexer.py:96-104` `_embed_batch()`

```python
semaphore = asyncio.Semaphore(8)    # 8 个并发 embedding
```

并发 8 个 embedding 调用的内存占用：

| 路径 | 单次占用量 | × 8 并发 |
|------|-----------|---------|
| API embedding（输入文本） | ~1–5 KB | ~40 KB |
| API embedding（响应 JSON） | ~8 KB | ~64 KB |
| **API 模式合计** | — | **~100 KB** |
| 本地 BGE-M3（输入文本） | ~1–5 KB | ~40 KB |
| 本地 BGE-M3（推理中间张量） | ~100–300 MB | **~0.8–2.4 GB** |
| **本地模式合计** | — | **OOM** |

**建议**：Semaphore 从 8 降到 2，batch_size 从 128 降到 32。

### 3.2 检索计算

**位置**：`backend/db/vector.py` `_compute_cosine_similarity()`（优化后）

```python
cand_matrix = np.array([emb for ...], dtype=np.float32)  # (N, 1024) × 4 bytes
```

| 候选数 N | 矩阵内存 |
|----------|---------|
| 500（小库） | 500 × 1024 × 4 = **2 MB** |
| 5,000（中库） | 5,000 × 1024 × 4 = **20 MB** |
| 50,000（大库） | 50,000 × 1024 × 4 = **200 MB** |

当前 `LIMIT 5000`，峰值 ~20 MB —— 可控。

### 3.3 批量 INSERT

**优化后的 `upsert_documents`**：整批 chunk 的 id、text、embedding 全部打包进一个 SQL 参数字典，batch_size=128 时约 128 × (1024 × 4 + 文本) ≈ **1–2 MB** 临时参数内存。

---

## 瓶颈 4：文档解析（PDF 导入时 ~50–500 MB）

**位置**：`backend/rag/loader.py` — 使用 `pymupdf4llm` 将 PDF 转为 Markdown。

`pymupdf4llm` 内部使用 `fitz`（MuPDF），会将整个 PDF 页面渲染为像素图再提取文本：

| PDF 大小 | 解析内存 |
|----------|---------|
| 10 页文本型 | ~50 MB |
| 100 页图文混合 | ~200–500 MB |
| 500 页教材（如 d2l-zh） | **>>> 2GB，无法完成** |

**建议**：
- 限制上传 PDF 大小（如 ≤ 50 页）
- 或使用轻量解析器（如 `pypdf` 纯文本提取，不渲染图片）

---

## 瓶颈 5：Python 运行时 + FastAPI（常驻 ~80–150 MB）

| 算项 | 占用 |
|------|------|
| Python 解释器 | ~30 MB |
| FastAPI + Uvicorn | ~20 MB |
| langchain/langgraph/openai 等库 | ~50–80 MB |
| config/schema 模块 | ~10–20 MB |
| **合计** | **~80–150 MB** |

这属于正常开销，无法大幅缩减。无 worker 多进程（`main.py` 无 `workers` 参数），单进程模式在此环境下反而是正确的。

---

## 内存预算汇总

### 最优配置（API embedding + 精简 PostgreSQL）

| 组件 | 占用 | 累计 |
|------|------|------|
| OS（Windows/Linux 基础） | ~400 MB | 400 MB |
| Python + FastAPI | ~100 MB | 500 MB |
| PostgreSQL（精简配置） | ~100 MB | 600 MB |
| API embedding（无本地模型） | ~5 MB | 605 MB |
| 检索 numpy 矩阵 | ~20 MB | 625 MB |
| 文档解析峰值 | ~200 MB | 825 MB |
| **可用余量** | **~1.2 GB** | **2 GB** |

此配置下 **2GB 可以运行，但余量有限，大 PDF 导入可能触发 swap**。

### 当前配置（API 失败降级本地 BGE-M3）

| 组件 | 占用 | 累计 |
|------|------|------|
| OS | ~400 MB | 400 MB |
| Python + FastAPI | ~100 MB | 500 MB |
| PostgreSQL（默认） | ~200 MB | 700 MB |
| BGE-M3 模型（降级加载） | ~2.3 GB | **3.0 GB** |
| **结论** | **OOM** | |

---

## 具体建议

### 必须改（否则无法启动）

1. **禁止本地 BGE-M3 降级加载**

   当前 `_api_embedding()` 失败时会调用 `_local_embedding()`，后者加载 BGE-M3 → OOM。改为直接返回错误或空向量，不加载本地模型：

   ```python
   # backend/services/llm.py _api_embedding
   except Exception as e:
       logger.warning(f"[Embedding] API 失败: {e}，无本地模型可用，返回空向量")
       return []  # 不调用 _local_embedding()
   ```

2. **精简 PostgreSQL 配置**

   编辑 `postgresql.conf`：
   ```ini
   shared_buffers = 32MB
   work_mem = 1MB
   max_connections = 20
   ```

### 建议改（提升稳定性）

3. **缩减连接池**（`config.yaml`）：`pool_size: 3`, `max_overflow: 5`
4. **减小 indexer 并发**：`Semaphore(2)`，`batch_size: 32`
5. **限制 PDF 上传大小**：前端/后端校验 ≤ 50 页或 ≤ 10MB
6. **加 swap**：至少 2GB swap 文件作为缓冲

### 可选

7. **换小 embedding 模型**：如果用本地模型，`all-MiniLM-L6-v2`（80MB）
8. **PostgreSQL 外置**：数据库部署在另一台机器上
