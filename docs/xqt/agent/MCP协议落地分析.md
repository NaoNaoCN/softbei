# MCP 协议落地分析

> MCP（Model Context Protocol）是 Anthropic 提出的标准化协议，用于连接 AI 模型与外部工具/数据源。本文分析本项目与 MCP 的关系及落地方案。

---

## 一、当前项目与 MCP 的关系

### 结论：项目核心痛点与 MCP 解决的问题高度吻合，但目前未使用 MCP。

项目代码中零 MCP 引用。但架构中存在几个典型痛点，恰好是 MCP 设计要解决的：

| 项目痛点 | MCP 解决方式 |
|---------|-------------|
| RAG 检索、KG 查询、LLM 调用、DB 操作各自用不同接口 | MCP 统一为 Resource / Tool 两种抽象 |
| 多 Provider LLM 切换需要改 `llm.py` 代码 | MCP Tool 封装，Provider 变化对 Agent 透明 |
| Agent 与基础设施紧耦合（Agent 直接 import 各 service） | MCP Client/Server 解耦，组件独立演进 |
| 新增能力（如 Web Search）需要写新的 Agent 或 service | 新能力封装为 MCP Server 即可被所有 Agent 复用 |
| 没有标准化的外部系统接入方式 | MCP 就是外部系统接入的标准 |

---

## 二、什么是 MCP（30 秒速览）

MCP 定义了三种核心抽象：

```
┌─────────────────────────────────────────────┐
│               MCP Client                     │
│          (LangGraph Agent 等)                │
│                                              │
│   ┌──────────┐  ┌──────────┐  ┌──────────┐  │
│   │ Resource │  │   Tool   │  │  Prompt  │  │
│   │ (读数据)  │  │ (执行动作) │  │ (模板)   │  │
│   └──────────┘  └──────────┘  └──────────┘  │
│                    │                         │
└────────────────────┼─────────────────────────┘
                     │ JSON-RPC over stdio/SSE/HTTP
┌────────────────────┼─────────────────────────┐
│               MCP Server                      │
│                                              │
│   对外暴露：Resources / Tools / Prompts        │
│   内部实现：具体的业务逻辑                      │
└─────────────────────────────────────────────┘
```

- **Resource**：只读数据（类似 GET），如知识库文档、KG 节点、学生画像
- **Tool**：可执行动作（类似 POST），如生成文档、构建 KG、出题
- **Prompt**：预定义 prompt 模板
- **传输层**：stdio（本地进程）、SSE/HTTP（远程服务），本项目已有 SSE 基础

---

## 三、项目现有能力与 MCP 抽象的映射

将项目的 6 大能力映射到 MCP 抽象，可以规划出 6 个潜在的 MCP Server：

```
                          ┌──────────────────────┐
                          │  Personal Learning    │
                          │  Orchestrator         │
                          │  (现有 LangGraph)     │
                          └──────┬───────────────┘
                                 │ MCP Client
                                 │
        ┌────────────┬───────────┼───────────┬────────────┬────────────┐
        │            │           │           │            │            │
   ┌────▼────┐ ┌─────▼────┐ ┌───▼────┐ ┌───▼─────┐ ┌───▼─────┐ ┌───▼──────┐
   │  RAG    │ │   KG     │ │ Student│ │   LLM   │ │  Quiz   │ │ Document │
   │ Server  │ │  Server  │ │Profile │ │ Provider│ │ Server  │ │  Server  │
   │         │ │          │ │ Server │ │  Server │ │         │ │          │
   │Resource │ │Resource  │ │Resource│ │  Tool   │ │  Tool   │ │  Tool    │
   │+ Tool   │ │+ Tool    │ │+ Tool  │ │         │ │         │ │          │
   └─────────┘ └──────────┘ └────────┘ └─────────┘ └─────────┘ └──────────┘
```

### 映射详表

| 现有模块 | MCP Server | 核心 Resource | 核心 Tool |
|---------|-----------|--------------|----------|
| `backend/rag/` | **RAG Server** | `knowledge://search/{query}` — 语义检索文档 | `knowledge://index` — 索引新文档 |
| `backend/services/kg_builder.py` | **KG Server** | `kg://nodes` — 获取节点列表，`kg://paths/{kp_id}` — 获取学习路径 | `kg://build` — 从文档构建 KG |
| `backend/services/profile.py` | **Profile Server** | `profile://{user_id}` — 获取学生画像 | `profile://update` — 更新画像 |
| `backend/services/llm.py` | **LLM Provider Server** | — | `llm://chat` — 统一 LLM 调用，`llm://embed` — 获取 embedding |
| `backend/agents/quiz_agent.py` | **Quiz Server** | `quiz://questions/{resource_id}` — 获取题目 | `quiz://generate` — 生成题目，`quiz://submit` — 提交答案 |
| `backend/rag/loader.py` | **Document Server** | `docs://{doc_id}` — 获取文档内容 | `docs://import` — 导入文档，`docs://parse` — 解析文档 |

---

## 四、为什么值得落地？

### 4.1 当前架构的问题

