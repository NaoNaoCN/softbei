# 系统 Token 消耗分析报告

分析日期: 2026-06-10
LLM 提供方: DashScope (qwen3.6-plus-2026-04-02)
Token 估算系数: 中文字符/token ≈ 1.5, 英文字符/token ≈ 4.0（来自 configs/config.yaml）


## 一、LLM 调用架构总览

系统通过 `backend/services/llm.py` 统一调用 LLM，每次请求经过 LangGraph 状态机（11 个 Agent 节点）按条件路由执行。

### 单次用户请求的 Agent 调用路径

```
用户消息
  │
  ├─ profile_agent (1-3 次 LLM 调用)
  │    ├─ 画像提取 (必选)
  │    ├─ 意图判断 (必选)
  │    └─ 追问引导 (画像不完整时触发)
  │
  ├─ planner_agent (1-2 次 LLM 调用)
  │    ├─ 意图分类: generate vs clarify (有对话历史时触发)
  │    └─ 资源类型路由 (必选，generate 路径)
  │
  ├─ [生成路径] generation_agent (1 次 LLM 调用)
  │    └─ 前置: RAG Query Rewrite (1 次 LLM 调用，可配置)
  │
  ├─ [生成路径] safety_agent (1 次 LLM 调用)
  │
  └─ recommend_agent (1 次 LLM 调用)
```

### 额外 LLM 调用（非每次触发）

| 场景 | 调用 | 触发条件 |
|------|------|----------|
| 对话标题生成 | 1 次 LLM 调用 | 新建聊天会话时 |
| 知识图谱构建 | 多次 LLM 调用 | 文档导入后手动触发 |
| RAG 评估 (LLM-as-Judge) | 1-3 次 LLM 调用 | 按采样率触发（开发环境 100%，生产 10%） |
| 智能资源规划 | 1 次 LLM 调用 | 前端调用 `/generate/smart` 时 |
| 学习计划排程 | 1 次 LLM 调用 | 生成学习计划时 |
| 学习报告邮件 | 1 次 LLM 调用 | 前端触发（当前未接入） |


## 二、各 Agent 的 System Prompt Token 估算

System prompt 在每次 LLM 调用中作为固定开销计入 input tokens。以下按实际 prompt 文本统计：

| Agent | Prompt 名称 | 中文字符数 | 估算 tokens |
|-------|------------|-----------|------------|
| profile | extract (画像提取) | ~450 | ~300 |
| profile | intent (意图判断) | ~80 | ~55 |
| profile | onboarding_clarify | ~180 | ~120 |
| profile | resource_clarify | ~180 | ~120 |
| profile | no_docs_guide | ~260 | ~175 |
| profile | profile_confirm | ~220 | ~145 |
| profile | profile_confirm_with_docs | ~180 | ~120 |
| planner | system_prompt (资源路由) | ~700 | ~465 |
| planner | intent_classify | ~360 | ~240 |
| planner | smart_plan | ~480 | ~320 |
| doc | system_prompt | ~1,700 | ~1,135 |
| mindmap | system_prompt | ~940 | ~625 |
| quiz | system_prompt | ~1,350 | ~900 |
| code | system_prompt | ~830 | ~555 |
| anim | system_prompt | ~3,300 | ~2,200 |
| summary | system_prompt | ~1,020 | ~680 |
| safety | system_prompt | ~1,080 | ~720 |
| recommend | system_prompt | ~660 | ~440 |
| clarify | system_prompt | ~280 | ~185 |
| rag | rewrite | ~380 | ~255 |
| rag | expand | ~190 | ~125 |
| kg_builder | node_extract | ~450 | ~300 |
| kg_builder | edge_extract | ~1,200 | ~800 |
| kg_builder | edge_extract_cross | ~450 | ~300 |


## 三、典型场景 Token 消耗明细

### 场景 A: 澄清/追问路径（最轻量）

用户追问之前的回答内容，流程为: profile → planner → clarify → END

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1. 画像提取 | profile.extract | ~500 | ~100 | ~600 |
| 2. 意图判断 | profile.intent | ~300 | ~10 | ~310 |
| 3. 意图分类 | planner.intent_classify | ~500 | ~30 | ~530 |
| 4. 澄清回答 | clarify | ~1,200 | ~300 | ~1,500 |
| **合计** | **4 次调用** | **~2,500** | **~440** | **~2,940** |

