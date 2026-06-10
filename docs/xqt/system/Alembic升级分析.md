# `alembic upgrade head` 生效原理

## 一、命令执行的完整链路

```
alembic upgrade head
  ├── alembic.ini  →  定位迁移脚本目录
  ├── migrations/env.py  →  连接数据库 + 调度迁移
  ├── migrations/versions/*.py  →  逐个执行 upgrade()
  └── PostgreSQL alembic_version 表  →  记录当前版本
```

整个链路可拆解为 **配置层 → 发现层 → 执行层 → 记录层** 四个阶段。

---

## 二、配置层：alembic.ini

`alembic.ini` 是 Alembic 的入口配置文件，核心是两行：

```ini
[alembic]
script_location = %(here)s/migrations    # 迁移脚本所在目录
prepend_sys_path = .                     # 把项目根目录加入 sys.path
```

`prepend_sys_path = .` 让 `migrations/env.py` 能通过 `from backend.config import config` 读取项目自己的配置（包括 `DATABASE_URL` 和所有 ORM 模型）。

本项目的 `alembic.ini` **没有**硬编码数据库连接串（L89 已注释掉）：
```ini
# sqlalchemy.url = driver://user:pass@localhost/dbname
```
URL 改由 `migrations/env.py` 从应用配置动态读取。

---

## 三、发现层：env.py 如何知道迁移链

### 3.1 URL 来源

`migrations/env.py` 不读 `alembic.ini` 里的 `sqlalchemy.url`，而是调用项目自身的配置：

```python
from backend.config import config as app_config

def get_url() -> str:
    return app_config.database.url   # ← 来自 configs/config.yaml 中的 ${DATABASE_URL}
```

### 3.2 迁移脚本发现

Alembic 扫描 `migrations/versions/` 目录下所有 `.py` 文件，提取每个文件中的元数据变量：

```python
revision: str = '6f9a2b3c4d5e'           # 当前迁移的唯一 ID
down_revision: str = '5d8e1f2a3b4c'       # 前一个迁移的 ID
```

通过 `down_revision` 字段，Alembic 在内存中构造成一条**单向链表**：

```
a6844ed9ad28 (initial)
  ↓ down_revision
9069c06f0251 (add_document_chunk)
  ↓
db2c961ff39d (uuid_to_snowflake)
  ↓
8a3f2e1b4c5d (embedding → pgvector)
  ↓
107bc3a0d271 (user_id index)
  ↓
5d8e1f2a3b4c (metadata JSONB)
  ↓
6f9a2b3c4d5e (IVFFlat → HNSW)   ← head（链尾，无其他迁移指向它）
```

`head` 就是链的末端 — 没有任何迁移的 `down_revision` 指向它。

---

## 四、执行层：`alembic upgrade head` 实际操作

### 4.1 判断哪些迁移需要执行

Alembic 查询 PostgreSQL 中的 `alembic_version` 表：

```sql
SELECT version_num FROM alembic_version;
```

这个表只有一行一列，记录数据库当前的迁移版本号（例如 `5d8e1f2a3b4c`）。

然后 Alembic 从"当前版本"的下一个节点开始，沿链表走到 `head`：

```
当前 DB 版本: 5d8e1f2a3b4c
需要执行:     5d8e1f2a3b4c → 6f9a2b3c4d5e  （1 个迁移）
```

如果是全新数据库（`alembic_version` 表不存在或为空），则从第一个节点（`a6844ed9ad28`）一直执行到 `head`。

### 4.2 连接数据库

```python
async def run_migrations_online() -> None:
    connectable = create_async_engine(
        get_url(),                    # postgresql+asyncpg://user:pass@host:5432/softbei
        poolclass=pool.NullPool,      # 不使用连接池 — 迁移只需要一个连接
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()
```

关键设计：使用 `NullPool` 而非连接池（`pool_size=10` 的生产配置）。这是因为迁移只需要一个长连接，不需要池化管理。`NullPool` 每次创建全新连接，用完即释放。

### 4.3 事务包裹

```python
def do_run_migrations(connection):
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():     # 整个迁移链在一个事务内
        context.run_migrations()
```

整个迁移链被包裹在**一个数据库事务**中。任一迁移失败，整个事务回滚，数据库回到执行前的状态。

### 4.4 执行 upgrade() 函数

对每个需要执行的迁移文件，Alembic 调用其 `upgrade()` 函数。以 `6f9a2b3c4d5e_switch_ivfflat_to_hnsw.py` 为例：

```python
def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_document_chunk_embedding_ivfflat")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_document_chunk_embedding_hnsw
        ON document_chunk
        USING hnsw (embedding vector_cosine_ops)
        WITH (m = 16, ef_construction = 200)
    """)
```

`op.execute()` 将原始 SQL 直接发送到 PostgreSQL 执行。两行 SQL 在同一事务中：DROP + CREATE 是原子的。

### 4.5 更新版本记录

每成功执行一个迁移，Alembic 立即更新 `alembic_version` 表：

```sql
UPDATE alembic_version SET version_num = '6f9a2b3c4d5e';
```

如果是从旧版本升级多个迁移，版本号逐步递增：
```
5d8e1f2a3b4c → 6f9a2b3c4d5e
```

---

## 五、本次迁移在 PostgreSQL 内部的变化

### 5.1 迁移前

