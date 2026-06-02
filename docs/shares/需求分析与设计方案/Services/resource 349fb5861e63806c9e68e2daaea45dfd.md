# resource

# resource.py 调用关系详解

> 文件路径：`backend/services/resource.py`
本文档说明其中八个公开函数的**输入来源、输出去向、以及每个调用方的具体使用方式**。
> 

---

## 涉及的数据库表

| 表名 | ORM 类 | 说明 |
| --- | --- | --- |
| `resource_meta` | `ResourceMeta` | 每条生成资源的元数据，含 `content`（文本）和 `content_json`（结构化内容） |
| `generation_task` | `GenerationTask` | 与 `resource_meta` 1:1，跟踪异步生成任务的状态和进度（0-100） |
| `learning_record` | `LearningRecord` | 用户对资源的学习行为记录（时长、评分、反馈） |

---

## 一、`get_resource()` — 查询单个资源详情

### 函数签名

```python
async def get_resource(
    resource_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[ResourceMetaOut]
```

### 调用方：`GET /resources/{resource_id}` 路由

**文件**：`backend/main.py:250`

| 项目 | 内容 |
| --- | --- |
| **输入 resource_id** | 来自 URL 路径参数，由前端从任务完成后的 `result_id` 字段获取 |
| **输出** | `ResourceMetaOut`（含 content/content_json/resource_type 等），若不存在则路由抛出 404 |
| **输出用途** | 返回给前端；生成页 `2_generate.py` 在轮询到 `status=done` 后调用此接口获取内容，再根据 `resource_type` 分发给对应渲染组件 |

---

## 二、`list_resources()` — 分页列举用户资源

### 函数签名

```python
async def list_resources(
    user_id: uuid.UUID,
    db: AsyncSession,
    resource_type: Optional[str] = None,   # 按类型过滤
    kp_id: Optional[str] = None,           # 按知识点过滤
    skip: int = 0,
    limit: int = 20,
) -> list[ResourceMetaOut]
```

### 调用方：`GET /resources` 路由

**文件**：`backend/main.py:237`

| 项目 | 内容 |
| --- | --- |
| **输入 user_id** | HTTP query 参数，从 `st.session_state["user_id"]` 提取 |
| **输入 resource_type** | 资源库页面下拉框：`"all"`, `"doc"`, `"mindmap"`, `"quiz"`, `"code"`, `"summary"` |
| **输入 kp_id** | 可选，按知识点过滤 |
| **输入 skip/limit** | 分页控制，默认 skip=0, limit=20 |
| **内部操作** | `SELECT COUNT(*) FROM resource_meta WHERE user_id = ?` + `SELECT * FROM resource_meta WHERE user_id = ? ORDER BY created_at DESC` |
| **输出** | `ResourceListOut(items=[...], total=N)`，按创建时间倒序 |
| **输出用途** | 资源库页面渲染每张资源卡片；若 total ≤ 20 则隐藏「下一页」按钮 |

**数据流**：

```
Streamlit 资源库页筛选区（type_filter, lib_skip）
  → GET /resources?user_id=...&resource_type=doc&skip=0&limit=20
    → list_resources(user_id, db, resource_type="doc", skip=0, limit=20)
      → SELECT * FROM resource_meta WHERE user_id=? AND resource_type=?
          ORDER BY created_at DESC LIMIT 20 OFFSET 0
        → list[ResourceMetaOut]
          → 2列网格 render_resource_card()
```

---

## 三、`delete_resource()` — 删除资源

### 函数签名

```python
async def delete_resource(
    resource_id: uuid.UUID,
    db: AsyncSession,
) -> bool
```

### 调用方：`DELETE /resources/{resource_id}` 路由

**文件**：`backend/main.py:259`、`streamlit_app/pages/4_library.py:42`

| 项目 | 内容 |
| --- | --- |
| **输入 resource_id** | 来自 URL 路径参数，Streamlit 资源库页每张卡片的”🗑️ 删除”按钮触发，传入 `res["id"]` |
| **内部操作** | DELETE `resource_meta` 表，级联删除关联的 `quiz_item`、`learning_record`（由 ORM 外键级联处理） |
| **输出** | `bool`，成功返回 True |
| **输出用途** | 路由返回 `{"deleted": True}`；Streamlit 收到 200 后显示”已删除”提示并调用 `st.rerun()` 刷新列表 |

---

## 四、`create_generation_task()` — 创建生成任务

### 函数签名

