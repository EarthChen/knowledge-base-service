# 文档索引（README-DOCS）

本文档为 **`docs/` 目录下的文档导航入口**：一页看清有哪些说明文件、各自覆盖范围，以及如何与仓库根目录 [`README.md`](../README.md) 配合使用。

---

## 项目概要（一段话）

**Knowledge Base Service** 是一套面向代码仓库的**独立知识库服务**：将多语言源码与配置文件索引进 **FalkorDB** 属性图与稠密向量空间（默认 **BAAI/bge-m3**），在服务端通过 **RRF 混合检索**、可选重排序与图扩展回答「代码在哪、谁调用谁、变更影响多大」类问题；在此基础上提供完整的 **Wiki 生成 / 检索 / 质量检测 / 记忆与反馈 / 深度研究** 流水线，以及面向人机协同的 **React + Vite 仪表盘**。对外契约包括 **FastAPI HTTP API**、与 Agent 工具生态对齐的 **主 MCP 清单（22 工具：12 核心图谱/RAG + 10 Wiki）**，以及在启用 **`WIKI__MCP_SERVER_ENABLED`** 时可挂载的 **Wiki 专用 HTTP MCP（6 工具）**。架构上逐步收敛到 **`AppContainer` 依赖注入** 与 **`@mcp_tool` 自动注册**，便于测试与演进。

---

## 文档导航（全表）

下列表格列出当前 `docs/` 下的主要 Markdown 文档及其用途（路径相对于 `docs/`）。

| 文档 | 说明 |
|------|------|
| [`README-DOCS.md`](README-DOCS.md) | **本文**：文档总索引、技术栈一页表、审计类文档入口；指向根 [`README.md`](../README.md)。 |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | **系统架构**：端到端数据流、索引与检索栈、Wiki 子系统（质量、记忆、矛盾、MCP 边界）、与前端的协作关系。 |
| [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md) | **实现 vs 规划**：阶段勾选、API 路径差异说明（例如矛盾检测路由）、AutoHealer 等能力与文档交叉引用；排查「文档写了但开关未开」的首选。 |
| [`CODEMAPS/INDEX.md`](CODEMAPS/INDEX.md) | **代码地图**：`main.py`、路由聚合、`mcp_server`/`mcp_wiki_server`、仪表盘入口、`store/`/`wiki/`/`indexer/`/`query/`/`llm/` 树状导读与 Wiki 聚焦表。 |
| [`MCP-INTEGRATION.md`](MCP-INTEGRATION.md) | **MCP 集成手册**：主 MCP 与 Wiki HTTP MCP 的 URL、请求体字段差异（`tool_name` vs `name`）、22+6 工具参数级说明、角色与错误码。 |
| [`DEPLOYMENT.md`](DEPLOYMENT.md) | **部署与运维**：前置条件、`WIKI__*` 等功能开关、认证与限流、Docker、安全与生产注意事项。 |
| [`DEVELOPMENT.md`](DEVELOPMENT.md) | **开发者指南**：仓库目录、`uv`/`pnpm`、测试命令、扩展语言与 MCP、本地调试惯例。 |
| [`ONBOARDING.md`](ONBOARDING.md) | **产品与上手**：功能地图、首次索引、仪表盘与 MCP 客户端配置心智模型。 |
| [`wiki-generation-architecture.md`](wiki-generation-architecture.md) | **Wiki 生成架构**：管道阶段、增量 Ingest、LLM Wiki v2（置信度、矛盾、主张、记忆层）、与异步任务/新鲜度 API 的关系。 |
| ~~[`KNOWN-ISSUES.md`](KNOWN-ISSUES.md)~~ | 已合并至 `specs/2026-05-12-agent-wiki-quality-and-tree-fix.md` §3，文件已删除。 |
| [`REMAINING-WORK.md`](REMAINING-WORK.md) | **统一剩余工作清单**：引用 `specs/2026-05-12-agent-wiki-quality-and-tree-fix.md` 作为唯一活跃提案。 |

---

## 审计与分析

下列材料偏**复盘、差距分析与架构决策记录**，篇幅较长，适合评审或规划会议使用。

