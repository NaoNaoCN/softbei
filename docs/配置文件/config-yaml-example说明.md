# 配置文件说明

本文档介绍如何使用 `configs/config.yaml` 配置文件。

## 目录结构

```
configs/
├── config.yaml           # 本地实际配置（已 gitignored）
└── config.yaml.example   # 配置模板（提交到 Git）
```

## 快速开始

### 1. 复制模板

```bash
cp configs/config.yaml.example configs/config.yaml
```

### 2. 修改配置

编辑 `configs/config.yaml`，填入实际的值：

```yaml
database:
  url: "mysql+aiomysql://root:你的密码@localhost:3306/softbei"

llm:
  api_key: "你的API密钥"
```

### 3. 设置环境变量（如需）

敏感信息也可通过环境变量传入，支持 `${ENV_VAR}` 语法：

```yaml
database:
  url: "mysql+aiomysql://root:${DB_PASSWORD}@localhost:3306/softbei"

llm:
  api_key: "${LLM_API_KEY}"
```

然后设置环境变量：

```bash
# Linux/Mac
export DB_PASSWORD=123456
export LLM_API_KEY=sk-xxx

# Windows (CMD)
set DB_PASSWORD=123456
set LLM_API_KEY=sk-xxx

# Windows (PowerShell)
$env:DB_PASSWORD="123456"
$env:LLM_API_KEY="sk-xxx"
```

## 配置项说明

### database - 数据库配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| url | string | - | 数据库连接 URL，格式：`mysql+aiomysql://user:pass@host:port/db` |
| echo | bool | false | 是否打印 SQL 语句（调试用） |
| pool_size | int | 10 | 连接池大小 |
| max_overflow | int | 20 | 最大溢出连接数 |
| pool_timeout | int | 30 | 获取连接超时时间（秒） |
| pool_recycle | int | 3600 | 连接回收时间（秒） |

**连接 URL 格式：**

```
# MySQL
mysql+aiomysql://user:password@host:port/database

# SQLite（开发用）
sqlite+aiosqlite:///./dev.db
```

### vector_db - 向量数据库配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| persist_dir | string | "./chroma_data" | ChromaDB 持久化目录 |
| collection | string | "knowledge_base" | 默认集合名称 |

### llm - 大语言模型配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| api_key | string | - | API 密钥 |
| base_url | string | - | API 接口地址 |
| model | string | - | 模型名称 |

### rag - 检索增强生成配置

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| chunk_size | int | 500 | 文档分块大小 |
| chunk_overlap | int | 50 | 分块重叠大小 |
| embedding_model | string | "BAAI/bge-m3" | Embedding 模型 |

## 代码中使用配置

```python
from backend.config import config

# 数据库配置
config.database.url
config.database.pool_size

# 向量库配置
config.vector_db.persist_dir

# LLM 配置
config.llm.api_key

# RAG 配置
config.rag.chunk_size
```

## 常见问题

### Q: 配置文件加载失败？

确保 `configs/config.yaml` 文件存在：

```bash
ls configs/config.yaml
```

如果不存在，从模板复制：

```bash
cp configs/config.yaml.example configs/config.yaml
```

### Q: 环境变量没有生效？

1. 确保环境变量已正确设置
2. 重启应用程序（环境变量需要重新加载）
3. 检查 `${ENV_VAR}` 语法是否正确（不能有空格）

### Q: 数据库连接失败？

1. 确认 MySQL 服务已启动
2. 检查 `url` 中的用户名、密码、主机、端口是否正确
3. 确认数据库已创建：
   ```sql
   CREATE DATABASE softbei CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   ```

## 多环境配置（进阶）

如果需要开发/生产环境使用不同配置，可以创建多个配置文件：

```bash
cp configs/config.yaml.example configs/config.yaml.development
cp configs/config.yaml.example configs/config.yaml.production
```

然后在启动前指定配置文件路径（需要修改 `backend/config.py`）。

## 注意事项

1. **不要提交 `config.yaml`** - 包含敏感信息，已在 `.gitignore` 中排除
2. **`config.yaml.example` 可以提交** - 作为团队成员的配置模板
3. **敏感信息优先使用环境变量** - 避免密码明文写在配置文件中