> **说明**: 此路径不经过 RAG、safety、recommend，是系统最轻量的路径。


### 场景 B: 文档生成（最常用完整路径）

用户请求"帮我生成卷积神经网络的学习资料"，画像完整：profile → planner → (RAG rewrite) → doc → safety → recommend

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1. 画像提取 | profile.extract | ~500 | ~100 | ~600 |
| 2. 意图判断 | profile.intent | ~300 | ~10 | ~310 |
| 3. 意图分类 | planner.intent_classify | ~500 | ~30 | ~530 |
| 4. 资源路由 | planner.system_prompt | ~3,000 | ~80 | ~3,080 |
| 5. Query Rewrite | rag.rewrite | ~800 | ~60 | ~860 |
| 6. 文档生成 | doc (含 RAG context) | ~5,000 | ~3,000 | ~8,000 |
| 7. 安全审核 | safety | ~2,500 | ~200 | ~2,700 |
| 8. 推荐 | recommend | ~1,500 | ~500 | ~2,000 |
| **合计** | **8 次调用** | **~14,100** | **~3,980** | **~18,080** |

> **说明**: 第 5 步 Query Rewrite 可通过 `rag.query_rewrite_enabled` 关闭（省 ~860 tokens）。
> 第 6 步的输入 tokens 主要由 System Prompt (~1,135 tokens) + RAG 检索上下文 (最多 3,000 tokens budget，实际 1,500-2,500 tokens) 组成。
> 第 7 步输入包含 System Prompt (~720 tokens) + 参考资料 (~800 tokens) + 草稿预览 (~3,000 chars ≈ 2,000 tokens)。


### 场景 C: 动画生成（最重量单次调用）

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1-5 | profile + planner + RAG rewrite | ~5,280 | ~280 | ~5,560 |
| 6. 动画生成 | anim (含 RAG context) | ~6,000 | ~5,000 | ~11,000 |
| 7. 安全审核 | safety | ~2,500 | ~200 | ~2,700 |
| 8. 推荐 | recommend | ~1,500 | ~500 | ~2,000 |
| **合计** | **8 次调用** | **~15,280** | **~5,980** | **~21,260** |

> **说明**: anim 的 System Prompt 最长（~3,300 字符 ≈ 2,200 tokens），包含完整的 p5.js API 文档和布局规范。max_tokens=6000，实际输出 p5.js 代码通常 2,500-5,000 tokens。


### 场景 D: 测验生成

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1-5 | profile + planner + RAG rewrite | ~5,280 | ~280 | ~5,560 |
| 6. 题目生成 | quiz (含 RAG context) | ~5,500 | ~2,500 | ~8,000 |
| 7. 安全审核 | safety | ~2,500 | ~200 | ~2,700 |
| 8. 推荐 | recommend | ~1,500 | ~500 | ~2,000 |
| **合计** | **8 次调用** | **~14,780** | **~3,480** | **~18,260** |


### 场景 E: 思维导图生成（最轻量生成）

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1-5 | profile + planner + RAG rewrite | ~5,280 | ~280 | ~5,560 |
| 6. 导图生成 | mindmap (含 RAG context) | ~4,000 | ~1,500 | ~5,500 |
| 7. 安全审核 | safety | ~2,500 | ~200 | ~2,700 |
| 8. 推荐 | recommend | ~1,500 | ~500 | ~2,000 |
| **合计** | **8 次调用** | **~13,280** | **~2,480** | **~15,760** |


### 场景 F: 首次对话 + 画像不全（追问引导）

用户首次发消息"你好"，画像为空，系统追问引导 → END

| 步骤 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|------|---------|------------|------------|------|
| 1. 画像提取 | profile.extract | ~500 | ~50 | ~550 |
| 2. 意图判断 | profile.intent | ~300 | ~10 | ~310 |
| 3. 追问引导 | profile.onboarding_clarify | ~400 | ~200 | ~600 |
| **合计** | **3 次调用** | **~1,200** | **~260** | **~1,460** |


## 四、其他 LLM 调用场景

### 4.1 对话标题自动生成

新建会话时自动调用，轻量级：

| 项目 | 值 |
|------|-----|
| System prompt | "根据首条消息生成≤15字标题" (~60 chars ≈ 40 tokens) |
| 用户消息 | 截断至 200 字符 (~130 tokens) |
| max_tokens | 30 |
| **单次总消耗** | **~200 tokens** |