```
# 当前：Agent 直接 import service，紧耦合
# doc_agent.py
from backend.rag.retriever import retrieve_by_kp      # 直接依赖
from backend.services.llm import chat_completion       # 直接依赖
from backend.services.profile import build_profile_context  # 直接依赖
```

每个 Agent 硬编码了对 3-5 个 service 的直接依赖。修改 service 接口 → 所有 Agent 都要改。想换 RAG 方案 → 要改每个 Agent。

### 4.2 MCP 化后的收益

**1. 组件解耦，独立演进**

```
# MCP 化后：Agent 只依赖 MCP Client，不关心 Server 实现
# doc_agent.py
rag_context = await mcp.read_resource("knowledge://search", {"query": kp_name})
response = await mcp.call_tool("llm://chat", {"messages": [...], "temperature": 0.7})
```

换 ChromaDB 为 Milvus/Pinecone？只改 RAG Server 内部，Agent 无感知。

**2. 跨项目复用**

RAG Server 封装好后，其他项目（如学校的课程推荐系统）可以直接通过 MCP 接入知识库搜索，不用复制代码。

**3. 多语言接入**

MCP 基于 JSON-RPC，前端 JS 也可以直接调用——比如在页面上做即时语义搜索而不走后端 API。

**4. 独立部署和伸缩**

每个 MCP Server 可以独立部署在不同机器上：
- LLM Provider Server 部署在 GPU 节点
- RAG Server 部署在内存大的节点（ChromaDB 需要大量内存）
- 其他 Server 部署在普通节点

**5. 与 Claude Desktop / AI IDE 的互操作**

封装好的 MCP Server 可以直接被 Claude Desktop、VS Code + Copilot 等工具消费。这意味着学生可以在 Claude Desktop 中直接检索课程资料、查询知识图谱。

---

## 五、分阶段落地方案

### 阶段 0：不落地（审慎决策的判断依据）

以下情况**不建议**落地 MCP：
- 团队只有 1-2 人，MCP 的抽象层会增加维护负担
- 项目确定不会拆分为微服务
- 没有其他系统需要接入本项目的能力
- 项目处于早期快速迭代阶段，紧耦合换开发速度是可接受的

如果满足上述条件，**保持现有架构是合理的**。MCP 不是银弹。

---

### 阶段 1：试点 — LLM Provider Server（最低风险）

**目标**：将 `backend/services/llm.py` 封装为 MCP Server，验证架构可行性。

**为什么先做这个**：
- LLM 调用是纯函数（输入 messages → 输出 text），最适合 MCP Tool 抽象
- 不涉及数据库、不改变现有数据流
- 改动范围最小——只需在 `llm.py` 外包装一层 MCP Server

**实现**（使用 `mcp` Python SDK）：

```python
# mcp_servers/llm_server.py
from mcp.server import Server
from mcp.types import Tool, TextContent
from backend.services.llm import chat_completion, stream_chat_completion

server = Server("llm-provider")

@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="chat_completion",
            description="调用大模型进行对话补全",
            inputSchema={
                "type": "object",
                "properties": {
                    "messages": {"type": "array"},
                    "temperature": {"type": "number", "default": 0.7},
                    "max_tokens": {"type": "integer", "default": 2048},
                    "provider": {
                        "type": "string",
                        "enum": ["qwen", "spark", "deepseek", "openai"],
                        "default": "qwen"
                    }
                },
                "required": ["messages"]
            }
        ),
        Tool(
            name="stream_chat_completion",
            description="流式对话补全",
            inputSchema={...}
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "chat_completion":
        result = await chat_completion(**arguments)
        return [TextContent(type="text", text=result)]
    # ...
```

Agent 侧改为：

```python
# doc_agent.py — MCP 化后
from backend.mcp_client import get_mcp_client

mcp = get_mcp_client("llm-provider")
response = await mcp.call_tool("chat_completion", {
    "messages": messages,
    "temperature": 0.7,
    "max_tokens": 4000,
})
```

**传输方式**：stdio（本地进程启动 MCP Server）或 SSE（已有基础）。

**周期**：约 3-5 天。

---

### 阶段 2：推广 — RAG Server + KG Server（核心价值）

**目标**：将检索和知识图谱封装为 MCP Server。

#### RAG Server

```python
# mcp_servers/rag_server.py
@server.list_resources()
async def list_resources():
    return [
        Resource(
            uri="knowledge://search/{query}",
            name="语义搜索知识库",
            description="在课程知识库中进行语义搜索",
            mimeType="application/json",
        )
    ]

@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="index_document",
            description="索引新文档到知识库",
            inputSchema={...}
        )
    ]

@server.read_resource()
async def read_resource(uri: str) -> list[TextContent]:
    # URI 格式: knowledge://search/注意力机制?n_results=5&threshold=0.5
    if uri.startswith("knowledge://search/"):
        query = extract_query(uri)
        results = await retrieve(query, **extract_params(uri))
        return [TextContent(type="text", text=format_context(results))]
```

#### KG Server

