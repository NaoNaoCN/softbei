# Claude Code Skill 使用指南

## 1. 什么是 Skill

Skill 是 Claude Code 中的**可调用提示词模板**，本质上是将一段预定义的 prompt 绑定到一个名称上。当用户通过 `/skillName` 调用时，该 prompt 被展开并注入到当前会话上下文中，指导 Claude Code 以特定方式完成任务。

与普通对话的区别：
- **普通对话**：每次都要描述需求，Claude 需要重新理解你的意图
- **Skill**：一次定义，反复调用，行为一致性强，减少重复描述

## 2. Skill 的层级

Skill 有三个层级，加载优先级从低到高：

| 层级 | 位置 | 作用范围 | 示例 |
|------|------|----------|------|
| 内置 | Claude Code 内置 | 所有项目 | `update-config`、`simplify`、`loop`、`claude-api` |
| 项目级 | 项目 `.claude/skills/` 目录 | 当前项目的所有开发者 | 团队共享的 `/deploy`、`/lint` 等 |
| 个人级 | 用户 `~/.claude/skills/` 目录 | 个人全部项目 | 个人偏好风格的 `/commit` |

同名 Skill 时，个人级覆盖项目级，项目级覆盖内置。

## 3. 内置 Skill 详解

### 3.1 `update-config` — 配置 Claude Code 钩子

用于自动化行为配置，通过 `settings.json` 配置 hooks。钩子可以在特定事件发生时自动执行操作。

**触发场景**：当需要配置"从此以后当 X 时自动 Y"类行为时使用。

**样例**：配置在每次提交前自动运行测试。

调用方式：
```
/update-config
```

Claude 会引导你配置 `settings.json`，例如添加 pre-commit hook：
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "pattern": "git commit*",
        "prompt": "在运行 git commit 之前，先运行 pytest 确保所有测试通过"
      }
    ]
  }
}
```

---

### 3.2 `simplify` — 代码审查与优化

用于审查已修改的代码，检查复用性、质量和效率问题，并自动修复发现的问题。

**触发场景**：当你完成一个功能或修改后，想要让 Claude 审查代码质量。

**样例**：

调用方式：
```
simplify
```

Claude 会：
1. 运行 `git diff` 查看所有变更
2. 分析代码中是否存在重复逻辑、低效实现、不符合项目规范的地方
3. 自动对发现的问题进行修复

例如，如果你写了两段相似的错误处理逻辑，`simplify` 会建议提取公共函数，减少代码重复。

---

### 3.3 `loop` — 循环执行

以固定间隔重复执行某个 prompt 或斜杠命令。

**触发场景**：轮询检查部署状态、定时刷新数据、持续监控某个指标。

**语法**：`/loop <间隔> <命令>`

**样例**：

```bash
# 每 5 分钟检查一次服务健康状态
/loop 5m curl -s http://localhost:8000/health

# 每 30 秒查看一次 git 状态
/loop 30s git status

# 每 10 分钟运行一次测试
/loop 10m pytest tests/ -v --tb=short
```

支持的间隔格式：`Xs`（秒）、`Xm`（分钟）、`Xh`（小时）。

注意：任务默认 7 天后自动过期。如果需要持久化（跨会话），需指定 `durable: true`。

---

### 3.4 `claude-api` — Claude API 开发辅助

用于辅助构建基于 Claude API 或 Anthropic SDK 的应用。

**触发场景**：当代码中导入 `anthropic`、`@anthropic-ai/sdk` 或 `claude_agent_sdk` 时，或用户明确要求使用 Claude API 构建功能时。

**样例**：

调用方式：
```
claude-api
```

当你在代码中写入：
```python
import anthropic

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[{"role": "user", "content": "Hello"}]
)
```

`claude-api` skill 会提供关于 API 最佳实践、错误处理、流式响应、工具调用等方面的指导。

---

## 4. 自定义 Skill

### 4.1 Skill 文件格式

Skills 是 Markdown 文件，存放在 `.claude/skills/` 目录下。每个文件定义一个 skill。

**基本结构**：

```markdown
---
name: <skill 名称>
description: <简短描述，用于自动判断何时触发>
---

# <Skill 标题>

这里写 skill 的具体 prompt 内容。当用户调用这个 skill 时，
这部分内容会被注入到 Claude Code 的上下文中。
```

### 4.2 项目级 Skill 示例

在项目根目录创建 `.claude/skills/` 目录，然后添加 skill 文件。

#### 示例 1：`deploy.md` — 一键部署

**文件路径**：`.claude/skills/deploy.md`

```markdown
---
name: deploy
description: 执行项目的标准部署流程
---

# Deploy Skill

你是一个部署助手。当用户调用 /deploy 时，请按以下步骤操作：

1. 运行 `pytest tests/ -v` 确保所有测试通过
2. 检查 `.env` 文件是否存在且包含必要的环境变量（LLM_API_KEY, JWT_SECRET, DATABASE_URL）
3. 运行 `alembic upgrade head` 执行数据库迁移
4. 提示用户确认部署目标环境（开发/生产）
5. 根据目标环境，给出对应的启动命令

