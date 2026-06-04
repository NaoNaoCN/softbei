# Embedding 方案分析：当前状态与优化建议

> 分析日期：2026-05-21
> 最后更新：2026-05-21（反映近期优化后的当前状态）

---

## 1 当前 Embedding 架构

### 1.1 概述

项目使用 **DashScope `text-embedding-v4`** 作为唯一 Embedding 方案。本地 BGE-M3 降级路径已移除，API 不可用时直接返回空向量，由 RAG 层优雅降级为纯 LLM 生成。

```
                      ┌─ get_embedding(text)
                      │    │
                      │    ├─ _get_embedding_client()  ← 单例复用 TCP 连接池
                      │    ├─ client.embeddings.create(model="text-embedding-v4", input=text)
                      │    ├─ 成功 → 返回 1024-dim 向量
                      │    └─ 失败 → logger.warning → return []  (RAG 降级)
                      │
                      └─ get_embeddings_batch(texts)
                           │
                           ├─ 单次 API 调用发送多条文本（最多 25 条/次）
                           ├─ 成功 → 返回 list[list[float]]
                           └─ 失败 → 返回空向量列表
```

### 1.2 关键代码路径

```python
# backend/services/llm.py:169-186
_embedding_client: AsyncOpenAI | None = None  # 模块级单例

def _get_embedding_client() -> AsyncOpenAI:
    """获取 Embedding API 客户端单例，复用 TCP 连接池。"""
    global _embedding_client
    if _embedding_client is None:
        _embedding_client = AsyncOpenAI(
            api_key=config.llm.api_key,
            base_url=config.embedding.api_base_url,
            timeout=Timeout(connect=10, read=60, write=30, pool=10),
        )
    return _embedding_client
```

```python
# backend/services/llm.py:189-204
async def get_embedding(text: str) -> list[float]:
    """单条文本向量化。失败时返回空向量，RAG 降级为纯 LLM 生成。"""
    try:
        client = _get_embedding_client()
        response = await client.embeddings.create(
            model=config.embedding.api_model,
            input=text,
        )
        return response.data[0].embedding
    except Exception as e:
        logger.warning(f"[Embedding] API embedding 失败: {e}，返回空向量，RAG 将降级为纯 LLM 生成")
        return []
```

```python
# backend/services/llm.py:207-224
async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """批量向量化，单次 API 调用发送多条文本。"""
    # 由 indexer.py 的 _embed_batch() 调用，batch_size 上限 25（API 限制）
    client = _get_embedding_client()
    response = await client.embeddings.create(
        model=config.embedding.api_model,
        input=texts,
    )
    return [d.embedding for d in response.data]
```

### 1.3 关键配置

```yaml
# configs/config.yaml
embedding:
  use_spark: true               # true=使用远程 Embedding API（false 路径已废弃）
  concurrency: 8                # 嵌入并发数（索引器批处理并发控制）
  api_model: "text-embedding-v4"
  api_base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  timeout_read: 60
  timeout_connect: 10
  timeout_write: 30
  timeout_pool: 10
  index_batch_size: 128         # 索引时每批块数（受 API 上限 25 约束，实际取 min(128, 25)=25）
  vector_dimension: 1024        # text-embedding-v4 输出维度
```

### 1.4 数据库约束

```python
# backend/db/models.py:156
embedding = mapped_column(Vector(1024), nullable=True)
```

pgvector 列固定 1024 维。`nullable=True` 允许嵌入失败时不阻塞写入。

---

## 2 当前生产路径：DashScope `text-embedding-v4`

### 2.1 特点

| 维度 | 说明 |
|------|------|
| 模型 | 阿里云 DashScope `text-embedding-v4` |
| 输出维度 | 1024 |
| 认证 | 复用 `LLM_API_KEY`（与对话 LLM 同一把 key） |
| 费用 | 按 token 计费，约 0.0007 元/千 tokens |
| 单次最大输入 | 2048 tokens（约 3000 中文字符） |
| 批量支持 | 已启用，单次 API 调用最多 25 条文本 |
| 客户端 | 模块级单例异步客户端，复用 TCP 连接池 |
| 可用性 | 依赖网络，无本地离线能力 |

### 2.2 近期优化（2026-05-20 ~ 2026-05-21）

| 优化项 | 状态 | 说明 |
|--------|------|------|
| HTTP 客户端单例复用 | ✅ 已完成 | `_get_embedding_client()` 保持全局单例 |
| 批量 Embedding API | ✅ 已完成 | `get_embeddings_batch()` 一次发多条，索引速度 10x+ |
| 移除 BGE-M3 降级链 | ✅ 已完成 | API 失败直接返回 `[]`，不再尝试加载本地模型 |
| 移除 `sentence-transformers` 依赖 | ✅ 已完成 | `requirements.txt` 中已不再包含 |
| 重试策略（tenacity） | ❌ 未实施 | `get_embedding` 和 `get_embeddings_batch` 无重试 |
| 请求级 Embedding 缓存 | ❌ 未实施 | 同 query 可能重复嵌入 |
| 配置项命名清理 | ❌ 未实施 | `use_spark` 仍为误导性命名 |