```python
# mcp_servers/kg_server.py
@server.list_resources()
async def list_resources():
    return [
        Resource(uri="kg://nodes", name="所有知识图谱节点"),
        Resource(uri="kg://nodes/{node_id}", name="特定节点详情"),
        Resource(uri="kg://paths/{kp_id}", name="获取学习路径"),
    ]

@server.list_tools()
async def list_tools():
    return [
        Tool(name="build_kg", description="从文档构建知识图谱"),
        Tool(name="infer_relations", description="推断节点间关系"),
    ]
```

**周期**：约 1-2 周。

---

### 阶段 3：生态 — 接入外部 MCP Server（扩展能力）

项目可以反过来作为 MCP Client，接入外部 MCP Server 来扩展能力：

```
本项目（MCP Client）
    ├── 自建 MCP Server（RAG / KG / Profile / LLM）
    └── 外部 MCP Server
        ├── Web Search（如 Brave Search MCP Server）
        ├── 文件系统（Filesystem MCP Server）
        ├── 数据库（SQLite / Postgres MCP Server）
        └── 第三方 API（GitHub / Arxiv / ...）
```

**收益**：
- 学生问"最新的 Transformer 变体有哪些"，Agent 可以通过 Web Search MCP Server 搜索最新论文
- 学生上传 PDF，通过 Filesystem MCP Server 读取
- 教师导入课程资源，通过 Database MCP Server 查询外部数据

这比现在写新的 Agent 或 service 来对接外部系统要快得多。

---

### 阶段 4：全量迁移 — Agent 全部走 MCP

**目标**：所有 Agent 通过 MCP Client 调用所有能力。

```
LangGraph Agent → MCP Client → [
    LLM Provider Server,
    RAG Server,
    KG Server,
    Profile Server,
    Quiz Server,
    Document Server,
    外部 MCP Server...,
]
```

**此时的架构**：

```
┌──────────────────────────────────────────────────┐
│                  LangGraph                        │
│                                                  │
│  profile_agent → planner_agent → {generators}    │
│       │               │              │           │
│       └───────────────┼──────────────┘           │
│                       │                          │
│               MCP Client (统一接入层)              │
└───────────────────────┼──────────────────────────┘
                        │ JSON-RPC
        ┌───────┬───────┼───────┬───────┬────────┐
        ▼       ▼       ▼       ▼       ▼        ▼
     RAG      KG     Profile   LLM    Quiz    Document
    Server   Server   Server  Server  Server   Server
```

**周期**：约 2-4 周。

---

## 六、风险与注意事项

### 6.1 增加延迟

当前 Agent 直接调用 Python 函数（微秒级），通过 MCP 后变为 JSON-RPC 调用（stdio 毫秒级，HTTP 数十毫秒级）。对于高频调用场景（如 LLM chat completion 本身已经 2-5 秒，MCP 开销占比较小），影响不大；但对于 RAG 检索（几百毫秒），增加几毫秒开销可接受。

**建议**：初期用 stdio 传输（同一进程内启动子进程），延迟最低。

### 6.2 增加复杂度

当前只需维护 1 个项目。MCP 化后变成 1 个编排项目 + 6 个 MCP Server 项目，总代码量和配置复杂度增加。

**建议**：先在同一个 repo 内以模块方式管理 MCP Server（`mcp_servers/` 目录），不拆 repo。等到某个 Server 需要独立部署时再拆分。

### 6.3 MCP SDK 成熟度

MCP Python SDK 仍在快速迭代，API 可能有 breaking change。

**建议**：固定 SDK 版本，关注 changelog；核心业务逻辑与 MCP 包装层分离，确保 MCP API 变化时只改包装层。

### 6.4 调试难度

直接函数调用的调用栈清晰易调试。MCP 调用涉及序列化/反序列化/网络传输，调试更复杂。

**建议**：在 MCP Client 层做统一的日志和 tracing；保留直接调用的 fallback 路径。

---

## 七、决策建议

| 条件 | 建议 |
|------|------|
| 项目是比赛/课程作品，1-2 人团队 | **不落地**。MCP 带来的抽象收益不足以抵消增加复杂度 |
| 项目计划长期维护，有 3+ 人团队 | **做阶段 1-2**。LLM Provider Server + RAG Server 实用价值最大 |
| 需要与其他系统互操作 | **做阶段 3**。MCP Client 模式让项目快速获得新能力 |
| 考虑微服务化部署 | **做阶段 4**。MCP 天然适合微服务架构 |
| 想在简历/面试中展示 MCP 实践 | **做阶段 1**。LLM Provider Server 改动最小、最安全、效果最直观 |

---

## 八、快速实验方案（1 天内可完成）

如果要快速验证 MCP 的价值，推荐最小可行实验：

**只做一件事**：把 `backend/rag/retriever.py` 的 `retrieve()` 函数包装为 MCP Server。

- 新建 1 个文件：`mcp_servers/rag_server.py`（~50 行）
- 修改 1 个 Agent 的检索调用：`doc_agent.py` 改为通过 MCP Client 调用（~5 行改动）
- 对比前后效果：延迟差异、代码解耦程度

如果这个实验效果好，再决定是否推进其他阶段。
