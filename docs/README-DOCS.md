# 知识库文档索引（Bootloader）

本页是 **文档入口与导航**，并记录 **P2（跨服务智能）及 G1–G6 扩展** 的实现状态。实现细节以代码与 [MCP 集成指南](MCP-INTEGRATION.md) 为准。

## P2 实现状态

| 阶段 | 状态 | 说明 |
|------|------|------|
| P2 提案（跨仓库 RPC、PR 审查、Smart Context、实体表、Spring DI） | ✅ 已完成 | 见 [PROPOSAL_20260416_174915_p2_cross_service_intelligence.md](proposals/PROPOSAL_20260416_174915_p2_cross_service_intelligence.md) |
| G1–G6 增量能力 | ✅ 已完成 | 解析与图增强、API/MCP、Dashboard P2、批量重索引等（见下表） |

### G1–G6 能力摘要

| 组别 | 内容 |
|------|------|
| **G1 解析** | Java 字段级注解（`ParsedField`）、构造器注入（DI 字段伪 Function 节点）、类节点上的泛型形参、`code_snippet` 截断策略优化 |
| **G2 图** | RPC 接口合约（Class 上 `is_rpc_contract`、`contract_methods`）、域事件（`EVENT_PRODUCES` / `EVENT_CONSUMES` 连到 Kafka Topic Module）、SmartContext 含 `rpc_interface_contracts` 与 `event_context` |
| **G3 API/MCP** | `GET /api/v1/search/architecture`（支持 `offset` / `search` 分页与类名过滤）、`GET /api/v1/quality/{entity_uid}`、MCP `search_architecture` / `code_quality`、索引完成后自动跨仓库富集；Dashboard **Architecture Explorer**（`/architecture`）按层浏览类与方法 |
| **G4 PR 审查** | `POST /api/v1/review/context` 支持 `branch` + `repo_path` 本地 `git diff`；MCP `review_pr` 同步 `branch` / `repo_path` / `base_branch` |
| **G5 Dashboard P2** | `GET /api/v1/stats/p2`、MCP `dashboard_stats` |
| **G6 批量重索引** | `POST /api/v1/reindex/all`、`scripts/reindex_all.py` |

## 架构（更新要点）

在 [主 README 架构图](../README.md#架构) 的基础上，当前实现还强调：

- **索引解析**：Tree-sitter + Java 注解语义；字段级结构；构造器注入边；类泛型元数据。
- **图富集**：`GraphEnricher`（端点、架构层、RPC 合约、Kafka 事件边等）；`CrossRepoEnricher`（跨仓库 RPC、DI `DEPENDS_ON`、实体表 `ACCESSES_TABLE`）；索引任务结束可自动触发跨仓库富集。
- **查询与 Agent**：`GraphQueryService`、`HybridQueryService`、`AgentWorkflowService`（PR 上下文、质量分、Smart Context）；`query/endpoint_queries.py` 等与 REST/MCP 共用。
- **对外接口**：FastAPI `viewer` / `editor` / `admin` 路由；MCP HTTP 适配（12 个工具）；可选 ACP Gateway 代理。

## 文档地图

| 文档 | 用途 |
|------|------|
| [MCP-INTEGRATION.md](MCP-INTEGRATION.md) | MCP 工具（12 个）、HTTP 调用、Cursor 配置、权限与推荐工作流 |
| [ONBOARDING.md](ONBOARDING.md) | 新成员上手与服务约定 |
| [../README.md](../README.md) | 服务总览、索引管道、API 与部署 |
| [proposals/](proposals/) | 能力提案与阶段记录（P1/P2 等） |
| [dashboard/README.md](../dashboard/README.md) | 前端 Dashboard |