| 文档 | 说明 |
|------|------|
| ~~`superpowers/DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md`~~ | (已完成并移除) 2026-05-02 全仓库代码审计 + 竞品对标 — B-01~B-17/F-01~F-07 全部已修复，遗留功能缺口 B-19~B-22/F-04 已迁移至 `REMAINING-WORK.md`。 |
| [`superpowers/specs/2026-05-02-architecture-refactor-design.md`](superpowers/specs/2026-05-02-architecture-refactor-design.md) | **架构重构设计**：DI 容器、`@mcp_tool` 注册策略、`lifespan` 分段与关停顺序等。 |
| [`superpowers/plans/2026-05-02-architecture-refactor.md`](superpowers/plans/2026-05-02-architecture-refactor.md) | **架构重构实施计划**：分 Task/Phase 的落地顺序与验收线索。 |
| ~~`specs/2026-05-09-graph-driven-deterministic-decomposition.md`~~ | (已实现并移除) CodeWiki 图驱动确定性分解 — 设计要点已固化至 `wiki/graph_module_decomposer.py`、`wiki/pipeline_graph.py`。 |
| ~~`specs/2026-05-09-codewiki-aligned-pipeline-design.md`~~ | (已实现并移除) CodeWiki 对齐管线重设计 — 设计要点已固化至 `wiki/harness.py`、`wiki/harness_evaluator.py`、`wiki/page_agent.py`。 |
| ~~`specs/2026-05-11-graph-decomposition-and-imports-fix-design.md`~~ | (已实现并移除) 图分解优化与 IMPORTS 边修复 — 设计要点已固化至 `indexer/code_graph_builder.py`、`store/falkordb_reads.py`、`wiki/graph_module_decomposer.py`。 |
| ~~`specs/2026-05-11-agent-driven-business-wiki-design.md`~~ | (已实现并移除) Agent 驱动的业务 Wiki 生成（Phase 0-4 ✅）— 架构设计已固化至 `wiki/domain_doc_agent.py`、`wiki/nodes/domain_compose.py`、`wiki/pipeline_graph.py`、`wiki/agent_prompts.py`；遗留项已迁移至下方统一提案。 |
| ~~`specs/2026-05-11-incremental-wiki-update-design.md`~~ | (已实现并移除) 增量 Wiki 更新设计 — 设计要点已固化至 `wiki/incremental_diff.py`、`wiki/nodes/domain_compose.py`、`wiki/pipeline_orchestrator.py`。 |
| [`specs/2026-05-12-agent-wiki-quality-and-tree-fix.md`](superpowers/specs/2026-05-12-agent-wiki-quality-and-tree-fix.md) | **唯一活跃统一提案**：Task A-D ✅（路径/质量门/内容/Robustness）；Task F Explore/Write 核心 ✅（优化项 P3）；**Task G 域分类准确度（P1）**；**Task H 域调整机制（P1）**；Task E L2 业务流（P3）。 |

---

## 技术栈概览

| 层级 | 组件与说明 |
|------|------------|
| **API** | **FastAPI**；**structlog** 日志；**限流**中间件（`rate_limiter.py`）；Wiki 扩展路由前缀 `/api/v1/wiki/*`；主 MCP `/api/v1/mcp/tools` + `/api/v1/mcp/tool`；可选 Wiki HTTP MCP `/api/v1/mcp/tools/list` + `/api/v1/mcp/tools/call`。 |
| **存储** | **FalkorDB**（Redis 生态图模型）；向量相似度检索与业务/多租户图隔离策略；Wiki 变更日志、反馈、Q&A、矛盾/主张等子图模型由 `store/wiki_*` 等模块封装。 |
| **解析** | **Tree-sitter** 与语言 grammar 包（Python、Java、Go、JavaScript、TypeScript、**Kotlin**、**Swift**、**Objective-C**、**Dart**，可按插件扩展）。 |
| **嵌入** | **Transformers / ONNX Runtime**；默认 **bge-m3**（1024 维）；可选 torch 路径视部署而定。 |
| **搜索** | 关键词 + 向量 +（可选）子块/BM25 → **加权 RRF** → 可选 **交叉编码器重排序** → 单文件命中上限 → **图扩展**；Wiki 内部亦有混合检索实现（`wiki/search.py` + `query/hybrid_query.py`）。 |
| **Wiki / Agent** | **LangGraph** 编排 Wiki 管线；**OpenAI 兼容**网关适配（`llm/base_provider.py`）；SSE 类响应用于 Ask/流式场景。 |
| **前端** | **React 19**、**Vite**、**TanStack Query**、**React Router**；**Mermaid**；**xyflow** 用于业务流/图谱可视化；编辑器与图表库见根 [`README.md`](../README.md) 技术栈表。 |
| **认证** | YAML / 环境变量 Token；角色 **VIEWER / EDITOR / ADMIN**；部分 MCP 工具（如 `wiki_export`）要求 **EDITOR** 及以上。 |

---

## 根 README

安装、一键启动、环境变量速查与功能全景仍以仓库根目录 **[`README.md`](../README.md)** 为准；`docs/` 侧重架构、运维与纵向专题。
