# 文档索引

**Knowledge Base Service** — FastAPI 后端、FalkorDB 图存储、Tree-sitter 索引、ONNX/torch 嵌入（BAAI/bge-m3）、RRF 混合检索与可选重排序、React + Vite 仪表盘，以及面向 Agent 的 MCP 风格 HTTP 工具。

## 文档导航

| 文档 | 内容 |
|------|------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | 端到端架构、索引与检索管道、图 Schema、仪表盘 |
| [MCP-INTEGRATION.md](MCP-INTEGRATION.md) | 完整 MCP 工具参考（15 个查询工具）、角色、HTTP 绑定 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 前置条件、完整环境变量表、认证、限流、Docker、安全 |
| [DEVELOPMENT.md](DEVELOPMENT.md) | 目录结构、`uv` / `pnpm`、测试、新增语言与 MCP 工具 |
| [ONBOARDING.md](ONBOARDING.md) | 产品导览、首次索引、搜索技巧、MCP 设置 |
| [wiki-generation-architecture.md](wiki-generation-architecture.md) | Wiki 生成栈、Phase 0–6 扩展、搜索、Webhook、定时器 |
| [superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md) | LLM Wiki 全面升级设计（SP1-SP6：架构加固、增量 Ingest、Agent/MCP、质量闭环、知识编译） |

## 技术栈概览

| 层级 | 组件 |
|------|------|
| API | FastAPI、结构化日志、限流中间件 |
| 存储 | FalkorDB（RedisGraph 兼容）、按标签向量索引 |
| 解析 | Tree-sitter，语言包（Python、Java、Go、JavaScript、TypeScript） |
| 嵌入 | Transformers / ONNX Runtime，默认 bge-m3 1024 维 |
| 搜索 | 关键词 + 向量 +（可选）子块搜索 → 加权 RRF → 可选 bge-reranker → 每文件上限 → 图扩展 |
| 前端 | React 19、Vite、TanStack Query、React Router、Mermaid、xyflow |
| 认证 | YAML 或环境变量 Token；角色 VIEWER / EDITOR / ADMIN |

[根目录 README](../README.md) 包含快速开始和配置概览。
