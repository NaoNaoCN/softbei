# retriever

# retriever.py 调用关系详解

> 文件路径：`backend/rag/retriever.py`
职责：在线检索阶段，将用户查询嵌入后在 ChromaDB 中做语义搜索，返回相关文本块，并格式化为 LLM prompt 上下文字符串。
> 

---

## 一、`retrieve()` — 通用语义检索

### 函数签名

```python
async def retrieve(
    query: str,
    n_results: int = 5,
    score_threshold: float = 0.5,   # 余弦相似度阈值，低于此值过滤
    where: Optional[dict] = None,   # ChromaDB 元数据过滤，如 {"doc_id": "chapter_01"}
    collection_name: Optional[str] = None,
) -> list[RetrievedChunk]           # 按相似度降序排列
```

### 调用方：`retrieve_by_kp()`

**文件**：`backend/rag/retriever.py:71`

| 项目 | 内容 |
| --- | --- |
| **输入 query** | 由 `retrieve_by_kp()` 传入，格式为 `"知识点：{kp_name}"` |
| **内部操作** | `get_embedding(query)` 获取查询向量 → `query_documents(query_embedding, n_results, where)` 在 ChromaDB 做余弦相似度搜索 → `_parse_results()` 将距离转换为相似度（`score = 1 - distance`）并过滤低分结果 |
| **输出** | `list[RetrievedChunk]`，每项含 `text/score/doc_id/source/page/section`，按 score 降序 |
| **输出用途** | 传入 `format_context()` 格式化为 prompt 上下文字符串 |

**数据流**：

```
retrieve(query="知识点：反向传播算法", n_results=8)
  → get_embedding("知识点：反向传播算法") → list[float]（查询向量）
    → query_documents(query_embedding, n_results=8)
        → ChromaDB 余弦相似度搜索 → 返回 top-8 候选（含距离值）
          → _parse_results(raw, score_threshold=0.5)
              → score = 1 - distance（距离转相似度）
              → 过滤 score < 0.5 的结果
              → 按 score 降序排列
                → list[RetrievedChunk]
```

---

## 二、`retrieve_by_kp()` — 按知识点检索

### 函数签名

```python
async def retrieve_by_kp(
    kp_name: str,
    n_results: int = 8,
    collection_name: Optional[str] = None,
) -> list[RetrievedChunk]
```

### 调用方：各生成 Agent（doc / mindmap / quiz / code / summary）

**文件**：`backend/agents/doc_agent.py:39`、`backend/agents/summary_agent.py:38` 等

| 项目 | 内容 |
| --- | --- |
| **输入 kp_name** | 知识点名称字符串，由 Agent 从 `state.kp_id` 查询知识图谱后获取，如 `"反向传播算法"` |
| **query 构造** | 在名称前加 `"知识点："` 前缀（`f"知识点：{kp_name}"`），使嵌入向量更贴近教学文档的表述风格，提升检索精度 |
| **输出** | `list[RetrievedChunk]`，最多 8 条，score ≥ 0.5，按相似度降序 |
| **输出用途** | 传入 `format_context()` 生成 context 字符串，注入 Agent 的 SYSTEM_PROMPT；同时原始文本列表存入 `state.retrieved_docs` 供 `safety_agent` 使用 |

**数据流**：

```
state.kp_id = "kp_05"
  → （查询知识图谱）kp_name = "反向传播算法"
    → retrieve_by_kp("反向传播算法", n_results=8)
        → retrieve(query="知识点：反向传播算法")
            → list[RetrievedChunk]（最多8条，score≥0.5）
              ├─→ format_context(chunks) → context 字符串
              │     → 注入 SYSTEM_PROMPT {context} 占位符
              └─→ state.retrieved_docs = [c.text for c in chunks]
                    → safety_agent 幻觉检测的事实依据
```

---

## 三、`format_context()` — 格式化为 Prompt 上下文

### 函数签名

```python
def format_context(
    chunks: list[RetrievedChunk],
    max_tokens: int = 3000,   # 粗略字符上限（按 max_tokens×2 字符估算）
) -> str
```

### 调用方：各生成 Agent

**文件**：`backend/agents/doc_agent.py:40`、`backend/agents/summary_agent.py:39` 等

| 项目 | 内容 |
| --- | --- |
| **输入 chunks** | `retrieve_by_kp()` 返回的检索结果列表 |
| **格式化规则** | 每块加编号 `[n]`、来源信息（文件名 + 页码 + 章节），累计字符超过 `max_tokens×2` 时截断，不引入后续块 |
| **输出示例** | `"[1] （来源：chapter_01.pdf，第 2 页）\n梯度下降是...\n\n[2] （来源：notes.md，第一章）\n反向传播..."` |
| **输出用途** | 填入各 Agent SYSTEM_PROMPT 的 `{context}` 占位符，让 LLM 基于真实文档生成内容；编号 `[n]` 同时作为 doc_agent 生成文档时的引用标注依据 |

