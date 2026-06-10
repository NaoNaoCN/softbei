# recommend_agent

# RecommendAgent - 学习推荐智能体

## 概述

RecommendAgent 是整个流水线的最后一个生成节点，负责基于学生画像和学习历史推荐下一步学习的知识点。它是一位智能学习顾问，能够从知识图谱中挑选最适合学生当前状态的知识点进行推荐。

## 核心职责

1. **候选查询** - 从知识图谱查询与已学知识点相邻的节点 **（按用户过滤）**
2. **智能推荐** - 结合画像调用 LLM 选出最优推荐
3. **推荐有效性验证** - 过滤掉 LLM 编造的虚假 kp_id
4. **可读文本生成** - 将推荐列表转为人类可读的 Markdown 格式
5. **结果存储** - 将推荐列表存入 `state.metadata["recommendations"]`

## System Prompt

```
你是一位智能学习顾问。
根据学生的当前画像和已学知识点，从知识图谱中推荐 3-5 个下一步应学习的知识点。

学生画像：
{profile}

已学知识点（已掌握）：{mastered}
薄弱知识点：{weak}
学习目标：{goal}

可选知识点（来自知识图谱）：
{available_kps}

重要规则：
- 你必须且只能从上面的"可选知识点"列表中选择推荐项
- kp_id 必须使用列表中冒号前的 ID（如 "kp_abc123"），不得自行编造
- kp_name 必须使用列表中冒号后的名称
- 如果可选知识点为空或不可用，返回空数组 []

以 JSON 数组返回，每项包含：
{"kp_id": "...", "kp_name": "...", "reason": "推荐原因"}
```

## 输入与输出

### 输入（AgentState）

| 字段 | 说明 |
| --- | --- |
| `profile` | 学生画像（含已掌握/薄弱知识点） |
| `kp_id` | 当前学习的知识点 |
| `user_id` | 用户 ID（知识图谱查询过滤） |
| `final_content` | 已生成的资源内容（用于决定是否追加推荐） |
| `metadata` | 现有元数据（用于追加 recommendations） |

### 输出（AgentState 更新）

| 字段 | 说明 |
| --- | --- |
| `metadata["recommendations"]` | 推荐知识点列表（JSON 数组） |
| `metadata["recommendations_text"]` | 可读的推荐文本（Markdown 格式） |
| `metadata["kp_name"]` | 当前知识点名称（供前端构造路径名） |
| `final_content` | 若无资源内容，写入推荐文本作为最终返回 |

## 推荐逻辑

#### **1. 候选查询**

- 从 `KGNode` 表查询知识点（按当前用户过滤：`user_id` 匹配或 `user_id IS NULL`）
- 构建可选知识点列表（格式：`kp_id: kp_name`）
- 记录 `valid_kp_ids` 集合用于后续验证

#### **2. 智能推荐**

- 调用 LLM，传入画像、已掌握/薄弱知识点、学习目标、可选知识点列表
- LLM 返回 JSON 数组：`[{"kp_id": "...", "kp_name": "...", "reason": "..."}]`

#### **3. 推荐有效性验证**

- 过滤掉 `kp_id` 不在 `valid_kp_ids` 中的虚假推荐
- 记录警告日志（若有过滤）

#### **4. 避免重复**

- 排除已在 `knowledge_mastered` 中的知识点（通过 Prompt 中的已掌握列表提示 LLM）

#### **5. 适配画像**

- **薄弱知识点优先**：Prompt 中单独列出 `weak` 字段，引导 LLM 优先推荐薄弱点相关
- **学习目标对齐**：`goal` 字段帮助 LLM 推荐与目标一致的路径

## 输出格式

```json
[
  {"kp_id": "kp_001", "kp_name": "线性回归", "reason": "是神经网络的前置知识"},
  {"kp_id": "kp_003", "kp_name": "梯度下降", "reason": "与当前知识点高度相关"},
  ...
]
```

## **执行流程**

1. **从 config 获取 db**（LangGraph 通过 config 传递）
2. **构建画像上下文**：
    - 调用 `profile_svc.build_profile_context(state.profile)`
    - 异常时 fallback `"（暂无画像信息）"`
3. **提取画像字段**：
    - `mastered`（已掌握知识点列表）
    - `weak`（薄弱知识点列表）
    - `goal`（学习目标）
4. **查询可用知识点（按用户过滤）**：
    - 从 `KGNode` 表查询（`user_id == user_uuid OR user_id IS NULL`）
    - 构建 `available_kps` 列表（格式：`kp_id: kp_name`）
    - 记录 `valid_kp_ids` 集合
    - 记录日志：查询到的知识点数量
5. **构造 Prompt**：
    - 填充 `profile`、`mastered`、`weak`、`goal`、`available_kps`
    - 列表为空时显示"无"或"未设定"
6. 调用 `chat_completion` 生成推荐（`temperature=0.7`, `max_tokens=2000`）
7. **处理 Markdown 代码块包裹的 JSON**
8. **JSON 解析**：
    - 成功：
        - 验证是否为列表（非列表则置为 `[]`）
        - 过滤无效 kp_id（不在 `valid_kp_ids` 中）
        - 写入 `metadata["recommendations"]`
        - 生成可读文本 `metadata["recommendations_text"]`
        - 写入 `metadata["kp_name"]`（供前端使用）
        - 若 `final_content` 存在 → 保留（推荐不追加）
        - 若 `final_content` 为空 → 写入推荐文本
    - JSONDecodeError：记录 warning + raw_preview，写入空列表
    - 其他异常：记录 error，写入空列表

## 依赖关系

- **上游**：SafetyAgent（安全审核后）
- **下游**：图的终点（END）

## 文件位置

`backend/agents/recommend_agent.py`