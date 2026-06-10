# RAG Query Rewrite 可行性分析与实现

> 分析日期：2026-05-21 | 实现日期：2026-05-21 | 最后更新：2026-05-25
> 基于 pgvector + DashScope text-embedding-v4 方案
> 状态：**策略 A+B+C 全部实现**，已集成 evaluation collector 自动采集检索质量指标

---

## 1. 什么是 Query Rewrite

Query Rewrite（查询改写）是 RAG 系统中位于"用户输入"和"向量检索"之间的一个预处理环节。其核心思想是：**用户输入的原始表述往往不适合直接作为检索查询**，需要经过改写、扩展或分解，生成更适合向量检索的 query。

典型问题场景：

| 用户输入 | 直接检索的问题 | 改写后的理想查询 |
|----------|---------------|-----------------|
| "上次那个反向传播你再说说" | "那个"指代不明，无上下文 | "反向传播算法的原理和计算步骤" |
| "SGD 和 Adam 哪个好" | 缩写、口语化、缺少领域限定 | "随机梯度下降 SGD 与 Adam 优化器的对比 优缺点" |
| "怎么防止过拟合" | 知识薄弱点，应从基础开始 | "过拟合的定义 原因 正则化 Dropout 早停 等防止过拟合的方法" |

---

## 2. 当前项目的 Query 链路

```
用户消息 (user_message)
  │
  ├─→ profile_agent      画像提取（与检索无关）
  │
  └─→ planner_agent      意图分类 + kp_id 提取
        │
        │  kp_id = "反向传播"   ← LLM 从消息中提取的知识点名称
        │
        ▼
      生成 Agent (如 doc_agent)
        │
        ├─→ resolve_kp_name(kp_id)   → "反向传播"
        │
        ├─→ retrieve_by_kp(kp_name)
        │     │
        │     │  query = f"知识点：反向传播；定义：反向传播；反向传播的核心概念与原理"
        │     │           ↑ 硬编码的三段式模板
        │     │
        │     ├─→ get_embedding(query)   → 1024-dim 向量
        │     │
        │     └─→ query_documents()     → pgvector <=> 余弦检索
        │
        └─→ chat_completion(prompt_with_context)   → 生成最终内容
```

### 2.1 当前存在的可用信息

在检索发生的时刻（生成 Agent 调用 `retrieve_context` 时），以下信息**已经可用但未被利用**：

| 信息 | 位置 | 当前是否用于检索 |
|------|------|:---:|
| `user_message`（原始提问） | `state.user_message` | ❌ 完全未用 |
| `chat_history`（多轮对话） | `state.chat_history` | ❌ 完全未用 |
| `profile`（学生画像） | `state.profile` | ❌ 完全未用 |
| `kp_id`（知识点名称） | `state.kp_id` | ✅ 唯一检索输入 |

### 2.2 当前仅有的一次"隐性"改写

```python
# backend/rag/retriever.py:114
query = f"知识点：{kp_name}；定义：{kp_name}；{kp_name}的核心概念与原理"
```

这是一个固定模板的查询扩展，不能称为真正的 Query Rewrite。需要进一步探索。

---

## 3. 主流的 Query Rewrite 策略

### 3.1 策略矩阵

| 策略 | 核心思想 | LLM 调用 | 延迟增加 | 收益 |
|------|---------|:---:|:---:|------|
| **A. 对话去上下文化** | 利用 chat_history 将指代词替换为具体实体 | 是 | +1 次 | 高（多轮对话必需） |
| **B. 画像感知改写** | 利用学生薄弱点调整检索角度 | 是 | +1 次 | 中（个性化检索） |
| **C. 多角度查询扩展** | 从不同角度生成 3-5 条子查询，合并检索结果 | 是 | +1 次 | 高（提升召回率） |
| **D. HyDE（假设文档嵌入）** | 先生成一段假想答案，用答案做检索 query | 是 | +1 次 | 中（对事实型问题有效） |
| **E. Step-Back Prompting** | 先抽象问题到更高层次，用抽象 query 检索 | 是 | +1 次 | 中（对概念对比型有效） |
| **F. 关键词提取 + 权重调整** | 用 jieba 提取关键词，调整 rerank 权重 | 否 | < 5ms | 低（轻度提升） |

### 3.2 策略详解

#### A. 对话去上下文化（Conversational De-contextualization）

```
输入:  chat_history + "上次那个你再说说"
输出:  "请解释反向传播算法的原理和数学推导过程"
```

