# Wiki 生成架构

本文档描述**生成式 Wiki 页面**如何融入 Knowledge Base Service：从**索引代码图**和**嵌入**中获取输入，经过**组合管道**，自动化（Webhook、调度器），以及**混合 Wiki 搜索**与产品其他部分的关系。

## 目标

- 将**索引属性图**（Tree-sitter → FalkorDB + 向量）转化为 **Markdown**（适当时包含 **Mermaid** 图表）和**稳定的源码位置交叉链接**。
- 支持**增量再生成**、多种 **LLM 后端**（OpenAI 兼容），以及**仪表盘**浏览。
- 暴露 **MCP 工具**（`get_wiki_page`、`list_wiki_pages`、`search_wiki`、`wiki_export`）与 HTTP Wiki 路由并行提供。

## 分层管道

```mermaid
flowchart TB
  subgraph ingest [已索引知识]
    G[FalkorDB 图]
    V[嵌入向量]
  end

  subgraph compose [Wiki 组合]
    SP[结构规划器]
    DC[数据收集器]
    WC[组合器 + 图表生成]
    RC[仓库级组合器 增量]
  end

  subgraph automate [自动化]
    WH[Webhook github/gitlab/gitea]
    PD[Push 防抖器]
    WS[Wiki 调度器]
    TL[任务锁 互斥]
  end

  subgraph out [输出]
    EX[导出器 / 磁盘]
    CACHE[持久化缓存]
    API[wiki_routes REST SSE]
    UI[仪表盘 Wiki 页面]
  end

  G --> SP --> DC --> WC --> EX
  RC --> WC
  V --> DC
  ingest --> compose
  EX --> CACHE --> API --> UI
  WH --> PD --> TL
  WS --> TL
```

Wiki 行为的功能开关位于 `config.py` 的 **`WIKI__*`**（`WikiConfig`）。LLM 路由使用 `LLMProviderFactory` 和 OpenAI 兼容的 **LLM__** 配置。

## Wiki 混合搜索

Wiki 搜索结合**图上下文**、**向量相似性**和**全文**信号，然后在 `wiki/search.py` 中应用 **RRF 风格融合**（与主产品的融合模式一致）。**Ask** 模式复用检索并可通过 **SSE** 流式输出。

```mermaid
sequenceDiagram
  participant C as 客户端
  participant S as WikiSearchService
  participant G as FalkorDB
  participant Vec as 嵌入路径
  participant FTS as 全文路径

  C->>S: POST /wiki/search
  par 并行检索
    S->>G: 结构化 / 邻域扩展
    S->>Vec: 向量相似
    S->>FTS: 关键词命中
  end
  S->>S: 融合 + 排序
  S->>C: 片段 + 元数据
```

### HTTP 搜索入口

旧版 **`POST /search`** 和 **`POST /business/search`** 已移除，统一使用 **`POST /api/v1/hybrid`** 并通过 `entity_type` 查询业务实体。在 **MCP** 侧，使用 **`rag_query`** 配合 `entity_type` 设为 `flow` 或 `concept` 替代已移除的业务专用工具。

可选 LLM 索引功能（**概念提取**、**业务流推断**）在 `LLMConfig` 中默认**关闭**；需要时显式启用。

## 自动化（Webhook 和定时计划）

- **Webhook**：`api/routes/webhook_routes.py`，路径 `/api/v1/hooks/{provider}`，包含签名验证和推送防抖处理。
- **调度器**：`wiki/scheduler/` 协调定期再生成，与 **`TaskLock`** 协作确保 Webhook 触发和定时任务不会并发损坏同一导出。

## 相关模块

| 关注点 | 位置 |
|--------|------|
| 模型 / 作用域 | `wiki/models.py`、`wiki/context.py` |
| 规划 / 组合 | `wiki/structure_planner.py`、`wiki/data_collector.py`、`wiki/composer.py`、`wiki/diagram_gen.py` |
| 仓库级 / 增量 | `wiki/repo_composer.py`、`wiki/incremental.py`、`wiki/disk_exporter.py`、`wiki/persistent_cache.py` |
| 搜索 / 问答 | `wiki/search.py`、`wiki/ask.py` |
| MCP Wiki 接口 | `wiki/mcp_tools.py`（清单在 `api/mcp_server.py` 中合并） |
| HTTP 路由 | `api/routes/wiki_routes.py`、`api/routes/provider_routes.py` |
| 仪表盘 | `dashboard/src/pages/`（Wiki 相关视图） |

## MCP 工具（Wiki）

四个 Wiki 工具注册在 **`WIKI_MCP_TOOLS_MANIFEST`** 中：**`get_wiki_page`**、**`list_wiki_pages`**、**`search_wiki`**、**`wiki_export`**。HTTP 组合目录通过 **`GET /api/v1/mcp/tools`** 获取 — 以此为工具名称和 Schema 的权威来源。**`wiki_export`** 至少需要 **Editor** 角色。

跨功能分析工具中结合 Wiki 与变更影响分析的，参见 **`analyze_changes`** 的 `impact_scope` 和 `wiki_pr_impact` 模式，详见 [MCP-INTEGRATION.md](MCP-INTEGRATION.md)。
