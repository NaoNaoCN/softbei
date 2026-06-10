# 项目使用的 PostgreSQL 特性与优势分析

> 分析日期：2026-05-20 | PostgreSQL 17.10 | asyncpg 驱动

---

## 一、项目中使用的 PostgreSQL 特性

### 1.1 pgvector 向量扩展

本项目最核心的 PostgreSQL 特性，用于在数据库内完成语义向量检索，避免引入独立的向量数据库。

**启用方式：**
```sql
CREATE EXTENSION IF NOT EXISTS vector;
```

**关键组件：**

| 组件 | 位置 | 说明 |
|------|------|------|
| `Vector(1024)` 列类型 | `backend/db/models.py:156` | BGE-M3 输出的 1024 维向量 |
| IVFFlat 索引 | `migrations/versions/8a3f2e1b4c5d` | `USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)` |
| `<=>` 余弦距离运算符 | `backend/db/vector.py:257,264` | 向量相似度比较和排序 |
| `ivfflat.probes = 10` | `backend/db/vector.py:270` | `SET LOCAL` 会话级参数，控制检索精度/速度平衡 |
| asyncpg codec 直传 | `backend/db/vector.py:169,244` | list[float] 自动转为向量，无需手动拼接字符串 |

**使用方式（query_documents）：**
```sql
SELECT chunk_id, text, doc_id, embedding <=> :embedding AS distance, ...
FROM document_chunk
WHERE collection_name = :cn
ORDER BY embedding <=> :embedding
LIMIT :n_results
```

---

### 1.2 ON CONFLICT（Upsert）

`backend/db/vector.py:176-186` — 批量插入文档块时使用，插入新记录或更新已有记录：

```sql
INSERT INTO document_chunk (id, chunk_id, doc_id, text, embedding, ...)
VALUES (...), (...)
ON CONFLICT (chunk_id) DO UPDATE SET
    text = EXCLUDED.text,
    embedding = EXCLUDED.embedding,
    source = EXCLUDED.source,
    ...
```

`EXCLUDED` 是 PostgreSQL 特有的伪表名，引用 VALUES 中与冲突行冲突的那个行。

**如果没有这个特性**，需要先 `SELECT` 检查存在性，再分别 `INSERT` 或 `UPDATE`，即应用层代码需多写一次查询并处理竞态条件。

---

### 1.3 ANY() 数组运算符

`backend/db/vector.py:305` — 批量删除向量文档：

```sql
DELETE FROM document_chunk WHERE chunk_id = ANY(:ids)
```

允许传入一个数组参数 `:ids` 匹配多个值，比 `WHERE chunk_id IN (:id1, :id2, ...)` 参数化更简洁，也比应用层循环逐条 DELETE 高效。

---

### 1.4 SET LOCAL 运行时参数

`backend/db/vector.py:270` — 在向量检索前动态设置 IVFFlat 探针数：

```sql
SET LOCAL ivfflat.probes = 10
```

`SET LOCAL` 是 PostgreSQL 特有语法，仅在当前事务/会话中生效，不影响其他连接。这使得检索精度可以在应用层灵活调优，无需重建索引或修改全局配置。

---

### 1.5 原生 ENUM 类型（6 个）

`backend/db/models.py` — 6 个自定义 PostgreSQL ENUM 类型：

| ENUM 名称 | 用途 | 值 |
|-----------|------|-----|
| `cognitivestyle` | 学生认知风格 | visual, verbal, logical, etc. |
| `kgnodetype` | KG 节点类型 | concept, topic, etc. |
| `kgrelation` | KG 边关系 | prerequisite, related_to, etc. |
| `resourcetype` | 资源类型 | doc, quiz, mindmap, code, summary |
| `taskstatus` | 任务状态（3 个模型共用） | pending, running, completed, failed |
| `questiontype` | 题目类型 | single_choice, multi_choice, etc. |

**使用 PostgreSQL ENUM 的好处：**
- 数据库层强制执行，输入值不合法时直接拒写
- 比 CHECK 约束更可读（`\dT+` 可查看所有枚举值）
- 存储为 4 字节整数，比 VARCHAR 更省空间
- 在 SQLAlchemy 中映射为 Python Enum，类型安全

---

### 1.6 JSON 列（7 处）

`backend/db/models.py` — SQLAlchemy `JSON` 类型（映射到 PostgreSQL `JSONB`）：

| 模型 | 列名 | 用途 |
|------|------|------|
| `StudentProfile` | `knowledge_mastered` | 已掌握知识点列表 |
| `StudentProfile` | `knowledge_weak` | 薄弱知识点列表 |
| `StudentProfile` | `error_prone` | 易错知识点列表 |
| `StudentProfile` | `goal_questions` | 摸底题目及答案 |
| `ProfileHistory` | `snapshot` | 画像历史快照 |
| `ResourceMeta` | `content_json` | 富文本/结构化内容 |
| `QuizItem` | `options` | 题目选项数组 |

