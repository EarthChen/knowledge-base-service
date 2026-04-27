# Code map index

**Last updated:** 2026-04-27  
**Repo:** `knowledge-base-service` (FastAPI + React/Vite + FalkorDB)

## Entry points

| Layer | Path |
|-------|------|
| HTTP app | `main.py` |
| Public / role-based API | `api/routes/kb_routers.py` → `api/routes/*_routes.py` |
| Wiki surface | `api/routes/wiki_routes.py` (aggregates `wiki_page_routes`, `wiki_task_routes`, `wiki_ask_routes`, `wiki_feedback_routes`, `wiki_contradiction_routes`, …) |
| MCP | `api/mcp_server.py`, optional `api/mcp_wiki_server.py` |
| Dashboard | `dashboard/src/main.tsx`, `dashboard/vite.config.ts` |

## Backend areas

```
api/routes/          # HTTP routers (wiki_*, repository, settings, webhooks, …)
store/               # FalkorDB / Cypher (WikiStore, SearchStore, …)
wiki/                # Wiki pipeline, quality, memory, lint, auto_healer, …
indexer/             # Code graph, chunks, incremental indexing
query/               # Hybrid search, blast radius, NL→Cypher (UI)
```

## Wiki subsystem (focused)

| Concern | Modules |
|---------|---------|
| Generation / compose | `wiki/service.py`, `wiki/composer.py`, `wiki/repo_composer.py` |
| Incremental / changelog | `wiki/incremental.py`, `wiki/change_detector.py`, `store/wiki_changelog.py` |
| Quality v2 | `wiki/confidence_scorer.py`, `wiki/contradiction_detector.py`, `wiki/lint.py` |
| Auto-heal (library) | `wiki/auto_healer.py` — see [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) for wiring |
| Ask / research | `wiki/ask.py`, `wiki/deep_research.py`, `wiki/memory_loop.py` |

## Frontend (dashboard)

| Area | Location |
|------|----------|
| Wiki UI | `dashboard/src/pages/`, `dashboard/src/components/wiki/` |
| Settings | `dashboard/src/components/settings/` |
| API client | `dashboard/src/api/client.ts` |

## Related doc

- [ARCHITECTURE.md](../ARCHITECTURE.md) — system architecture
- [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) — code vs plans, API path gotchas
