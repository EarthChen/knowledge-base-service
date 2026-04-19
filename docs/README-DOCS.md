# Documentation index

**Knowledge Base Service** — FastAPI backend, FalkorDB graph storage, Tree-sitter indexing, ONNX/torch embeddings (BAAI/bge-m3), hybrid retrieval with RRF and optional reranking, React + Vite dashboard, and MCP-style HTTP tools for agents.

## Guides

| Document | Contents |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | End-to-end architecture, indexing and retrieval pipelines, graph schema, dashboard |
| [MCP-INTEGRATION.md](MCP-INTEGRATION.md) | Complete MCP tool reference (16 tools), roles, HTTP binding |
| [DEPLOYMENT.md](DEPLOYMENT.md) | Prerequisites, full env var table, auth, rate limits, Docker, security |
| [DEVELOPMENT.md](DEVELOPMENT.md) | Directory layout, `uv` / `pnpm`, tests, adding languages and MCP tools |
| [ONBOARDING.md](ONBOARDING.md) | Product tour, first index, search tips, MCP setup |
| [wiki-generation-architecture.md](wiki-generation-architecture.md) | Wiki generation stack, search, webhooks, scheduler |

## Tech stack summary

| Layer | Components |
|-------|----------------|
| API | FastAPI, structured logging, rate-limit middleware |
| Storage | FalkorDB (RedisGraph-compatible), vector indexes per label |
| Parsing | tree-sitter, language pack (python, java, go, javascript, typescript) |
| Embeddings | Transformers / ONNX runtime, default bge-m3 1024-dim |
| Search | Keyword + vector + (optional) chunk search → weighted RRF → optional bge-reranker → per-file cap → graph expansion |
| UI | React 19, Vite, TanStack Query, React Router, Mermaid, xyflow |
| Auth | YAML or env tokens; roles VIEWER / EDITOR / ADMIN |

The [root README](../README.md) has a short quick start and configuration overview.