PostgreSQL 的 JSONB 支持二进制存储（比 JSON 类型更快）、GIN 索引（方便未来按 JSON 内容查询），且保留键序和去重。

---

### 1.7 BIGINT 主键（Snowflake ID）

`backend/db/models.py` — 除 `KGNode`（String(64)）外，所有 12 张表使用 `BigInteger` 主键：

项目将原始 UUID 主键迁移为 **Snowflake 64-bit BIGINT**（`migrations/versions/db2c961ff39d`），自定义实现位于 `backend/utils/snowflake.py`。

**为什么用 PostgreSQL BIGINT 而非 UUID：**
- BIGINT 作为主键索引更紧凑（8 字节 vs 16 字节的 UUID）
- B-Tree 索引上 BIGINT 的插入随机性更低，页面分裂更少
- Snowflake 自带时间排序，适合按时间范围查询
- PostgreSQL 对 BIGINT 的主键/外键处理性能优于 UUID

---

### 1.8 复合索引（6 个）

`backend/db/models.py` — 6 个多列复合索引：

| 表 | 复合索引 | 说明 |
|----|----------|------|
| `chat_message` | `(session_id, created_at)` | 按会话 + 时间查聊天消息 |
| `kg_node` | `(user_id, node_type)` | 按用户 + 类型过滤 KG 节点 |
| `resource_meta` | `(user_id, resource_type)` | 按用户 + 资源类型过滤 |
| `resource_meta` | `(user_id, kp_id)` | 按用户 + 知识点过滤 |
| `quiz_attempt` | `(user_id, submitted_at)` | 按用户 + 时间查答题记录 |
| `learning_record` | `(user_id, kp_id)` | 按用户 + 知识点查学习记录 |

复合索引避免回表查询，让 WHERE 条件直接命中索引覆盖列。

---

### 1.9 外键与 CASCADE

`backend/db/models.py:130` — 聊天消息引用会话：

```python
session_id = mapped_column(ForeignKey("chat_session.id", ondelete="CASCADE"))
```

数据库层自动清理：删除会话 → 级联删除其所有消息。避免了应用层手动删除或产生孤儿记录。

---

### 1.10 asyncpg 连接池

`backend/db/database.py:51-81` — `create_async_engine` 的 PostgreSQL 专有配置：

| 参数 | 值 | 说明 |
|------|-----|------|
| `pool_size` | 10 | 常驻连接数 |
| `max_overflow` | 20 | 峰值可额外创建 20 个（最大 30） |
| `pool_recycle` | 3600 | 1 小时后回收连接，防止空闲断连 |
| `pool_pre_ping` | True | 每次 checkout 前发 `SELECT 1` 验证连接 |
| `command_timeout` | 60 | asyncpg 语句超时（秒） |
| `pool_timeout` | 30 | 等待连接池的最大秒数 |

---

### 1.11 aggregate 函数（COUNT 等）

通过 SQLAlchemy `func.count()` 映射到 PostgreSQL `COUNT()`，在以下场景使用：

- `backend/db/crud.py:209` — CRUD 层的通用 `count()` 函数
- `backend/services/resource.py:72` — 统计资源数量
- `backend/main.py:882` — API 层的统计查询

---

## 二、项目中未使用但可挖掘的 PostgreSQL 特性

| 特性 | 当前替代方案 | 引入价值 |
|------|-------------|----------|
| **pg_trgm** (三元组模糊匹配) | Python 侧关键词重排 | 可在 DB 层做模糊搜索，省去应用层处理 |
| **JSONB GIN 索引** | 无索引，全量 JSON 加载 | StudentProfile 的 JSON 列按内容查询时，GIN 索引可大幅加速 |
| **tsvector 全文搜索** | Python `_rerank_by_keyword_overlap` | DB 层全文检索更快，支持中文分词插件 |
| **LISTEN/NOTIFY** | 无 | 可实现 DB 层事件通知（如 KG 构建完成后自动触发推荐） |
| **递归 CTE** | Python BFS 全量加载边 | KG 子图查询可从 Python BFS 迁移到 DB 递归 CTE，O(N) → 单次查询 |
| **物化视图** | 无 | 学生画像分析等聚合场景可预计算 |
| **行级安全 (RLS)** | 应用层 `user_id` 过滤 | 多租户场景下增强数据隔离 |

---

## 三、为什么 PostgreSQL 适合本项目

### 3.1 统一数据栈：关系 + 向量检索

本项目核心需求是 **结构化数据（用户/资源/KG） + 语义向量检索（RAG）**。传统方案需要两套系统：

| 方案 | 组件 | 代价 |
|------|------|------|
| MySQL + Pinecone/Milvus | 2 个数据库 | 维护两套连接、保证数据一致性、处理跨系统事务 |
| MongoDB + Atlas Vector | 文档 DB + 向量 | 两个集合/索引，查询接口不同 |
| **PostgreSQL + pgvector** | **1 个数据库** | 一次 SQL 同时查结构化列和向量距离 |