这是多轮对话 RAG 系统**最核心**的 Query Rewrite 类型。当前项目的 `user_message` 直接传给 planner 做 `kp_id` 提取（planner 确实使用了 chat_history），但 `kp_id` 是一个孤立的名称，丢失了用户原始问题的细节。如果用户问的是"反向传播中梯度消失怎么解决"，提取的 kp_id 是"反向传播"，检索时就丢失了"梯度消失"这个关键约束。

#### B. 画像感知改写

```
输入:  kp_name + profile(薄弱点: ["激活函数选择", "梯度计算"])
输出:  "激活函数 ReLU Sigmoid Tanh 的选择 梯度计算 入门"
```

利用学生画像将查询偏向学生的薄弱领域。对 QuizAgent 生成针对性题目、对 DocAgent 生成针对性文档尤其有价值。

#### C. 多角度查询扩展（Multi-Query Expansion）

```
输入:  "反向传播"
输出:  ["反向传播算法原理", "BP 算法数学推导链式法则", "反向传播计算步骤示例", "梯度下降与反向传播的关系"]
```

从多个角度生成 3-5 条子查询，分别检索后对结果做 RRF 融合。这是提升召回率最有效的方法，代价是 embedding 调用和检索次数翻倍。

#### D. HyDE（Hypothetical Document Embeddings）

```
输入:  "什么是反向传播"
Step 1: LLM 生成假想答案 "反向传播是训练神经网络的核心算法，通过链式法则从输出层向输入层逐层计算梯度..."
Step 2: 用假想答案的 embedding 做检索（而非原问题的 embedding）
```

原理：假想答案的向量分布更接近真实文档，能更好地匹配。

#### E. Step-Back Prompting

```
输入:  "SGD 和 Adam 哪个好"
Step 1: 抽象 → "神经网络优化算法"
Step 2: 用抽象 query 检索 → 获得优化器相关文档
Step 3: LLM 在丰富的优化器上下文中回答 SGD vs Adam
```

#### F. 关键词提取 + 权重（零 LLM 调用）

直接使用 jieba 分词提取有效关键词，与现有 `_rerank_by_keyword_overlap` 整合。这是最轻量的方案，但效果有限。

---

## 4. 项目适配性分析

### 4.1 策略 A：对话去上下文化 —— **强烈推荐**

**匹配度：极高**

项目的多轮对话场景决定了这是刚需。当前 planner 虽然用 chat_history 提取了 kp_id，但 kp_id 只是一个知识点名称，丢失了用户问题的完整语义。

**插入位置**：`retrieve_context()` 调用之前，在生成 Agent 中。

**实现方式**：

```python
# 在 agents/utils.py 新增
async def rewrite_query_with_history(
    user_message: str,
    kp_name: str,
    chat_history: list[dict],
) -> str:
    """利用对话历史将用户消息改写为独立的检索查询。"""
    if not chat_history:
        return f"{user_message} {kp_name}"

    prompt = f"""将学生的多轮对话消息改写为一个独立的、完整的检索查询。
    
对话历史：
{_format_history(chat_history)}

学生最新消息：{user_message}
提取的知识点：{kp_name}

改写规则：
1. 将"这个"、"上面那个"、"刚才说的"等指代词替换为具体概念
2. 补全省略的主语和背景信息
3. 保留原始问题的具体细节（如"怎么推导"、"有什么例子"）
4. 输出一段 30-80 字的自然语言查询，而非关键词列表

只返回改写后的查询文本。"""

    rewritten = await chat_completion(
        [{"role": "user", "content": prompt}],
        temperature=0.1,
        max_tokens=150,
    )
    return rewritten.strip()
```

**延迟影响**：+1 次 LLM 调用（~200-500ms，用低 temperature + 短 token 可控制在 300ms 内）

### 4.2 策略 B：画像感知改写 —— **推荐**

**匹配度：高**

教育场景下，同一知识点对不同学生的侧重点完全不同。数学系学生和计算机系学生对"反向传播"的需求差异很大。画像感知改写可以将检索偏向学生的薄弱领域和认知风格。

**插入位置**：与策略 A 合并为一次 LLM 调用（减少延迟）。

```python
# 合并 A + B
prompt = f"""改写以下查询，用于检索学习资料：

学生画像：
- 薄弱知识点：{profile.knowledge_weak}
- 学习目标：{profile.learning_goal}
- 认知风格：{profile.cognitive_style}

知识点：{kp_name}
原始问题：{user_message}

改写为适合检索的查询，偏向学生的薄弱领域。输出 30-80 字。"""
```

