# 文档索引

**Knowledge Base Service** — FastAPI 后端、FalkorDB 图存储、Tree-sitter 索引、ONNX/torch 嵌入（BAAI/bge-m3）、RRF 混合检索与可选重排序、React + Vite 仪表盘。Wiki 侧支持**增量 Ingest**、**质量与矛盾检测**、**记忆分层与遗忘曲线**、**用户反馈与深度研究**、**业务流图（xyflow）**；面向 Agent 的能力包括**主服务 MCP 清单（图谱 + Wiki 管线）**与可选的**独立 Wiki MCP 五工具**（`WIKI__MCP_SERVER_ENABLED`）。

## 文档导航

| 文档 | 内容 |
|------|------|
| [IMPLEMENTATION-STATUS.md](IMPLEMENTATION-STATUS.md) | **实现与规划对照**（双套 SP 编号说明、矛盾 API 路径、AutoHealer 现状、缺失独立 spec 的替代引用） |
| [CODEMAPS/INDEX.md](CODEMAPS/INDEX.md) | 代码入口与 Wiki 相关目录速查 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 端到端架构、索引与检索、Wiki 子系统（质量引擎、记忆演化、MCP） |
| [MCP-INTEGRATION.md](MCP-INTEGRATION.md) | 主 MCP 工具（20 个：12 核心 + 8 Wiki）与可选 Wiki MCP HTTP（6 个）、角色、HTTP 绑定 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 前置条件、`WIKI__*` 等功能开关、认证、限流、Docker、安全 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 目录结构、`uv` / `pnpm`、测试、新增语言与扩展 MCP |
| [ONBOARDING.md](ONBOARDING.md) | 产品导览、功能发现、首次索引、MCP 设置 |
| [wiki-generation-architecture.md](wiki-generation-architecture.md) | Wiki 管道、Ingest/自动化、LLM Wiki v2（置信度/矛盾/主张/记忆层） |
| [superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md) | **已批准** LLM Wiki v2（三阶段、**SP1–SP7**，与下一条的 SP 含义不同） |
| [superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md) | 草案：LLM Wiki 全面升级路线图（**SP1–SP6**）；`superpowers/plans/*-spN-*` 计划文件沿用此套编号 |
| [superpowers/specs/2026-04-27-phase0-knowledge-maintenance-loop-design.md](superpowers/specs/2026-04-27-phase0-knowledge-maintenance-loop-design.md) | **Phase 0** — 知识维护闭环修复：接入 AutoHealer + 启用 Lint 调度（立即可做） |
| [superpowers/specs/2026-04-27-phase1-knowledge-compilation-feedback-design.md](superpowers/specs/2026-04-27-phase1-knowledge-compilation-feedback-design.md) | **Phase 1** — 知识编译快照 + AGENTS.md 增强 + 反馈驱动再生成闭环（短期） |
| [superpowers/specs/2026-04-27-phase2-graph-community-wiki-editing-design.md](superpowers/specs/2026-04-27-phase2-graph-community-wiki-editing-design.md) | **Phase 2** — 图社区驱动 Wiki 组织 + 路径检索 + Wiki 内置编辑（中期） |
| [superpowers/specs/2026-04-27-phase3-reasoning-visualization-multiview-design.md](superpowers/specs/2026-04-27-phase3-reasoning-visualization-multiview-design.md) | **Phase 3** — 推理路径可视化 + 多视图 Wiki + 离线访问（长期） |

## 技术栈概览

| 层级 | 组件 |
|------|------|
| API | FastAPI、结构化日志、限流中间件；Wiki 扩展路由（`/api/v1/wiki/*`）、可选 Wiki MCP（`/api/v1/mcp/tools/list`、`/api/v1/mcp/tools/call`） |
| 存储 | FalkorDB（RedisGraph 兼容）、按标签向量索引；Wiki 变更日志、反馈、Q&A 记忆、矛盾/主张等图模型 |
| 解析 | Tree-sitter，语言包（Python、Java、Go、JavaScript、TypeScript） |
| 嵌入 | Transformers / ONNX Runtime，默认 bge-m3 1024 维 |
| 搜索 | 关键词 + 向量 +（可选）子块 → 加权 RRF → 可选 bge-reranker → 每文件上限 → 图扩展；Wiki 内混合搜索与全局搜索 |
| 前端 | React 19、Vite、TanStack Query、React Router、Mermaid、**xyflow**（业务流可视化） |
| 认证 | YAML 或环境变量 Token；角色 VIEWER / EDITOR / ADMIN |

[根目录 README](../README.md) 包含快速开始和配置概览。
