# AGENTS.md — Knowledge Base Service

This file provides AI coding agents with essential context about the project.

---

## Project Summary

**Knowledge Base Service** is a code-intelligence platform that indexes multi-language repositories into a property graph + vector space (FalkorDB), enables hybrid search (keyword + BM25 + semantic → RRF fusion → rerank → graph expansion), and generates LLM-driven Markdown wiki documentation with quality gates, memory tiers, and automated healing.

**Key capabilities:** Code graph indexing, hybrid retrieval, wiki generation pipeline (LangGraph), AI agent tool loops, MCP tool exposure (22 core + 6 optional wiki), React dashboard.

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

## Directory Structure

```
knowledge-base-service/
├── main.py                    # FastAPI app factory, lifespan (init → shutdown)
├── core/
│   ├── container.py           # AppContainer — DI holder for all singletons
│   ├── config.py              # Settings (pydantic-settings, 50+ wiki flags)
│   ├── auth.py                # Token registry, Role (VIEWER/EDITOR/ADMIN), require_role()
│   ├── log.py                 # structlog setup
│   ├── redis_resilience.py    # Redis BusyLoadingError retry decorator
│   └── startup/               # Phased init: security → core_services → wiki_and_lint
├── api/
│   ├── routes/                # ~15 route modules (search, wiki_*, indexing, business, etc.)
│   ├── mcp_server.py          # Main MCP handler (22 tools via @mcp_tool + collect_tools)
│   ├── mcp_wiki_server.py     # Optional Wiki HTTP MCP (6 tools)
│   ├── mcp_registry.py        # @mcp_tool decorator, collect_tools()
│   ├── rate_limiter.py        # IP token-bucket rate limiting
│   └── kb_state.py            # AppContainer compat layer for legacy imports
├── wiki/
│   ├── service.py             # WikiService — main orchestrator (generation, incremental, export)
│   ├── agents/                # ** Agent framework package **
│   │   ├── base_agent.py      # GenericAgent, ToolRegistry, ToolDef, RunConfig
│   │   ├── runner.py          # run_agent_loop(), LoopConfig, LoopHooks, AgentLoopResult
│   │   ├── agent_tool.py      # agent_tool() factory — wrap agent as ToolDef
│   │   ├── context.py         # RunContext, WikiDeps (typed DI per run)
│   │   ├── guardrails.py      # InputGuardrail, OutputGuardrail, PromptLengthGuardrail
│   │   ├── tool_decorator.py  # @function_tool — auto-register from signatures
│   │   ├── tracing.py         # AgentTracer, Span, JsonlTraceProcessor
│   │   ├── handoff.py         # HandoffConfig, execute_handoff()
│   │   ├── memory.py          # Memory base class
│   │   ├── events.py          # ToolCallEvent, ContentEvent, DoneEvent, etc.
│   │   ├── edit_agent.py      # WikiEditAgent (section-based edits)
│   │   ├── doc_orchestrator.py     # DocOrchestrator (template method: explore→write→verify)
│   │   ├── topic_doc_agent.py      # TopicDocAgent
│   │   ├── flow_doc_agent.py       # FlowDocAgent
│   │   ├── ask_orchestrator.py     # AskOrchestrator (explore → answer)
│   │   ├── research_orchestrator.py # ResearchOrchestrator (decompose → N× explore → synthesize)
│   │   └── section_utils.py        # Section splitting/reassembly
│   ├── page_agent.py          # WikiPageAgent — 14 @function_tool methods, explore/enrich
│   ├── pipeline_graph.py      # LangGraph StateGraph for wiki generation
│   ├── pipeline_nodes.py      # Pipeline node functions
│   ├── rag/                   # IterativeRAGEngine, retrievers
│   ├── search.py              # WikiSearchService
│   ├── ask.py                 # WikiAskService (streaming Q&A)
│   ├── deep_research.py       # DeepResearchService
│   ├── event_bus.py           # WikiEventBus (pub/sub, SSE heartbeat)
│   ├── lint.py                # WikiLintService
│   ├── export_service.py      # WikiExportService (Markdown/ZIP/Git/Obsidian/MkDocs)
│   ├── mcp_tools.py           # Wiki MCP tools (10 tools)
│   └── ...                    # planners, composers, quality, memory, webhook, etc.
├── indexer/
│   ├── tree_sitter_parser.py  # Multi-language AST extraction
│   ├── code_graph_builder.py  # AST → GraphNode/GraphEdge
│   ├── embedding_generator.py # EmbeddingGenerator (ONNX/Torch/HTTP backends)
│   ├── incremental_indexer.py # Git-diff-based incremental index
│   └── languages/             # Per-language plugins (python, java, go, js, kotlin, swift, etc.)
├── store/
│   ├── falkordb_store.py      # FalkorDB connection, CRUD, thread pool execution
│   ├── schema.py              # NodeLabel, EdgeType, VECTOR_INDEX_CONFIGS
│   ├── wiki_page_store.py     # Wiki page CRUD, versions
│   ├── business_manager.py    # Multi-tenant graph naming
│   └── ...                    # traversal, search, wiki_* stores, settings, conversation
├── query/
│   ├── hybrid_query.py        # HybridQueryService (3-way RRF)
│   ├── semantic_query.py      # SemanticQueryService (vector similarity)
│   ├── graph_query.py         # GraphQueryService (Cypher templates)
│   ├── blast_radius.py        # BlastRadiusAnalyzer (BFS impact)
│   └── ...                    # deep_search, nl_cypher, reranker, community_detection
├── llm/
│   ├── provider.py            # LLMProvider (OpenAI-compatible, semaphore + retry)
│   ├── provider_factory.py    # Multi-provider factory with fallback
│   ├── base_provider.py       # LLMPortBridge protocol adapters
│   └── retry.py               # Tenacity-based retry decorators
├── services/
│   ├── service_registry.py    # ServiceRegistry (shared FalkorDB, per-business KB)
│   ├── kb_service.py          # KnowledgeBaseService (per-business facade)
│   └── scheduler.py           # SyncScheduler (cron git pull + reindex)
├── dashboard/                 # React 19 SPA (see below)
├── tests/                     # ~3775 pytest tests + 306 Vitest tests
├── docs/                      # Architecture, deployment, MCP integration, etc.
├── pyproject.toml             # Dependencies, Ruff, pytest config
└── Dockerfile
```