```python
async def create_generation_task(
    user_id: uuid.UUID,
    request: GenerateRequest,   # 含 kp_id, resource_type, extra_params
    db: AsyncSession,
) -> GenerateTaskOut
```

### 调用方：`POST /generate` 路由

**文件**：`backend/main.py:204`

| 项目 | 内容 |
| --- | --- |
| **输入 user_id** | 来自 HTTP 查询参数 |
| **输入 request** | 请求体 `GenerateRequest`，由 Streamlit 生成页的”🚀 开始生成”按钮提交，包含 `kp_id`（知识点 ID）和 `resource_type`（资源类型） |
| **输入来源** | `2_generate.py:35`：用户在下拉框选择知识点、单选框选择资源类型后点击按钮 |
| **内部操作** | 先 INSERT `resource_meta`（空内容占位），再 INSERT `generation_task`（status=‘pending’, progress=0），返回 task_id |
| **输出** | `GenerateTaskOut`（含 task_id/status=‘pending’/progress=0） |
| **输出用途** | 路由返回 task_id 给前端；Streamlit 拿到 task_id 后进入轮询循环（`poll_task_status`） |

**数据流**：

```
Streamlit 生成页：用户选择 kp_id="kp_05", resource_type="quiz"
  → POST /generate?user_id=... body: {"kp_id":"kp_05","resource_type":"quiz"}
    → create_generation_task(user_id, GenerateRequest(...), db)
      → INSERT resource_meta (user_id, kp_id, resource_type, content=null)
      → INSERT generation_task (resource_id, status='pending', progress=0)
        → GenerateTaskOut {task_id: "xxx", status: "pending", progress: 0}
          → 前端开始轮询 GET /generate/xxx/status
```

---

## 五、`get_task_status()` — 轮询任务进度

### 函数签名

```python
async def get_task_status(
    task_id: uuid.UUID,
    db: AsyncSession,
) -> Optional[GenerateTaskOut]
```

### 调用方：`GET /generate/{task_id}/status` 路由

**文件**：`backend/main.py:220`

| 项目 | 内容 |
| --- | --- |
| **输入 task_id** | 来自 URL 路径参数，由前端从 `create_generation_task` 返回值中获取 |
| **输出** | `GenerateTaskOut`（含 status/progress/result_id/error_msg），若不存在则路由抛出 404 |
| **输出用途** | Streamlit 生成页每秒轮询一次（`time.sleep(1)`），用 `progress` 更新进度条；`status=done` 时取 `result_id` 调用 `get_resource()` 获取内容；`status=failed` 时显示错误信息 |

**数据流**：

```
Streamlit 轮询循环（每秒一次）
  → GET /generate/{task_id}/status
    → get_task_status(task_id, db)
      → SELECT * FROM generation_task WHERE id=?
        → GenerateTaskOut {status:"running", progress:60}
          → progress_bar.progress(0.6)
          → 继续循环...
        → GenerateTaskOut {status:"done", progress:100, result_id:"yyy"}
          → 退出循环 → fetch_resource("yyy") → 渲染内容
```

---

## 六、`update_task_progress()` — 更新任务进度

### 函数签名

```python
async def update_task_progress(
    task_id: uuid.UUID,
    progress: int,           # 0-100
    status: TaskStatus,      # pending/running/done/failed
    db: AsyncSession,
    error_msg: Optional[str] = None,
    result_id: Optional[uuid.UUID] = None,
) -> None
```

### 调用方：Agent 执行过程（待实现）

**文件**：目前无实际调用方，由后续 Agent 执行框架调用

| 项目 | 内容 |
| --- | --- |
| **输入 task_id** | 由 `create_generation_task` 创建后传入 Agent 执行上下文 |
| **输入 progress** | Agent 各阶段完成时上报的进度值，例如：RAG 检索完成=30，LLM 生成完成=80，safety 检测完成=100 |
| **输入 status** | 阶段性状态，最终完成时传 `TaskStatus.done` 并附带 `result_id` |
| **内部操作** | `UPDATE generation_task SET progress=?, status=?, error_message=?, updated_at=NOW() WHERE id=?`；若 `result_id` 非空，同时更新 `resource_meta.content` |
| **输出** | None（副作用操作） |
| **输出用途** | 被 `get_task_status` 轮询读取，驱动前端进度条更新 |

---

## 七、`record_learning()` — 记录学习行为

### 函数签名

```python
async def record_learning(
    user_id: uuid.UUID,
    data: LearningRecordCreate,   # 含 resource_id, duration_seconds, rating, feedback
    db: AsyncSession,
) -> LearningRecordOut
```