```sql
-- 查看 document_chunk 的索引
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'document_chunk';
```

结果包含：
```
ix_document_chunk_embedding_ivfflat | CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)
```

### 5.2 迁移执行

```sql
BEGIN;                                                           -- context.begin_transaction()
DROP INDEX IF EXISTS ix_document_chunk_embedding_ivfflat;        -- op.execute(1)
CREATE INDEX IF NOT EXISTS ix_document_chunk_embedding_hnsw     -- op.execute(2)
    ON document_chunk
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 200);
UPDATE alembic_version SET version_num = '6f9a2b3c4d5e';        -- 记录版本
COMMIT;                                                          -- 提交事务
```

### 5.3 迁移后

```sql
SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'document_chunk';
```

结果变为：
```
ix_document_chunk_embedding_hnsw | CREATE INDEX ... USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 200)
```

### 5.4 HNSW 索引的内部结构

与 IVFFlat 的 K-means 聚类不同，HNSW 在索引创建时：

1. **遍历全表**，对每个 `NOT NULL` 的 `embedding` 向量执行插入
2. **构建多层图**：顶层稀疏（长距离跳转）、底层稠密（精细搜索）
3. `M=16`：每个节点最多 16 个邻居
4. `ef_construction=200`：构建时搜索宽度 200，控制索引质量
5. 构建完成后，后续任何 `INSERT` 的新向量**自动加入图结构**，无需 `REINDEX`

---

## 六、Alembic 的两个核心表

### 6.1 `alembic_version` — 版本追踪

```sql
CREATE TABLE alembic_version (
    version_num VARCHAR(32) PRIMARY KEY
);
```

只有一行：当前生效的迁移版本号。Alembic 每次启动时读取它来判断数据库状态。

### 6.2 `pg_indexes` — PostgreSQL 系统表（Alembic 不管理）

迁移中创建的索引可通过 PostgreSQL 系统目录查询：

```sql
-- 查看索引大小
SELECT pg_size_pretty(pg_relation_size('ix_document_chunk_embedding_hnsw'));

-- 查看索引使用情况（需在查询执行后）
SELECT idx_scan, idx_tup_read, idx_tup_fetch
FROM pg_stat_user_indexes
WHERE indexrelname = 'ix_document_chunk_embedding_hnsw';
```

---

## 七、常见子命令

| 命令 | 作用 |
|------|------|
| `alembic current` | 显示数据库当前版本 |
| `alembic history` | 显示完整迁移链 |
| `alembic upgrade head` | 执行所有未应用的迁移 |
| `alembic upgrade +1` | 只执行下一个迁移 |
| `alembic downgrade -1` | 回退一个迁移（调用 `downgrade()`） |
| `alembic revision --autogenerate -m "msg"` | 对比 ORM 模型与数据库，自动生成迁移 |
| `alembic stamp head` | 不执行迁移，仅将 `alembic_version` 标记为 `head`（用于已有数据库首次接入 Alembic） |

---

## 八、本项目的特殊之处

1. **异步引擎**：env.py 使用 `create_async_engine` + `asyncio.run()`，与项目整体的 asyncpg 异步栈一致
2. **NullPool**：迁移连接不用连接池，避免迁移运行时持有多个数据库连接
3. **大多数迁移用 `op.execute()` 发原始 SQL**：因为 pgvector 的 `USING hnsw`、`ON CONFLICT`、`server_default` 等语法无法用 SQLAlchemy 的 `op.create_index()` 完整表达
4. **URL 完全从应用配置读取**：不依赖 `alembic.ini` 中的 `sqlalchemy.url`，适配多环境部署

---

## 九、执行流程图

```
用户执行: alembic upgrade head
              │
              ▼
     ┌─ alembic.ini ─────────────────────┐
     │ script_location = migrations/      │
     │ prepend_sys_path = .              │
     └───────────────────────────────────┘
              │
              ▼
     ┌─ migrations/env.py ───────────────┐
     │ ① 导入 ORM Base + 所有 models     │
     │ ② 从 backend.config 读 DATABASE_URL│
     │ ③ 创建异步引擎 (NullPool)         │
     └───────────────────────────────────┘
              │
              ▼
     ┌─ 连接 PostgreSQL ─────────────────┐
     │ SELECT version_num                │
     │ FROM alembic_version              │
     │ → 得到当前版本, 如 5d8e1f2a3b4c   │
     └───────────────────────────────────┘
              │
              ▼
     ┌─ 构建迁移链 ─────────────────────┐
     │ 扫描 migrations/versions/*.py     │
     │ 按 down_revision 构建有向链表     │
     │ 找到 head = 6f9a2b3c4d5e         │
     │ 待执行: [6f9a2b3c4d5e]           │
     └───────────────────────────────────┘
              │
              ▼
     ┌─ BEGIN TRANSACTION ──────────────┐
     │                                   │
     │  执行 6f9a2b3c4d5e.upgrade():     │
     │    DROP INDEX ivfflat             │
     │    CREATE INDEX hnsw              │
     │                                   │
     │  UPDATE alembic_version           │
     │  SET version_num = '6f9a2b3c4d5e' │
     │                                   │
     └─ COMMIT ─────────────────────────┘
              │
              ▼
        迁移完成 ✓
```

---

*文档生成日期：2026-05-25*