---

## Agent Framework Architecture

All agents use a unified execution engine (`run_agent_loop` in `wiki/agents/runner.py`):

```
GenericAgent (base class)
├── WikiPageAgent          — 14 tools, code exploration + wiki enrichment
└── WikiEditAgent          — section-based editing with streaming

DocOrchestrator (template method)
├── DomainDocAgent         — per business-domain documentation
├── TopicDocAgent          — deep-dive topic pages
└── FlowDocAgent           — business flow + call-chain docs

Composition orchestrators:
├── AskOrchestrator        — explore → answer (Q&A)
└── ResearchOrchestrator   — decompose → N× explore → synthesize
```

**Key patterns:**
- `run_agent_loop()`: Unified execution with LoopConfig (max_rounds, repeated call detection, guardrails, early stop, context trim)
- `LoopHooks`: on_no_tool_calls / on_loop_complete callbacks
- `@function_tool`: Auto-register methods as tools from function signatures
- `agent_tool()`: Wrap sub-agents as composable ToolDef instances
- Tool tier activation: tier-1 always, tier-2 from round 3, tier-3 from round 5
- Repeated call detection: Blocks consecutive identical tool+args (default enabled)

---

## Development Commands

### Backend

```bash
# Install dependencies
uv sync --extra dev --group dev

# Run server (port 8100)
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8100

# Run tests (parallel by default via pytest-xdist)
uv run pytest                          # Full suite (~3775 tests, ~60s with -n auto)
uv run pytest tests/wiki/agents/ -x    # Specific module, stop on first failure
uv run pytest -k "test_runner" -x      # By keyword

# Lint
uv run ruff check .
uv run ruff format .
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

## Architecture Decisions

1. **FalkorDB over Neo4j** — Redis-based graph with built-in vector indexes; same protocol, lower ops overhead
2. **Multi-tenant isolation** — Each business gets its own graph (`kb_{business_id}`)
3. **Agent Runner separation** — Agent identity (tools, prompts) separated from execution control (LoopConfig, hooks)
4. **LangGraph for wiki pipeline** — Declarative state machine for complex multi-step generation
5. **MCP dual exposure** — Main MCP (22 tools, always-on) + optional Wiki HTTP MCP (6 tools)
6. **Tiered tool activation** — Prevents token waste by introducing complex tools only in later rounds
7. **Repeated call detection** — Default-enabled; prevents agent loops that waste tokens
8. **Embedding deduplication** — Query text embedded once, shared across parallel searches

---

## Common Tasks for AI Agents

### Adding a new agent tool
1. Define the method on `WikiPageAgent` (or relevant agent) with `@function_tool` decorator
2. Specify `tier=` parameter (1-3) for activation round
3. The tool is auto-registered by `collect_tools()` — no manual schema needed
4. Add tests in `tests/wiki/agents/`

### Adding a new MCP tool
1. Add to `MCP_TOOLS_MANIFEST` in `api/mcp_server.py` (or `WIKI_MCP_TOOLS_MANIFEST` in `wiki/mcp_tools.py`)
2. Implement handler with `@mcp_tool("name", min_role=Role.VIEWER)` decorator
3. Test in `tests/api/`

### Adding a new API route
1. Choose router by role: `public_router`, `viewer_router`, `editor_router`, `admin_router`
2. Add route in appropriate `api/routes/*_routes.py`
3. Use `Depends(require_role(...))` for auth
4. Add response type to `api/models/`

### Modifying the wiki generation pipeline
1. Pipeline definition: `wiki/pipeline_graph.py`
2. Node implementations: `wiki/pipeline_nodes.py`
3. State: `wiki/pipeline_state.py`
4. Test: `tests/wiki/integration/`

---

## Environment Variables (Key Subset)

| Variable | Purpose |
|----------|---------|
| `HOST` / `PORT` | Server bind (default 0.0.0.0:8100) |
| `FALKORDB__HOST` / `FALKORDB__PORT` / `FALKORDB__PASSWORD` | Graph database |
| `EMBEDDING__MODEL_NAME` | Embedding model (default bge-m3) |
| `LLM__ENABLED` / `LLM__BASE_URL` / `LLM__API_KEY` / `LLM__MODEL` | LLM provider |
| `WIKI__*` | ~50 wiki feature flags |
| `REQUIRE_AUTH` / `API_TOKEN` | Authentication |
| `LOG_LEVEL` / `LOG_FORMAT` | Logging (console/json) |

Full config: `core/config.py` → `Settings` class.

---

## File Navigation Tips

- **Entry point:** `main.py` → `create_app()` → `lifespan`
- **Agent code:** `wiki/agents/` (framework) + `wiki/page_agent.py` (main agent)
- **API routes:** `api/routes/` (15+ modules)
- **Graph schema:** `store/schema.py` (NodeLabel, EdgeType)
- **Config:** `core/config.py` (Settings with all env vars)
- **Tests:** Mirror source structure under `tests/`
- **Frontend entry:** `dashboard/src/main.tsx` → `App.tsx` (routes)
- **Frontend API:** `dashboard/src/api/client.ts` + `hooks.ts`
- **Wiki components:** `dashboard/src/components/wiki/` (~60 components)
