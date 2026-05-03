# 数据模型与 Schema 编写规范

本文档面向所有参与本项目的开发者，使用 Claude Code 编写代码时请严格遵守以下规范。
违反规范会导致运行时 `ValidationError`、字段静默丢失等难以排查的 bug。

---

## 核心原则：ORM 是唯一事实来源

**`backend/db/models.py` 中的 ORM 字段名是权威定义。**
Pydantic schema（`backend/models/schemas.py`）的字段名必须与 ORM 完全一致。
禁止在 schema 中自行发明字段别名，禁止用 `model_validator` 做隐式字段映射。

```
ORM 定义什么字段名 → Schema 就用什么字段名 → API 响应就返回什么字段名
```

---

## 1. 时间戳字段

| 场景 | 正确字段名 | 禁止使用 |
|------|-----------|---------|
| 记录创建时间 | `created_at` | `submitted_at`, `recorded_at`, `added_at`, `timestamp` |
| 记录最后更新时间 | `updated_at` | `modified_at`, `changed_at`, `last_updated` |
| 最后使用/访问时间 | `last_used_at` | `last_access`, `accessed_at` |

**ORM 写法：**
```python
created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**Schema 写法（直接对应，无需任何转换）：**
```python
class FooOut(BaseModel):
    created_at: datetime
    model_config = {"from_attributes": True}
```

---

## 2. 主键与外键

| 场景 | 正确字段名 | 禁止使用 |
|------|-----------|---------|
| 本表主键 | `id` | `foo_id`（在本表内）|
| 引用其他表的外键 | `{表名}_id`，如 `user_id` | 缩写或重命名 |
| Schema 中暴露主键 | `id`（与 ORM 一致）| `task_id`, `record_id`, `path_id` |

**反例（禁止）：**
```python
# ORM 字段叫 id，schema 不能改名
class GenerateTaskOut(BaseModel):
    task_id: uuid.UUID  # ❌ 错误：ORM 字段是 id
```

**正例：**
```python
class GenerateTaskOut(BaseModel):
    id: uuid.UUID  # ✅ 与 ORM 一致
```

如果 API 对外必须暴露不同名称（如与第三方系统对接），使用 `serialization_alias` 显式声明：
```python
id: uuid.UUID = Field(serialization_alias="task_id")
```

---

## 3. 错误与状态字段

| 场景 | 正确字段名 | 禁止使用 |
|------|-----------|---------|
| 错误信息文本 | `error_message` | `error_msg`, `error`, `err_msg` |
| 任务状态 | `status` | `task_status`, `state` |
| 进度百分比 | `progress` | `percent`, `pct` |

---

## 4. 资源/实体命名

| 场景 | 正确字段名 | 禁止使用 |
|------|-----------|---------|
| 实体标题/名称 | `title`（与 ORM 一致）| 在 schema 中改为 `name` |
| 节点类型 | `node_type`（与 ORM 一致）| 在 schema 中改为 `type` |
| 内容正文 | `content` | `body`, `text`, `data` |
| 结构化内容 | `content_json` | `json_content`, `structured_data` |

---

## 5. 新增数据模型的检查清单

每次新增或修改 ORM 模型 / Pydantic schema 时，必须完成以下检查：

```
[ ] ORM 模型中所有时间戳字段均使用 created_at / updated_at
[ ] Schema 中每个字段名与 ORM 对应字段名完全一致
[ ] Schema 中没有使用 model_validator 做字段名映射
[ ] 若使用 serialization_alias，已在代码注释中说明原因
[ ] main.py 中手动构造 Schema 实例时，字段名与 ORM 一致（无 .submitted_at 等引用）
[ ] 前端页面中 .get("field_name") 的 key 与 API 实际返回字段名一致
```

---

## 6. 完整示例

### 新增一个 `Assignment`（作业）模型

**第一步：在 `backend/db/models.py` 定义 ORM**
```python
class Assignment(Base):
    __tablename__ = "assignment"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    content: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
```

**第二步：在 `backend/models/schemas.py` 定义 Schema（字段名严格对齐）**
```python
class AssignmentOut(BaseModel):
    id: uuid.UUID          # ✅ 与 ORM 一致
    user_id: uuid.UUID     # ✅
    title: str             # ✅
    content: Optional[str] # ✅
    status: str            # ✅
    error_message: Optional[str]  # ✅ 不是 error_msg
    created_at: datetime   # ✅ 不是 submitted_at
    updated_at: datetime   # ✅

    model_config = {"from_attributes": True}
```

**第三步：在路由中使用（`model_validate` 直接工作，无需任何转换）**
```python
assignment = await select_one(db, Assignment, filters={"id": assignment_id})
return AssignmentOut.model_validate(assignment)  # ✅ 直接成功
```

---

## 7. 常见错误模式（禁止）

```python
# ❌ 禁止：用 model_validator 做字段名映射
class FooOut(BaseModel):
    created_at: datetime

    @model_validator(mode="before")
    @classmethod
    def fix_names(cls, data):
        if hasattr(data, "submitted_at"):
            data.created_at = data.submitted_at  # 这是在掩盖 ORM 命名错误
        return data

# ❌ 禁止：schema 字段名与 ORM 不一致
class TaskOut(BaseModel):
    task_id: uuid.UUID    # ORM 字段是 id
    error_msg: str        # ORM 字段是 error_message
    name: str             # ORM 字段是 title

# ❌ 禁止：手动构造时引用已不存在的旧字段名
return FooOut(
    created_at=obj.submitted_at,  # submitted_at 已被统一为 created_at
)
```

---

## 8. 与 CLAUDE.md 主文件的关系

本文档是 `CLAUDE.md` 中"Naming Conventions"节的详细展开。
两者同时有效，本文档优先级更高（更具体）。