规则：
- 如果测试失败，中止部署并报告错误
- 如果缺少环境变量，列出缺失的变量和用途
- 每次部署前必须确认目标环境
```

**使用**：在对话中输入 `/deploy` 即可触发。

---

#### 示例 2：`cr.md` — 代码审查

**文件路径**：`.claude/skills/cr.md`

```markdown
---
name: cr
description: 对当前变更进行全面的代码审查，输出审查报告
---

# Code Review Skill

你是一个代码审查专家。对当前分支的所有变更进行审查。

## 审查清单

1. **安全性**
   - 是否有 SQL 注入风险（本项目用 SQLAlchemy ORM，但需检查原生 SQL）
   - 用户输入是否经过校验
   - JWT token 处理是否正确

2. **正确性**
   - 与后端 ORM 模型字段名是否一致（参考 CLAUDE.md 命名约定）
   - API 返回值是否与 schema 匹配

3. **性能**
   - 数据库查询是否有 N+1 问题
   - 向量检索的 ef_search 参数是否合理

4. **可维护性**
   - 系统提示词是否应放在 configs/prompts.yaml 而非硬编码
   - 日志是否使用 lazy evaluation（`{}` 占位符而非 f-string）
   - 是否使用了 `[AgentName]` 前缀

## 输出格式

使用表格输出审查结果，每行包含：
- 文件:行号
- 问题级别（严重/警告/建议）
- 问题描述
- 改进方案
```

**使用**：在对话中输入 `/cr` 即可触发。

---

#### 示例 3：`agent-debug.md` — Agent 调试

**文件路径**：`.claude/skills/agent-debug.md`

```markdown
---
name: agent-debug
description: 调试 LangGraph Agent Pipeline 问题，分析 Agent 状态流转
---

# Agent Debug Skill

你是一个 LangGraph Agent 调试专家。当用户调用 /agent-debug 时，
请分析项目中 11 个 Agent 的状态流转。

## 分析步骤

1. 查看 `backend/agents/graph.py` 的 StateGraph 定义
2. 确认当前 `AgentState` schema（`backend/models/schemas.py`）
3. 检查路由逻辑：`route_by_resource_type` 是否正确分发
4. 检查 `configs/prompts.yaml` 中对应 agent 的 system prompt
5. 分析问题所在节点的 LLM 调用和状态更新

## 关键检查点

- `intent_type` + `resource_type` 的组合是否覆盖所有场景
- Agent 节点的 `model_copy(update={...})` 是否正确传递了需要的字段
- `chat_history` 是否正确累积多轮对话
- RAG 检索缓存是否在每次 `graph.invoke()` 前清除

## 输出

输出一张状态流转表，标注当前请求经过的节点和每个节点的状态变化。
```

**使用**：当 agent pipeline 出现异常时，输入 `/agent-debug` 进行排查。

---

### 4.3 个人级 Skill 示例

放在 `~/.claude/skills/` 目录下，跨项目生效。

#### 示例：`my-commit.md` — 个人风格的提交

```markdown
---
name: my-commit
description: 使用我的个人风格创建 git commit
---

# My Commit Skill

你是一个 commit message 专家。当用户调用 /my-commit 时：

1. 运行 `git diff --staged` 和 `git status` 获取变更内容
2. 生成简洁的 commit message（中文）：
   - 标题：动词开头，不超过 50 字，格式：`类型: 简短描述`
   - 类型包括：feat, fix, refactor, docs, perf, test
3. 如果变更涉及多个不相关的文件，提醒用户拆分为多个 commit
4. 执行 `git commit -m "message"`，不使用 --no-verify

示例 output：
feat: 增加用户注销账户功能
```

---

## 5. Skill 的自动触发

Skill 不一定要手动调用。在 Skill 的 frontmatter 中，`description` 字段用于判断**何时自动触发**。

当用户的请求与 skill 的 `description` 匹配时，Claude Code 会提示该 skill 可用，或者自动触发（取决于 skill 定义中的 `trigger` 配置）。

例如，`claude-api` skill 的 description 写明了触发条件：
```
TRIGGER when: code imports anthropic/@anthropic-ai/sdk/claude_agent_sdk
```

当 Claude 检测到你正在编写包含这些导入的代码时，就会自动 invoke 该 skill。

---

## 6. 最佳实践

1. **description 要精确**：好的 description 让 Claude 知道什么时候该用这个 skill，什么时候不该用
2. **保持 Skill 短小**：一个 Skill 只做一件事，避免"万能 skill"
3. **写清楚规则而非步骤**：告诉 Claude *判断标准*而不是*固定步骤*，让 Claude 能根据实际情况灵活执行
4. **用 NEVER/IMPORTANT 分级**：参考项目 `configs/prompts.yaml` 中的 prompt 书写规范，对 skill 中的规则也标注优先级
5. **团队共享的 Skill 要写进版本控制**：放在 `.claude/skills/` 目录下并提交到 git

---

## 7. 当前项目 Skill 现状

| 项目 | 状态 |
|------|------|
| 项目级 Skill（`.claude/skills/`） | 未配置 |
| 个人级 Skill | 未配置 |
| 内置 Skill | 可用（4 个） |

需要自定义 Skill 时，在项目根目录创建 `.claude/skills/` 目录，按上述格式添加 Markdown 文件即可。