触发频率: 每个新会话 1 次。

### 4.2 知识图谱构建 (`/kg/build`)

从文档构建 KG，按文档分块批量调用 LLM：

| 阶段 | LLM 调用次数 | 单次输入 tokens | 单次输出 tokens | 总消耗估算 |
|------|------------|---------------|---------------|-----------|
| 节点提取 | N 批 (最多 30) | ~2,000 | ~1,500 | 30 × 3,500 = ~105,000 |
| 章节内边提取 | N 批 | ~2,000 | ~1,000 | 30 × 3,000 = ~90,000 |
| 跨章节边提取 | 1 批 (可选) | ~1,500 | ~500 | ~2,000 |
| **总计 (30 批文档)** | **~60 次** | | | **~197,000** |

> **说明**: 这是系统中最昂贵的单次操作。对于 50 页的 PDF 教材（约 100,000 字符），按每批 6,000 字符送入约 17 批，总消耗约 110,000 tokens。按 qwen3.6-plus 的定价（输入 ¥3.5/百万 tokens, 输出 ¥14/百万 tokens），一次 KG 构建约 ¥0.4-0.7。

### 4.3 智能资源规划 (`POST /generate/smart`)

独立于主对话流程，前端按需触发：

| 项目 | 值 |
|------|-----|
| System prompt | smart_plan (~480 chars ≈ 320 tokens) |
| User message | 学生画像 + 目标知识点 (~300 chars ≈ 200 tokens) |
| 输出 | 2-3 个资源类型 (~30 tokens) |
| **单次总消耗** | **~550 tokens** |

### 4.4 RAG 评估 (LLM-as-Judge)

在开发模式下每次生成后以 100% 采样率触发，生产模式 10%：

| 评估维度 | LLM 调用 | 输入 tokens | 输出 tokens | 小计 |
|---------|---------|------------|------------|------|
| 忠实度 (Faithfulness) | judge | ~3,000 | ~500 | ~3,500 |
| 完整度 (Completeness) | judge | ~2,500 | ~500 | ~3,000 |
| **每次 Judge** | **1 次调用** | **~3,000** | **~500** | **~3,500** |

> **说明**: 交叉验证 (cross_validation) 模式会增加 1 倍消耗（当前默认关闭）。
> 开发环境每次生成额外消耗 ~3,500 tokens，生产环境 10% 采样则平均 +350 tokens/次。

### 4.5 学习计划排程 (`POST /study-plan/generate`)

| 项目 | 值 |
|------|-----|
| System prompt | seq (~1,400 chars ≈ 930 tokens) |
| User message | 画像 + 候选知识点列表 | 
| 输出 (max_tokens=2048) | 排好序的知识点列表 |
| **单次总消耗** | **~4,000 tokens** |

### 4.6 Embedding API

文本向量化调用 DashScope `text-embedding-v4`，不计入 LLM token 消耗，但有独立计费：

| 场景 | 调用次数 | 文本量估算 |
|------|---------|----------|
| RAG 检索（每次生成） | 1-2 次 (query + expanded queries) | ~200 chars |
| 文档索引（首次导入） | N 批 (N = 文本块数 / 10) | 全文档 |
| Embedding 健康检查 | 1 次 (启动时) | "ping" |


## 五、各场景 Token 消耗汇总

| 场景 | LLM 调用次数 | 输入 tokens | 输出 tokens | **总计** |
|------|------------|------------|------------|---------|
| A. 澄清/追问 | 4 | ~2,500 | ~440 | **~2,940** |
| F. 首次引导 | 3 | ~1,200 | ~260 | **~1,460** |
| E. 思维导图 | 8 | ~13,280 | ~2,480 | **~15,760** |
| B. 文档生成 | 8 | ~14,100 | ~3,980 | **~18,080** |
| D. 测验生成 | 8 | ~14,780 | ~3,480 | **~18,260** |
| C. 动画生成 | 8 | ~15,280 | ~5,980 | **~21,260** |
| 智能规划 | 1 | ~520 | ~30 | **~550** |
| 对话标题 | 1 | ~170 | ~30 | **~200** |
| 学习计划 | 1-2 | ~2,500 | ~1,500 | **~4,000** |
| KG 构建 (17 批) | ~35 | ~60,000 | ~50,000 | **~110,000** |
| RAG Judge (开发) | 1 | ~3,000 | ~500 | **~3,500** |
| 自动标题 | 1 | ~170 | ~30 | **~200** |


