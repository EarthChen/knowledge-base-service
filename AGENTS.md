# AGENTS.md — Knowledge Base Service

Essential context for AI coding agents. Detailed docs live in `docs/`.

---

## Project Summary

**Knowledge Base Service** is a code-intelligence platform that indexes multi-language repositories into a property graph + vector space (FalkorDB), enables hybrid search (keyword + BM25 + semantic → RRF fusion → rerank → graph expansion), and generates LLM-driven Markdown wiki documentation with quality gates, memory tiers, and automated healing.

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.12+, FastAPI, Uvicorn, Pydantic Settings, structlog |
| **Storage** | FalkorDB (graph + vector indexes), Redis (tasks/locks), SQLite (checkpoints/conversations) |
| **Indexing** | Tree-sitter (8 languages), ONNX/Torch embeddings (bge-m3, 1024-dim) |
| **Search** | 3-way RRF fusion, optional cross-encoder reranking, graph expansion |
| **Wiki/Agent** | LangGraph pipeline, OpenAI-compatible LLM, iterative RAG, agent tool loops |
| **Frontend** | React 19, Vite 8, TypeScript 5.9, Tailwind CSS 4, TanStack Query 5, React Router 7 |
| **Graph Viz** | @xyflow/react + dagre |
| **Testing** | pytest + pytest-asyncio + pytest-xdist (-n auto), Vitest + Playwright |

---

## Development Commands

### Backend

```bash
uv sync --extra dev --group dev          # Install dependencies
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8100  # Run server
uv run pytest                            # Full suite (~3865 tests, -n auto)
uv run pytest tests/wiki/agents/ -x      # Specific module
uv run pytest -k "test_runner" -x        # By keyword
uv run ruff check .                      # Lint
uv run ruff format .                     # Format
```

### Frontend

```bash
cd dashboard
pnpm install
pnpm dev              # http://localhost:5173 (proxy /api → :8100)
pnpm build            # → ../static/
pnpm test             # Vitest
pnpm test:e2e         # Playwright
pnpm lint             # ESLint
```

---

## Key Conventions

### Python
- **Package manager:** `uv` only (never pip/conda/poetry)
- **Format/Lint:** Ruff, target py312, line-width 120, rules E,F,I,N,W,UP
- **Type hints:** `from __future__ import annotations` at module level
- **Logging:** `structlog` via `from core.log import get_logger`; structured key-value fields
- **Async:** `asyncio_mode = auto` in pytest; heavy use of `AsyncMock`
- **DI:** `AppContainer` (core/container.py) holds singletons; FastAPI `Depends` for routes

### Frontend
- **Package manager:** `pnpm` only (never npm/yarn)
- **State:** TanStack Query for server state; no Redux/Zustand
- **Styling:** Tailwind CSS utility classes; no CSS modules or styled-components
- **API calls:** Custom `api()` fetch wrapper in `api/client.ts`; never raw fetch in components
- **i18n:** Custom context (en/zh), not i18next
- **Icons:** lucide-react exclusively

### Testing
- Backend: pytest-asyncio, pytest-xdist (-n auto), mock FalkorDB with MagicMock/AsyncMock
- Frontend: Vitest + Testing Library + MSW for API mocks
- Coverage: Backend ≥75%, Frontend lines ≥70%

---

## File Navigation Tips

- **Entry point:** `main.py` → `create_app()` → `lifespan`
- **Config:** `core/config.py` (Settings, AppWikiFlags with 50+ flags)
- **DI container:** `core/container.py` (AppContainer)
- **API routes:** `api/routes/` (26 route modules)
- **MCP tools:** `api/mcp_server.py` (22 core) + `api/mcp_wiki_server.py` (6 optional wiki)
- **Agent framework:** `wiki/agents/` (25+ files: GenericAgent, run_agent_loop, @function_tool, guardrails, tracing, token_budget, context_compactor, delegation, review_agent, citation_verifier, memory_promotion)
- **Main agent:** `wiki/page_agent.py` (WikiPageAgent — 15 @function_tool methods)
- **Wiki pipeline:** `wiki/pipeline_graph.py` (LangGraph StateGraph definition)
- **Pipeline nodes:** `wiki/nodes/` (17 files: classify, compose, heal, quality_gate, tour, finalize, etc.)
- **Pipeline concurrency:** `wiki/pipeline_concurrency.py` (PipelineConcurrency — unified semaphore management)
- **Graph schema:** `store/schema.py` (NodeLabel, EdgeType, VECTOR_INDEX_CONFIGS)
- **Indexer languages:** `indexer/languages/` (11 files: python, java, go, js, ts, kotlin, swift, objc, dart)
- **Frontend entry:** `dashboard/src/main.tsx` → `App.tsx` (12 lazy-loaded pages)
- **Frontend API:** `dashboard/src/api/client.ts` + `hooks.ts`
- **Frontend hooks:** `dashboard/src/hooks/` (58 files: wiki, settings, search, streaming)
- **Wiki components:** `dashboard/src/components/wiki/` (~70 components)
- **Tests:** Mirror source structure under `tests/` (658 test files)

---

## Documentation Map

| Document | Scope |
|----------|-------|
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | System architecture, data flow, architecture decisions |
| [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md) | Full directory structure, dev setup, testing, extension guide, AI agent tasks |
| [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) | Environment variables, Docker, auth, production config |
| [`docs/MCP-INTEGRATION.md`](docs/MCP-INTEGRATION.md) | MCP tool parameter reference (22+6 tools) |
| [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | Product overview, first-run guide |
| [`docs/wiki-generation-architecture.md`](docs/wiki-generation-architecture.md) | Wiki pipeline nodes, agent framework, quality gates |
| [`docs/CODEMAPS/INDEX.md`](docs/CODEMAPS/INDEX.md) | Code map: entry points, module tree, wiki subsystem |
| [`docs/REMAINING-WORK.md`](docs/REMAINING-WORK.md) | Unified backlog |
| [`docs/superpowers/TODO.md`](docs/superpowers/TODO.md) | Design proposals & optimization backlog |
| [`docs/wiki-quality-audit.md`](docs/wiki-quality-audit.md) | Wiki generation quality audit (12 issues, fix priorities) |
| [`docs/knowledge-base-system-analysis.md`](docs/knowledge-base-system-analysis.md) | Full system analysis: multi-role perspectives, competitor comparison, roadmap |
