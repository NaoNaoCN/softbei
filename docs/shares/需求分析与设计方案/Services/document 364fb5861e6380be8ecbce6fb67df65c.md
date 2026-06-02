# document

# [document.py](http://document.py) 调用关系详解

> 文件路径：`backend/services/document.py`
本文档说明其中八个公开函数的**输入来源、输出去向、以及每个调用方的具体使用方式**。
> 

---

## **一、`import_pdf()` — 导入 PDF 文档**

### **函数签名**

```python
async def import_pdf(    
		file_path: str,    
		user_id: uuid.UUID,    
		title: Optional[str] = None,    
		db: Optional[AsyncSession] = None,
) -> dict
```

### **调用方**

| 项目 | 内容 |
| --- | --- |
| **调用方** | Streamlit 上传页面 |
| **文件位置** | `backend/services/document.py:33` |
| **输入 file_path** | 临时保存的 PDF 文件路径 |
| **输入 user_id** | 上传用户 UUID |
| **输入 title** | 自定义文档标题，默认使用文件名 |
| **内部操作** | 1. `loader.load_file()` 解析 PDF → 2. `rag_indexer.index_chunks()` 索引到向量库 → 3. `INSERT resource_meta` 创建资源记录 |
| **输出** | `{"doc_id": str, "title": str, "chunks": int, "indexed": int, "resource_id": str}` |
| **输出用途** | 返回给前端，显示导入结果 |

### **数据流**

`用户上传 PDF 文件  → import_pdf(file_path, user_id, title)    → loader.load_file(file_path, doc_id)      → PyPDFLoader.load() → list[Document]      → docs_to_chunks() → list[TextChunk]    → rag_indexer.index_chunks(chunks, user_id=user_id)      → _embed_batch() → list[list[float]]      → upsert_documents() → ChromaDB    → INSERT resource_meta（可选，有 db 时）    → 返回 {"doc_id": "...", "chunks": N, "indexed": N}  → 前端显示导入成功`

---

### **二、`import_pdf_with_progress()` — 带进度回调的 PDF 导入**

### **函数签名**

`async def import_pdf_with_progress(    file_path: str,    user_id: uuid.UUID,    title: Optional[str] = None,    db: Optional[AsyncSession] = None,    progress_callback: Optional[Callable[[str, int], None]] = None,) -> dict`

### **调用方**

| 项目 | 内容 |
| --- | --- |
| **调用方** | Streamlit 上传页面（带进度条） |
| **文件位置** | `backend/services/document.py:85` |
| **输入 `progress_callback`** | `(stage: str, percent: int)` 回调函数 |
| **进度阶段** | saving(5%) → parsing(20%) → indexing(20%-90%) → saving_record(95%) → done(100%) |
| **内部操作** | 同 `import_pdf()`，但分阶段调用 `progress_callback` |
| **输出** | 同 `import_pdf()` |
| **输出用途** | 前端显示索引进度条 |

### **数据流**

`用户上传 PDF 文件  → import_pdf_with_progress(file_path, user_id, progress_callback)    → progress_callback("saving", 5)    → loader.load_file() → list[TextChunk]    → progress_callback("parsing", 20)    → rag_indexer.index_chunks(chunks, progress_callback=_index_progress, user_id)      → _index_progress(batch_num, total_batches)        → 进度 = 20 + (batch_num/total_batches * 70) → 上限 90    → progress_callback("indexing", 90)    → INSERT resource_meta（可选）    → progress_callback("saving_record", 95)    → progress_callback("done", 100)    → 返回结果  → 前端进度条更新`

---

### **三、`save_uploaded_file()` — 保存上传文件**

### **函数签名**

`def save_uploaded_file(    content: bytes,    original_name: str,) -> str`

### **调用方**

| 项目 | 内容 |
| --- | --- |
| **调用方** | Streamlit 上传页面 |
| **文件位置** | `backend/services/document.py:157` |
| **输入 `content`** | 文件字节内容 |
| **输入 `original_name`** | 原始文件名（仅支持 `.pdf`） |
| **内部操作** | 生成唯一文件名 `uuid.hex[:12]_{original_name}`，写入 `uploaded_docs/` 目录 |
| **输出** | 保存后的文件路径 |
| **输出用途** | 临时保存文件，供 `import_pdf()` 后续解析 |

### 

### **整体数据流总览**

`用户上传 PDF 文件  → save_uploaded_file(content, original_name)    → 验证后缀（仅 .pdf）    → 生成唯一文件名 "uuid_hex[:12]_{original_name}"    → 写入 uploaded_docs/ 目录    → 返回 file_path  → import_pdf_with_progress(file_path, user_id, progress_callback)    → progress_callback("saving", 5)    → loader.load_file(file_path, doc_id)      → PyPDFLoader.load() → list[Document]      → docs_to_chunks() → list[TextChunk]（含 chunk_id/doc_id/source/page/section）    → progress_callback("parsing", 20)    → rag_indexer.index_chunks(chunks, progress_callback=_index_progress, user_id)      → 分批（每批 32 个）      → _embed_batch() → get_embedding() × N（Semaphore 限制 8 并发）      → upsert_documents() → ChromaDB（metadata 含 user_id）    → progress_callback("indexing", 90)    → INSERT resource_meta（可选）    → progress_callback("saving_record", 95)    → progress_callback("done", 100)    → 返回 {"doc_id": ..., "chunks": N, "indexed": N}  → 前端显示导入成功 + 进度条  → 用户可在资源库看到该文档  → 用户可构建知识图谱：build_kg(doc_id, db)`