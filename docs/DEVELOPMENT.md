# Developer guide

## Project structure

```text
knowledge-base-service/
├── main.py                 # FastAPI app, route registration, lifespan
├── config.py               # Pydantic settings (env / .env)
├── auth.py                 # Token registry, roles, dependencies
├── service.py              # KnowledgeBaseService composition
├── service_registry.py     # Multi-tenant graph services
├── api/
│   ├── mcp_server.py       # MCP manifest + KnowledgeBaseMCPHandler
│   ├── rate_limiter.py     # Token-bucket middleware
│   └── routes/             # wiki, webhook, provider helpers
├── indexer/                # Tree-sitter → graph, incremental index, embeddings
├── store/                  # FalkorDB adapter, schema, graph_queries
├── query/                  # Hybrid, semantic, graph_query, insights, …
├── search/                 # RRF fusion helpers
├── wiki/                   # Wiki pipeline, MCP wiki tools, webhook, scheduler
├── llm/                    # OpenAI-compatible providers
├── dashboard/              # React + Vite SPA (build → ../static)
├── tests/
├── docs/
├── pyproject.toml
├── Dockerfile
└── README.md
```

## Dev setup

### Backend

```bash
uv sync
uv sync --extra dev    # pytest, ruff, …
```

Optional extras from `pyproject.toml`:

```bash
uv sync --extra torch    # GPU sentence-transformers path when not using ONNX only
```

Run the API:

```bash
uv run uvicorn main:app --reload --host 0.0.0.0 --port 8100
```

### Frontend

```bash
cd dashboard
pnpm install
pnpm dev          # local dev server
pnpm build        # production bundle → static/
```

Use **`pnpm`**, not npm, per project convention.

## Tests

```bash
uv run python -m pytest
```

Async tests use `pytest-asyncio` (`asyncio_mode = auto` in `pyproject.toml`).

Frontend: **`pnpm build`** verifies TypeScript and Vite production build (ci-style); add `pnpm lint` for ESLint when tightening quality gates.

## Adding a programming language

1. **Config** — Extend `supported_languages` and `file_extensions` in `config.py` (or override via env if your deployment supports list serialization).
2. **Parser** — Add or extend Tree-sitter queries in `indexer/tree_sitter_parser.py` (and related language-specific helpers).
3. **Graph** — Map AST constructs to `NodeLabel` / `EdgeType` in `indexer/code_graph_builder.py`.
4. **Vectors** — Ensure emitted nodes use labels covered by `VECTOR_INDEX_CONFIGS` in `store/schema.py` if they need embeddings.
5. **Tests** — Add fixture snippets under `tests/indexer/` and run pytest.

## Adding MCP tools

1. Append a manifest entry to `MCP_TOOLS_MANIFEST` in `api/mcp_server.py` (or `WIKI_MCP_TOOLS_MANIFEST` in `wiki/mcp_tools.py` for wiki-specific tools).
2. If the tool requires more than viewer access, add `MCP_TOOL_MIN_ROLE` (`Role.EDITOR` or `Role.ADMIN`).
3. Implement an async handler on `KnowledgeBaseMCPHandler` (or delegate to `WikiMCPHandler`).
4. Register the name in the `handlers` dict inside `handle_tool_call`.
5. Wire HTTP `POST /api/v1/mcp/tool` automatically via existing routes; expose listing via `get_tools_manifest`.
6. Add tests under `tests/test_mcp_*.py`.

## Code style

- **Python**: Ruff (`tool.ruff` in `pyproject.toml`), target 3.12, line length 120.
- **Type hints**: Prefer explicit types on public APIs (`from __future__ import annotations`).
- **Logging**: Use `log = get_logger(__name__)` and structured keys (`log.info("event", key=value)`).

Run Ruff:

```bash
uv run ruff check .
uv run ruff format .
```
