# User guide

## What is this system?

The **Knowledge Base Service** indexes your repositories into a **graph** (functions, classes, modules, calls, imports, …) plus **semantic vectors** so you can search by natural language, explore relationships, and (optionally) generate wiki-style documentation. A **web dashboard** provides search and exploration without writing code.

## Dashboard tour

After starting the server (`uv run uvicorn main:app …`), open the root URL (default **http://localhost:8100**).

| Area | What you do there |
|------|-------------------|
| **Search** | Run **hybrid** NL queries (`POST /hybrid` under the hood): results combine semantic hits with graph-expanded context. Filter by repository or language when needed. |
| **Deep Search** | Multi-step **LLM** investigation (requires `LLM__ENABLED` and working provider). Streams stages when using the SSE endpoint from the UI. |
| **Graph / Explorer** | Explore entities and neighborhoods (force-directed views, entity detail). Aligns with `rag_graph` and `/graph/explore` APIs. |
| **Repositories** | See indexed repos, stats, and status; entry point for “what’s in the index”. |
| **Indexing** | Trigger **full** or **incremental** jobs; for remotes, configure Git and pass `git_url` via API if not using the UI wiring. |
| **Wiki** | Browse and search **generated** wiki pages when the wiki pipeline is enabled and pages exist. |
| **Architecture** | View layer and endpoint-oriented breakdowns where enrichment has classified services. |
| **Sync / Settings** | Scheduled git pull + re-index, hooks, LLM/provider settings (as exposed in UI). |

The UI is a **React + Vite** SPA: heavy charts and graph code load when you open those routes.

## Index your first repository

### Option A: Local directory (API)

Use an **editor** token. Call:

`POST /api/v1/index` with JSON like:

```json
{
  "directory": "/absolute/path/to/repo",
  "repository": "my-repo",
  "mode": "full"
}
```

You receive a **`task_id`**. Poll `GET /api/v1/index/tasks/{task_id}` until `completed` or `failed`.

### Option B: Git URL

Set `GIT__GITLAB_URL` / `GIT__GITLAB_TOKEN` (or SSH) as needed, then:

```json
{
  "git_url": "https://gitlab.example.com/group/myproject.git",
  "branch": "main",
  "repository": "myproject",
  "mode": "full"
}
```

The server clones under `GIT__CLONE_BASE_PATH` and indexes the checkout.

### Option C: MCP agent

Use tool **`rag_index`** (requires **editor** role) with the same fields as the HTTP body.

## Search effectively

- Prefer **specific** identifiers in the query when you know them (class/function names); the hybrid stack boosts **keyword** matches via RRF.
- **Scope** with `repository` and `language` to reduce noise.
- For **large files**, enable child-chunk behavior (see `HYBRID_SEARCH__USE_CHILD_CHUNKS` and MCP `use_child_chunks`) for finer-grained hits.
- For **architecture questions**, use the architecture view or MCP `search_architecture` (`mode: layers` or `endpoints`).

Deprecated global search endpoints have been removed; use **`POST /api/v1/hybrid`** with optional `entity_type` for business entities (`flow`, `concept`).

## Using with AI agents (MCP)

1. **Token** — Create a `viewer` or `editor` token (`tokens.yaml` or `API_TOKENS`).
2. **List tools** — `GET /api/v1/mcp/tools` with `Authorization: Bearer <token>`.
3. **Invoke** — `POST /api/v1/mcp/tool` with `{"tool_name":"rag_query","arguments":{...}}`.
4. **Tenant** — Pass `X-Business-Id: your-tenant` when using multi-business graphs with unbound admin tokens.

Full tool list and schemas: [MCP-INTEGRATION.md](MCP-INTEGRATION.md).

## Authentication quick reference

| Mode | Behavior |
|------|----------|
| No tokens configured | Open access (not for production); `REQUIRE_AUTH` forces failure at startup unless tokens exist |
| `tokens.yaml` / env tokens | Bearer required for protected routers; roles control viewer vs editor vs admin routes |

Check your role: `GET /api/v1/auth/me`.
