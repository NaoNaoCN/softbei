# kg_builder

# **kg_builder.py** 调用关系详解

> 文件路径：`backend/services/kg_builder.py`
本文档说明其中八个公开函数的**输入来源、输出去向、以及每个调用方的具体使用方式**。
> 

---

### **一、`build_kg()` — 主入口：构建知识图谱**

### **函数签名**

`async def build_kg(    doc_id: str,    db: AsyncSession,    on_progress=None,    user_id=None,) -> dict[str, Any]`

### **调用方**

| 项目 | 内容 |
| --- | --- |
| **调用方** | `kg_agent.run()` |
| **文件位置** | `backend/services/kg_builder.py:571` |
| **输入 `doc_id`** | 文档 ID（用于从 ChromaDB 获取文本块） |
| **输入 `user_id`** | 用户 UUID（写入节点归属） |
| **输入 `on_progress`** | 异步回调 `(progress: int, stage: str)` |
| **内部操作** | 见数据流 |
| **输出** | `{"nodes_count": int, "edges_count": int, "doc_id": str}` |
| **输出用途** | 返回构建统计，供 kg_agent 写入 `metadata["kg_result"]` |

### **数据流**

`kg_agent.run() → build_kg(doc_id, db, user_id)  ① 从 ChromaDB 获取文本块    → get_documents_by_doc_id(doc_id)    → 返回 list[documents] + list[metadatas]  ② 尝试提取 PDF 目录（TOC）    → 从 ResourceMeta.content 解析文件名    → loader.extract_toc(pdf_path) → list[{"title": ..., "page": ..., "level": ...}]    → _trim_toc_by_level()（超过 100 项则裁剪深层级）  ③ 判断走哪个路径    → 若 toc 存在且 ≥3 项 → TOC 路径    → 否则 → Fallback 路径  ── TOC 路径 ──    ④ _build_toc_skeleton()      → 根据 level 生成 Chapter/KnowledgePoint 节点 + IS_PART_OF 层级边    ⑤ _group_by_toc()      → 按目录页码范围聚合文本块 → list[{"section": ..., "text": ..., "type": ...}]    ⑥ _extract_nodes_with_context()      → 并发 LLM 提取各章节细粒度节点（SubPoint/Concept）      → 合并骨架节点 + 细粒度节点（去重）    ⑦ _attach_details_to_sections()      → 细粒度节点自动挂到所属章节（IS_PART_OF 边）    ⑧ _extract_cross_edges()      → 并发 LLM 推断跨章节关系（REQUIRES / RELATED_TO）  ── Fallback 路径 ──    ④ _group_by_page()      → 按页聚合文本块（每批 ~12000 字符，采样控制在 30 批）    ⑤ _extract_nodes()      → 并发 LLM 提取节点（每批 6000 字符）    ⑥ _extract_edges()      → 并发 LLM 推断关系（IS_PART_OF / REQUIRES / RELATED_TO / CONTAINS）  ⑨ 清除旧数据    → SELECT old_node_ids WHERE course_id = doc_id    → DELETE KGEdge + DELETE KGNode  ⑩ 写入节点    → _make_node_id(name, doc_id) → 生成唯一 ID    → INSERT KGNode（去重：同名只保留第一个）  ⑪ 创建 Course 根节点    → 生成 course_node_id    → INSERT KGNode(type="Course")  ⑫ 自动生成 Chapter → Course 边（IS_PART_OF）  ⑬ 写入 LLM 推断的边（去重）    → INSERT KGEdge  ⑭ commit  → 返回 {"nodes_count": N, "edges_count": M, "doc_id": doc_id}`

---

### **二、`run_kg_build()` — 后台异步 KG 构建**

### **函数签名**

`async def run_kg_build(    task_id,    doc_id: str,    db: AsyncSession,    user_id=None,) -> None`

### **调用方**

| 项目 | 内容 |
| --- | --- |
| **触发时机** | FastAPI BackgroundTasks，KGBuildTask 创建后执行 |
| **文件位置** | `backend/services/kg_builder.py:771` |
| **输入 `task_id`** | KGBuildTask UUID |
| **内部操作** | 1. 创建独立 session → 2. 调用 `build_kg()` → 3. 更新 KGBuildTask 状态 |
| **输出** | 无 |
| **输出用途** | 后台执行 KG 构建，通过 `on_progress` 回调更新任务进度 |

### **整体数据流总览**

`用户点击「构建知识图谱」  → kg_agent.run()    → kg_builder.build_kg(doc_id, db, user_id)      ① 从 ChromaDB 获取文本块        → get_documents_by_doc_id(doc_id)      ② 尝试提取 PDF 目录（TOC）        → loader.extract_toc(pdf_path) → list[{"title", "page", "level"}]        → _trim_toc_by_level()（超过 100 项则裁剪深层级）      ③ 判断走哪个路径        → 若 toc 存在且 ≥3 项 → TOC 路径        → 否则 → Fallback 路径      ── TOC 路径（智能构建）─        ④ _build_toc_skeleton()          → 根据 level 生成 Chapter/KnowledgePoint 节点 + IS_PART_OF 层级边        ⑤ _group_by_toc()          → 按目录页码范围聚合文本块        ⑥ 并发 LLM 提取各章节细粒度节点（SubPoint/Concept）          → Semaphore(10) 限制 10 并发        ⑦ 细粒度节点自动挂到所属章节（IS_PART_OF 边）        ⑧ 并发 LLM 推断跨章节关系（REQUIRES / RELATED_TO）      ── Fallback 路径（原始逻辑）─        ④ _group_by_page()          → 按页聚合文本块（采样控制在 30 批）        ⑤ 并发 LLM 提取节点        ⑥ 并发 LLM 推断关系（IS_PART_OF / REQUIRES / RELATED_TO / CONTAINS）      ⑨ 清除该 doc 关联的旧数据（DELETE KGEdge + KGNode）      ⑩ 写入节点（去重）        → _make_node_id(name, doc_id) → 生成唯一 ID        → INSERT KGNode      ⑪ 创建 Course 根节点        → INSERT KGNode(type="Course")      ⑫ 自动生成 Chapter → Course 边（IS_PART_OF）      ⑬ 写入 LLM 推断的边（去重）        → INSERT KGEdge      ⑭ commit      → 返回 {"nodes_count": N, "edges_count": M}    → state.metadata["kg_result"] = result    → 前端显示构建成功（节点数 + 边数）  → 用户可前往「学习路径」页面查看知识图谱可视化`