## 六、一条完整用户对话的 Token 预算

以一个典型的多轮对话为例（首次对话 → 生成文档 → 追问 → 生成测验）：

| 轮次 | 场景 | Tokens |
|------|------|--------|
| 第 1 轮 | 首次引导 (F) + 自动标题 | ~1,660 |
| 第 2 轮 | 文档生成 (B) + Judge (开发) | ~21,580 |
| 第 3 轮 | 追问澄清 (A) | ~2,940 |
| 第 4 轮 | 测验生成 (D) + Judge (开发) | ~21,760 |
| **4 轮总计** | | **~47,940** |

> 生产模式（Judge 采样 10%）：~45,640 tokens
> 生产模式（关 Judge + 关 Query Rewrite）：~43,000 tokens


## 七、成本估算（基于 qwen3.6-plus 官方定价）

qwen3.6-plus 定价（截至 2026 年 6 月）：
- 输入: ¥3.5 / 百万 tokens
- 输出: ¥14 / 百万 tokens

| 场景 | 输入费用 | 输出费用 | **单次费用** |
|------|---------|---------|------------|
| 首次引导 | ¥0.004 | ¥0.004 | **< ¥0.01** |
| 澄清追问 | ¥0.009 | ¥0.006 | **¥0.015** |
| 思维导图 | ¥0.046 | ¥0.035 | **¥0.081** |
| 文档生成 | ¥0.049 | ¥0.056 | **¥0.105** |
| 测验生成 | ¥0.052 | ¥0.049 | **¥0.101** |
| 动画生成 | ¥0.053 | ¥0.084 | **¥0.137** |
| KG 构建 (17 批) | ¥0.21 | ¥0.70 | **¥0.91** |
| 4 轮完整对话 | ¥0.12 | ¥0.22 | **¥0.34** |

> **按 qwen3.6-plus 价格计算，1000 次文档生成约 ¥105，100 个用户每人 10 轮对话约 ¥340。**


## 八、优化建议

### 8.1 已启用的优化

| 优化项 | 节省估算 | 状态 |
|--------|---------|------|
| RAG 检索缓存 (请求级) | 同一请求内多个 Agent 复用检索结果 | 已启用 |
| Query Rewrite 缓存 (请求级) | 避免重复改写 | 已启用 |
| `query_rewrite_multi_query: false` | 省 1 次 LLM 调用 + N 次 embedding | 已配置 |

### 8.2 可考虑的优化

| 优化项 | 预期节省 | 代价 |
|--------|---------|------|
| 关闭开发环境 Judge 100% 采样 | 每次生成省 ~3,500 tokens | 失去评估数据 |
| 缩短 safety_agent draft_preview | 每 1000 chars 省 ~670 input tokens | 审核覆盖面减小 |
| 合并 profile.extract + profile.intent 为单次调用 | 省 ~300 tokens/次 | 需重新设计 prompt |
| 缩小 planner 的 kp_list（当前上限 500 条） | 省 1000-3000 tokens | 可能影响 LLM 匹配精度 |
| 缓存 doc_agent 系统 prompt (服务端缓存) | 无 token 节省，但省网络延迟 | 需 prompt 缓存支持 |
| 对简单资源类型跳过 safety_agent | 省 ~2,700 tokens/次 | 风险：未审核内容 |
| 降低 anim.max_tokens (6,000 → 4,000) | 省最多 2,000 输出 tokens | 复杂动画可能被截断 |

### 8.3 最大头的 Token 消耗者

按消耗占比排序：

1. **generation_agent 的内容生成** — 占每次请求的 45-55%（System Prompt 长 + RAG 上下文大 + 输出长）
2. **safety_agent** — 占 13-15%（输入包含 draft 预览 + 参考资料）
3. **planner_agent 资源路由** — 占 15-18%（kp_list 可长达 500 条）
4. **recommend_agent** — 占 10-12%
5. **profile_agent** — 占 5-7%
6. **RAG Query Rewrite** — 占 4-5%

> **结论：优化的最大杠杆点在 generation_agent 的输入侧（缩短 System Prompt + 压缩 RAG 上下文）和输出侧（降低 max_tokens）。**
