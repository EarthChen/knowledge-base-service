# Code map index

**Last updated:** 2026-04-27 (Wiki domain-classification perf: sub-batch, SSE, parallel, cache)  
**Repo:** `knowledge-base-service` (FastAPI + React/Vite + FalkorDB)

## Entry points

| Layer | Path |
|-------|------|
| HTTP app | `main.py` |
| Public / role-based API | `api/routes/kb_routers.py` → `api/routes/*_routes.py` |
| Wiki surface | `api/routes/wiki_routes.py` (aggregates `wiki_page_routes`, `wiki_task_routes`, `wiki_ask_routes`, `wiki_feedback_routes`, `wiki_contradiction_routes`, …) |
| MCP | `api/mcp_server.py`（主清单 20 工具），可选 `api/mcp_wiki_server.py`（HTTP 6 工具 + `wiki_mcp_routes`） |
| Dashboard | `dashboard/src/main.tsx`, `dashboard/vite.config.ts` |

## Backend areas

```
api/routes/          # HTTP routers (wiki_*, repository, settings, webhooks, wiki_mcp_routes, …)
store/               # FalkorDB / Cypher (WikiStore, SearchStore, graph_queries shortest_path, wiki_page_store …)
wiki/                # Wiki pipeline, quality, memory, lint, auto_healer, compilation_snapshot, feedback_loop, …
indexer/             # Code graph, chunks, incremental indexing
query/               # Hybrid search, blast radius, NL→Cypher (UI)
```

## Phases 0–3 + P0/P1 (2026-04-27) — key modules

| Track | Code (illustrative) | Notes |
|-------|---------------------|--------|
| Phase 0 | `wiki/lint.py`, `wiki/lint_scheduler.py`, `wiki/auto_healer.py` | AutoHealer wired via `run_lint`；见 [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) |
| Phase 1 | `wiki/compilation_snapshot.py`, `wiki/feedback_loop.py`, `wiki/event_bus.py`, `wiki/agents_md_generator.py` | `wiki_get_snapshot` on main + HTTP MCP；SSE event bus |
| Phase 2 | `wiki/community_context.py`, `store/graph_queries.py`（`shortest_path_between_names`）, `store/wiki_page_store.py`（`update_wiki_page_content`, 版本/ diff） | HTTP：`PATCH …/content`，`GET …/versions`，`GET …/diff` |
| Phase 3 | `wiki/reasoning_path.py`, `wiki/offline_pack.py`, `store/wiki_tree_store.py`（`wiki_tier`） | HTTP：`GET …/offline-pack`，`wiki_tier` on tree |
| P0 / P1 | (历史计划文件已清理) | 完成状态以 IMPLEMENTATION-STATUS 为准 |
| Wiki async gen (2026-04-27) | `wiki/task_store.py`, `api/routes/wiki_task_routes.py`, `store/wiki_page_store.py`（`get_repo_wiki_freshness`）, `dashboard/src/hooks/useWikiRegenerate.ts` | 业务 Wiki **202** + 任务轮询；见 [spec](../superpowers/specs/2026-04-27-wiki-generation-architecture-improvement-design.md) 与 [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) |

## Wiki subsystem (focused)

| Concern | Modules |
|---------|---------|
| Generation / compose | `wiki/service.py`, `wiki/composer.py`, `wiki/repo_composer.py`（`generate_business_wiki` 支持 `incremental`、`progress_callback`） |
| Business domain LLM (perf) | `wiki/business_domain_planner.py` (sub-batching), `wiki/cross_repo_domain_planner.py` (parallel classify, per-repo timeout, bounded in-memory cache), `llm/base_provider.py` (`LLMPortBridge.generate_stream`, SSE); `tests/wiki/test_domain_planner_perf.py` |
| Business wiki tasks / Redis | `wiki/task_store.py`（`WikiTaskStore`）, `wiki/task_registry.py`, `wiki/bootstrap.py`（`app.state.wiki_task_store`）, `api/routes/wiki_task_routes.py`（202 + `GET …/business/tasks/{task_id}`） |
| Incremental / changelog | `wiki/incremental.py`, `wiki/change_detector.py`, `store/wiki_changelog.py`；**仓库级 Wiki 新鲜度** `store/wiki_page_store.get_repo_wiki_freshness` |
| Quality v2 | `wiki/confidence_scorer.py`, `wiki/contradiction_detector.py`, `wiki/lint.py` |
| Auto-heal (library) | `wiki/auto_healer.py` — see [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) for wiring |
| Ask / research | `wiki/ask.py`, `wiki/deep_research.py`, `wiki/memory_loop.py` |

## Frontend (dashboard)

| Area | Location |
|------|----------|
| Wiki UI | `dashboard/src/pages/`, `dashboard/src/components/wiki/`（含 `ReasoningPathPanel`, `OfflinePackDownloadButton`, `WikiShell` 业务再生成进度/增量开关, 编辑/ diff 相关测试等）；`dashboard/src/hooks/useWikiRegenerate.ts`（轮询 `businessWikiTaskStatus`） |
| Settings | `dashboard/src/components/settings/` |
| API client | `dashboard/src/api/client.ts` |

## Related doc

- [ARCHITECTURE.md](../ARCHITECTURE.md) — system architecture
- [IMPLEMENTATION-STATUS.md](../IMPLEMENTATION-STATUS.md) — code vs plans, API path gotchas