**数据流**：

```
list[RetrievedChunk]（来自 retrieve_by_kp）
  → format_context(chunks, max_tokens=3000)
      → 逐块拼接：
          "[1] （来源：chapter_01.pdf，第2页）\n{chunk.text}"
          "[2] （来源：notes.md，第一章）\n{chunk.text}"
          ...（超过6000字符时截断）
        → context 字符串
          → SYSTEM_PROMPT.format(context=context, kp_name=...)
            → chat_completion([system_prompt, user_msg])
              → draft_content（文档/思维导图/题目/代码/总结）
```

---

## 四、内部辅助：`_parse_results()`

```python
def _parse_results(raw: dict, score_threshold: float) -> list[RetrievedChunk]:
```

| 项目 | 内容 |
| --- | --- |
| **输入 raw** | ChromaDB `query_documents()` 的原始返回值，含 `ids/documents/distances/metadatas` 四个列表 |
| **转换逻辑** | `score = 1.0 - float(distance)`（ChromaDB 余弦距离 → 相似度），过滤 `score < score_threshold` 的结果 |
| **输出** | `list[RetrievedChunk]`，按 score 降序排列 |

---

## **五、向量库健康检查与降级**

### **检查时机**

在执行检索前，先检查向量库状态：

| 场景 | 行为 |
| --- | --- |
| 向量库为空（0 条文档） | `logger.warning` 提示运行 `python -m backend.rag.indexer` 导入文档，返回 `[]` |
| 向量库未初始化或查询异常 | `logger.warning` 提示检查配置，返回 `[]` |
| Embedding 返回空向量 | `logger.warning` 提示检查 embedding 模型/API 配置，返回 `[]` |

### **降级效果**

检索失败时返回空列表，上游 Agent 继续以"无参考资料"模式调用 LLM 纯生成（degrade gracefully）。

---

## **六、用户隔离过滤**

### **过滤策略**

```python
user_filter = {"$or": [    {"user_id": user_id},      
# 用户自己上传的文档    {"user_id": ""},           # 公共文档（无 user_id）]}
```

### **合并逻辑**

- 若原 `where` 非空：合并为 `{$and: [original_where, user_filter]}`
- 若原 `where` 为空：直接使用 `user_filter`
- 旧数据（无 `user_id` 字段）：回退到无过滤检索并记录警告

### **效果**

- 用户只能检索到自己上传的文档 + 公共文档
- 跨用户数据隔离，保护隐私

---

## 七、整体数据流

```
state.kp_id = "kp_05"
  → retrieve_by_kp("反向传播算法", n_results=8, user_id=current_user)
    → retrieve(query="知识点：反向传播算法", user_id=current_user)
      ① 向量库健康检查
        → get_collection() → col.count()
        → 若 doc_count == 0 → logger.warning → RAG 降级为纯 LLM 生成，返回 []
        → 若查询异常 → logger.warning → RAG 降级，返回 []
      ② query 向量化
        → get_embedding("知识点：反向传播算法") → list[float]（查询向量）
        → 若 embedding 为空 → logger.warning → 返回 []
      ③ 用户隔离过滤
        → 构建 user_filter：{$or: [{user_id: current_user}, {user_id: ""}]}
        → 合并 where 条件：{$and: [original_where, user_filter]}
        → 旧数据无 user_id 字段时回退到无过滤检索并记录警告
      ④ ChromaDB 语义搜索
        → query_documents(query_embedding, n_results=8, where=user_filter)
        → ChromaDB 余弦相似度搜索，返回 top-8 候选结果（含 distance）
      ⑤ 结果解析与过滤
        → _parse_results(raw, score_threshold=0.5)
          → score = 1.0 - float(distance)
          → 过滤 score < 0.5 的结果
          → 按 score 降序排列
          → 返回 list[RetrievedChunk]
    → 若检索无结果 → logger.info → LLM 纯生成
    → 若检索有结果 → logger.info → 返回检索到的 chunks
  → format_context(chunks, max_tokens=3000)
    → 遍历 chunks，拼接 "[n] （来源：source, 第N页, 章节）\n文本"
    → 累加字符数，超出 max_tokens×2 时截断（不再拼接下一条）
    → 返回 context 字符串
  → SYSTEM_PROMPT.format(context=context, kp_name=kp_name)
    → 注入 {context} 占位符
  → chat_completion(...)
    → LLM 结合参考资料生成内容
  → draft_content（学习文档 / 思维导图 / 测验题目 / 编程练习 / 知识点总结）
  → state.retrieved_docs = [c.text for c in chunks]
    → safety_agent：用检索到的文档与 draft_content 对比，检测幻觉
```