在 `query_documents` 中，一个查询同时完成：
- `WHERE user_id = :uid` — 按用户过滤（关系型）
- `ORDER BY embedding <=> :query_emb` — 按语义相似度排序（向量型）
- `LIMIT :n` — 取 top-N

**不需要把向量检索和结构化过滤分开两个系统再在应用层合并。**

### 3.2 事务性（ACID）

作为教育系统，数据一致性至关重要：

- 学习路径创建时同时写入 `LearningPath` + `LearningPathItem`（同事务）
- 资源生成时创建 `GenerationBatch` + N 个 `GenerationTask` + N 个 `ResourceMeta`（同事务）
- KG 构建时批量写入 Node + Edge（同事务）

PostgreSQL 的 ACID 保证这些多表写入要么全部成功要么全部回滚。

### 3.3 强大的索引体系

数据库层使用 **4 种索引类型**覆盖不同查询模式：

| 索引类型 | 用途 | 数量 |
|----------|------|------|
| B-Tree | 常规查询（单列 + 复合） | 23 个 |
| IVFFlat | 向量近似检索 | 1 个 |
| UNIQUE | 约束（主键 + 唯一列） | 7 个 |
| 复合索引 | 多列组合查询覆盖 | 6 个 |

所有索引在 ORM 模型中声明（`backend/db/models.py`），通过 Alembic 迁移管理，确保代码与数据库索引一致。

### 3.4 生态成熟

- **pgvector** 是 GitHub 14K+ stars 的成熟扩展，PostgreSQL 17.10 完全兼容
- **SQLAlchemy 2.0** 对 PostgreSQL 的支持是最完善的方言之一（ENUM、JSONB、ON CONFLICT 均有原生映射）
- **asyncpg** 是 Python 生态最快的 PostgreSQL 异步驱动，性能远超 psycopg2
- **Alembic** 对 PostgreSQL DDL 支持完善（`CREATE INDEX CONCURRENTLY`、`ALTER TYPE ADD VALUE` 等）
- PostgreSQL 每 4 年一个 LTS 大版本，17 系列 EOL 到 2029-11

### 3.5 运维简单

- 只需要一个服务：不需要同时维护关系数据库 + 向量数据库 + 缓存
- 备份一条命令：`pg_dump` 备份所有数据（结构化 + 向量）
- 迁移一条命令：`alembic upgrade head`
- 监控一条 SQL：`pg_stat_activity` / `pg_stat_user_indexes` 查看连接和索引使用情况
- 单机即可支撑数万文档向量 + 高并发查询

### 3.6 开源免费

PostgreSQL 采用 PostgreSQL License（类 MIT），无商业限制，无连乘计费，可以：
- 在本地开发环境免费使用
- 在校内服务器私有部署
- 在任何云平台（阿里云/RDS、AWS RDS、Supabase）一键部署
- 源代码完全开放，可审计

---

## 四、如果把数据库换成其他方案

| 特性 | MySQL 8.0 | SQLite | MongoDB | PostgreSQL 17 |
|------|-----------|--------|---------|---------------|
| pgvector 向量检索 | 不支持 | 不支持 | 需 Atlas Vector（付费） | 原生支持 |
| `ON CONFLICT` | `ON DUPLICATE KEY` | 支持 | upsert 语法不同 | 原生支持 |
| `ANY(:array)` | 需 unnest | 不支持 | 不同原生支持 | 原生支持 |
| `SET LOCAL` 参数 | 不支持 | 不支持 | 不支持 | 原生支持 |
| 原生 ENUM | 支持 | CHECK 约束替代 | 无约束 | 原生支持 |
| JSONB + GIN 索引 | JSON 无 GIN | JSON 无索引 | 原生 BSON | 原生支持 |
| 连接池（asyncpg） | aiomysql | aiosqlite | motor | **asyncpg 最快** |
| 复合索引 | 支持 | 支持 | 支持 | 支持 |
| 外键 + CASCADE | 支持 | 支持 | 不支持 | 支持 |
| 开源免费 | 社区版免费 | 免费 | SSPL（有限制） | 完全免费 |

PostgreSQL 是本项目唯一能同时满足 **关系型强一致性 + 向量检索 + 开源免费** 需求的选择。

---

## 五、总结

本项目对 PostgreSQL 的使用是 **深度而非广度** 的：

- 没有用 20 个扩展，但 **pgvector 这一个扩展用到了核心链路**（文档导入 → 向量索引 → 语义检索 → RAG）
- **6 个 ENUM + 7 个 JSONB 列 + 23 个 B-Tree 索引 + 1 个 IVFFlat 索引 + 6 个复合索引** 构成了完整的查询优化体系
- **ON CONFLICT + ANY() + SET LOCAL** 三个 SQL 特性让应用层代码更简洁、更高效
- **asyncpg 连接池** 提供了生产级的异步并发能力

PostgreSQL 为项目带来的最大价值是 **复杂查询可以在一次 SQL 中完成**（结构化过滤 + 向量排序 + 分页），无需在应用层拼接多个系统的结果。