### 4.3 策略 C：多角度查询扩展 —— **推荐**

**匹配度：高**

当前 `retrieve_by_kp` 已经有三段式模板（知识点 + 定义 + 核心概念），是一种简化的多角度查询。用 LLM 替代固定模板可以显著提升覆盖度。

**插入位置**：替换 `retrieve_by_kp` 内的硬编码模板。

**延迟影响**：+1 次 LLM 调用，但检索次数从 1 次变为 3-5 次（embedding + DB 查询 × N）。总延迟增加 ~500ms + N×20ms。

### 4.4 策略 D：HyDE —— **条件推荐**

**匹配度：中等**

HyDE 对事实型、概念型问题效果好（"什么是 XX"），对过程型问题（"怎么实现 XX"）效果一般。学习场景中两者都有，建议与策略 C 结合使用。

**风险**：如果 LLM 生成的假想答案本身包含错误，可能把检索引偏。

### 4.5 策略 E：Step-Back —— **条件推荐**

**匹配度：中等**

当用户问题涉及两个概念的对比（"SGD vs Adam"）或多概念串联时效果好。学习场景中常见，但频率不如直接的知识点提问。

### 4.6 策略 F：零 LLM 关键词 —— **低优先级**

**匹配度：低**

当前已有 `_rerank_by_keyword_overlap`，再用 jieba 优化的边际收益小。不如直接上策略 C。

---

## 5. 实施状态

### 5.1 已实施：Phase 1（策略 A + B 合并）+ 策略 C 可配置

```
实施后的流程:
  retrieve_context(state, agent_label)
    ├─ [enabled=true] _rewrite_query(user_message, kp_name, chat_history, profile)
    │    ├─ 策略A：用 chat_history 消解指代
    │    ├─ 策略B：用 profile 偏向薄弱领域
    │    └─ 失败 → _build_fallback_query()（回退安全网）
    │
    ├─ [multi_query=true] _expand_queries(rewritten_query, n=3)
    │    └─ retrieve_with_queries() → RRF 融合
    │
    ├─ [multi_query=false] retrieve(rewritten_query) → 单查询检索
    │
    └─ [enabled=false] retrieve_by_kp(kp_name) → 固定模板（降级，与旧版一致）
```

### 5.2 改动文件清单

| 文件 | 改动 | 行数 |
|------|------|:---:|
| `backend/config.py` | `RAGConfig` 新增 7 个 `query_rewrite_*` 扁平字段 | +7 |
| `configs/config.yaml` | 新增 `rag.query_rewrite` 嵌套配置节（YAML 嵌套 → Python 扁平映射） | +9 |
| `backend/agents/utils.py` | 新增 `_rewrite_query()`、`_expand_queries()`、`_rrf_fusion()`、`_build_fallback_query()`；重写 `retrieve_context()` 签名改为 `(state, agent_label)`；集成 evaluation collector | ~230 |
| `backend/rag/retriever.py` | 新增 `retrieve_with_queries()` 多查询并发检索 | +30 |
| `backend/agents/doc_agent.py` | `retrieve_context(kp_name, user_id, label)` → `retrieve_context(state, label)` | -1/+1 |
| `backend/agents/code_agent.py` | 同上 | -1/+1 |
| `backend/agents/quiz_agent.py` | 同上 | -1/+1 |
| `backend/agents/mindmap_agent.py` | 同上 | -1/+1 |
| `backend/agents/summary_agent.py` | 同上 | -1/+1 |

### 5.3 配置说明

```yaml
# configs/config.yaml
rag:
  query_rewrite:
    enabled: true              # 总开关，false 则完全回退到固定模板
    decontextualize: true      # 策略A：多轮对话指代消解
    profile_aware: true        # 策略B：根据薄弱点/学习目标改写
    multi_query: false         # 策略C：多角度扩展 + RRF（默认关闭，生产稳定后开启）
    multi_query_count: 3       # 扩展查询条数
    temperature: 0.1           # 改写 LLM 温度
    max_tokens: 150            # 改写输出 token 数
```

### 5.4 容错设计

实现了三层回退安全网，确保 Query Rewrite 失败时不影响检索：