### 调用方：`POST /records` 路由

**文件**：`backend/main.py:302`

| 项目 | 内容 |
| --- | --- |
| **输入 user_id** | 来自 HTTP 查询参数 |
| **输入 data** | 请求体 `LearningRecordCreate`，由前端在用户完成阅读/测验后提交，包含 `resource_id`（资源 ID）、`duration_seconds`（阅读时长）、`rating`（1-5 星评分）、`feedback`（文字反馈） |
| **内部操作** | INSERT `learning_record` 表 |
| **输出** | `LearningRecordOut`（含 id/user_id/created_at） |
| **输出用途** | 前端确认记录成功；后续 `recommend_agent` 可查询此表分析用户学习偏好，调整推荐策略 |

---

## 八、`list_learning_records()` — 列举学习历史

### 函数签名

```python
async def list_learning_records(
    user_id: uuid.UUID,
    db: AsyncSession,
    skip: int = 0,
    limit: int = 20,
) -> list[LearningRecordOut]
```

### 调用方：暂无路由（待实现）

目前 `main.py` 中未暴露此接口，预留给学习评估页（`5_evaluate.py`）的”历史成绩”面板使用，展示用户的学习时长、评分趋势和薄弱知识点分布。

## **九、`create_batch()` — 创建批量生成批次**

### **函数签名**

```python
async def create_batch(    
		user_id: uuid.UUID,    
		request: BatchGenerateRequest,    
		db: AsyncSession,) 
-> BatchGenerateOut
```

### **调用方：**`POST /generate/batch`

**文件**：`backend/services/resource.py:232`

| 项目 | 内容 |
| --- | --- |
| **输入 user_id** | 用户 UUID |
| **输入 request** | `BatchGenerateRequest(kp_id, resource_types, num_questions, question_type_counts)` |
| **内部操作** | 1. 解析知识点名称 → 2. `INSERT generation_batch` → 3. 为每个 `resource_type` 创建 `resource_meta + generation_task` |
| **输出** | `BatchGenerateOut(batch_id, status=pending, progress=0, tasks=[...])` |
| **输出用途** | 一次性创建多个资源的生成任务，返回批次 ID 和各子任务状态 |

## **十、`get_batch_status()` — 查询批次状态**

### **函数签名**

```python
async def get_batch_status(    
		batch_id: uuid.UUID,    
		db: AsyncSession,
) -> Optional[BatchGenerateOut]
```

### **调用方：**`GET /generate/batch/{batch_id}/status`

**文件**：`backend/services/resource.py:308`

| 项目 | 内容 |
| --- | --- |
| **输入 batch_id** | 批次 UUID |
| **内部操作** | 1. 查询 `generation_batch` → 2. 查询所有子 `generation_task` → 3. 计算聚合状态（avg_progress、all_done、any_failed） → 4. 更新 batch 记录 |
| **输出** | `BatchGenerateOut(batch_id, status, progress, tasks=[...])` |
| **输出用途** | 前端轮询批次状态；展示各子任务进度；任一完成即可渲染对应资源 |

---

## 十一、整体数据流总览

```
用户发起生成（kp_id, resource_type）
  → POST /generate
    → create_generation_task()
      → INSERT resource_meta + INSERT generation_task（pending）
      → 返回 task_id
  → 前端每秒轮询 GET /generate/{task_id}/status
    → get_task_status(task_id)
      → SELECT generation_task
      → 返回 {status, progress, result_id}
    → 若 status=running → progress_bar.progress(N)
    → 若 status=done → 退出轮询 → GET /resources/{result_id}
      → get_resource(result_id)
        → SELECT resource_meta
        → 返回 ResourceMetaOut（content/content_json）
      → 按 resource_type 渲染（mindmap → render_mindmap，quiz → render_quiz_card...）
    → 若 status=failed → 显示错误信息

用户完成学习
  → POST /records
    → record_learning(user_id, data)
      → INSERT learning_record
      → 返回 LearningRecordOut

用户进入资源库
  → GET /resources?resource_type=quiz&skip=0
    → list_resources(user_id, resource_type, skip, limit)
      → SELECT resource_meta WHERE user_id = ?
      → 返回 ResourceListOut
  → 渲染资源卡片网格
  → 点击删除 → DELETE /resources/{id}
    → delete_resource(resource_id)
      → DELETE resource_meta（级联删除 quiz_item）
    → 显示已删除 → st.rerun() 刷新列表
```