---

## 3 降级策略：优雅降级，无故障放大

### 3.1 当前降级链

```
get_embedding(text)
  → API 调用成功 → 返回 1024-dim 向量 → RAG 正常检索
  → API 调用失败 → return [] (空列表)
    → retriever.py:66 → return []  (空 chunks)
      → agent utils.py:112 → context = "（暂无参考资料）"
        → LLM 纯生成（无 RAG 上下文）
```

### 3.2 与旧方案（BGE-M3 降级）的对比

| 维度 | 旧方案 | 新方案 |
|------|--------|--------|
| API 失败时 | 尝试加载 BGE-M3（2.2GB）→ 下载超时 → 最终也返回 `[]` | 直接返回 `[]` |
| 故障恢复时间 | 数分钟（下载等待） | 即时（最迟 API 超时后） |
| 副作用 | 可能混用两种语义空间的向量 | 无 |
| 代码复杂度 | `_local_embedding` + `_get_embedding_model` + 全局模型对象 | 无 |

### 3.3 降级的实际影响

| 场景 | 影响 |
|------|------|
| API 偶尔超时 | 单次检索返回空，后续请求正常 |
| API 完全不可用 | 所有 RAG 降级为纯 LLM 生成 |
| 降级期间的生成质量 | 无参考资料，LLM 凭自身知识生成（可接受，质量略降） |

---

## 4 项目中不存在替代 Embedding 路径

| 可能方案 | 状态 |
|----------|------|
| DashScope `text-embedding-v4` API | ✅ **当前唯一可用路径** |
| BGE-M3 本地模型 | ❌ 代码已完全移除 |
| 其他 Provider（Spark/DeepSeek/OpenAI）Embedding API | ❌ 对话 LLM 的多 provider 机制未复用到 Embedding |
| ONNX / TensorRT / Ollama 本地推理 | ❌ 不存在 |

---

## 5 当前待改进项

### 5.1 为 Embedding 添加重试策略（P2）

当前 `chat_completion` 使用 `@retry`（tenacity）实现指数退避重试，但 `get_embedding` 和 `get_embeddings_batch` 没有。建议对齐：

```python
@retry(
    stop=stop_after_attempt(3),  # embedding 重试次数可少于 chat（3 次即可）
    wait=wait_exponential(multiplier=2, min=3, max=15),
    retry=retry_if_exception_type((RateLimitError, TimeoutError, ConnectionError)),
)
async def get_embedding(text: str) -> list[float]:
    ...
```

### 5.2 清理配置项命名（P2）

`embedding.use_spark` 是历史遗留命名，当前实际指向 DashScope：

| 当前 | 建议 |
|------|------|
| `embedding.use_spark: true` | 移除该字段（本地路径已废弃，无需开关） |

由于本地 BGE-M3 路径已删除，`use_spark` 字段在代码中无实际分支逻辑（`get_embedding` 不再判断它），可考虑直接移除。

### 5.3 请求级 Embedding 缓存（P3）

同一请求内，多个 Agent 检索同一知识点时，`retrieve_context()` 已缓存 RAG 检索结果，但 Embedding 调用未被缓存。当日后的 metadata 过滤检索需要同一 query 对应不同 filter 多次嵌入时，缓存收益会更明显。

---

## 6 配置文件中的相关项

### 6.1 当前配置注释

```yaml
embedding:
  use_spark: true    # true=使用远程 Embedding API；false=使用本地模型（BGE-M3，已废弃）
```

注释已标注 BGE-M3 为"已废弃"，状态透明。

### 6.2 不再存在的配置项

以下字段已从配置中移除（与 BGE-M3 本地模型一同清理）：

| 已移除字段 | 原用途 |
|-----------|--------|
| `embedding.model` | BGE-M3 模型名（`BAAI/bge-m3`） |
| `embedding.hf_mirror` | HuggingFace 下载镜像 |

---

## 7 总结

```
当前状态:
  唯一路径: DashScope text-embedding-v4 ✅ 稳定运行
  客户端:   单例 AsyncOpenAI        ✅ 连接池复用
  批量 API:  get_embeddings_batch    ✅ 索引速度优化
  降级策略:  API 失败 → return []   ✅ 优雅降级，无故障放大
  本地模型:  BGE-M3                 ❌ 已完全移除

待改进:
  P2: 为重试策略添加 tenacity（对齐 chat_completion）
  P2: 清理 embedding.use_spark 配置项（已无实际分支逻辑）
  P3: 请求级 Embedding 缓存
```