```
Layer 1: _rewrite_query() LLM 失败 → _build_fallback_query(user_message, kp_name)
         └─ 智能回退：短消息且包含知识点 → "{user_message} 核心概念 原理 示例"
         └─ 否则 → "{kp_name}：{user_message[:120]}"
Layer 2: _expand_queries() LLM 失败 → 返回 [rewritten_query]（不做多角度扩展）
Layer 3: query_rewrite.enabled = false → 完全回退到旧版固定模板 retrieve_by_kp()
```

此外，当对话历史为空**且**画像信息不可用时，`_rewrite_query()` 直接跳过 LLM 调用返回 fallback query（零额外延迟）。

### 5.5 缓存策略（请求级）

同一生成请求内多个 Agent 可能检索相同知识点，两层缓存避免重复开销：

| 缓存 | Key | 命中场景 | 生命周期 |
|------|-----|---------|---------|
| `_rewrite_cache` | `(user_message, kp_name)` | 同一请求内多个 Agent 使用相同改写结果 | `clear_retrieval_cache()` 清除 |
| `_retrieval_cache` | `(kp_name, user_id)` | 同一知识点 + 同一用户的检索结果复用 | `clear_retrieval_cache()` 清除 |

### 5.6 评估采集集成

`retrieve_context()` 内置了 evaluation collector 自动采集，零额外代码：

```python
# backend/agents/utils.py:356-372
from backend.evaluation.collector import collector
collector.start_query(query=rewritten_query, kp_name=kp_name, ...)
collector.record_retrieval(scores=[...], chunk_ids=[...], ...)
```

每次检索自动记录：查询文本、检索分数分布、chunk ID 列表、embedding/DB 延迟估算。collector 不可用时静默跳过（不阻断检索）。

### 5.7 效果评估方法

建议在实施前后用 `evaluation/` 模块采集以下指标对比：

| 指标 | 采集方式 | 预期改善 |
|------|---------|---------|
| 召回率 (recall@5) | Judge 模块 | +10-25% |
| 检索结果与问题的相关度 | Judge `relevance_labels` | +15-30% |
| 生成内容的完整度 | Judge `completeness_score` | +5-15% |
| 多轮对话场景的检索命中率 | hit_rate（按 intent_type 分组） | +20-40% |

---

## 6. 已实现的成本优化

### 6.1 请求级改写缓存（已实现）

同一生成请求内，多个 Agent 可能检索相同知识点。`_rewrite_cache` 以 `(user_message, kp_name)` 为 key 缓存改写结果，后续 Agent 直接命中。

### 6.2 智能跳过改写（已实现）

在 `_rewrite_query()` 开头检查：如果既无对话历史又无画像信息（`decontext_section` 和 `profile_section` 均为空），直接调用 `_build_fallback_query()` 跳过 LLM 调用。`_build_fallback_query()` 的优化逻辑：

- 用户消息 ≤80 字符且包含知识点名 → 直接拼接 `"{user_message} 核心概念 原理 示例"`
- 否则 → `"{kp_name}：{user_message[:120]}"`

---

## 7. 总结

| 维度 | 结论 |
|------|------|
| **能否做** | ✅ 已实现 |
| **值得做吗** | ✅ 当前 kp_name 直接嵌入是最薄弱的环节，Query Rewrite 是 ROI 最高的 RAG 增强 |
| **已实施** | 策略 A+B 合并（对话去上下文 + 画像感知），策略 C 可配置启用 |
| **风险** | 低。三层回退安全网 + 智能跳过改写，LLM 失败自动回退固定模板 |
| **延迟增加** | ~300-500ms（1 次轻量 LLM 调用），无对话/画像时自动跳过改写（零延迟） |
| **代码改动量** | 9 个文件，~280 行净增（含 evaluation collector 集成） |
| **下一步** | 生产环境观察效果 → 开启 multi_query → 评估召回率改善 |

```
Query Rewrite 在 RAG 增强路线图中的位置：

Phase 1 ✅ 元数据字段 + 父子切割   ← 已完成 (2026-05-25, 迁移 8b3c4d5e6f7g)
Phase 2 ✅ Query Rewrite          ← 已实现 (2026-05-21, 策略 A+B+C + evaluation collector)
Phase 3 ✅ 增量索引更新            ← 已完成 (2026-05-25, content_hash diff)
Phase 4 🔲 关键词融合检索          ← 待实施
Phase 5 🔲 RAG 评估体系落地        ← 待实施 (ANALYSIS_PARENT_CHILD_TESTING.md)
```
