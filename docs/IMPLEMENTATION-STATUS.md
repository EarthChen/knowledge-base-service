# Implementation status (code vs docs)

**Last updated:** 2026-04-30

This file is the **single place** for high-level "what exists in the repo today" vs historical plans.

## Sub-project numbering (read this first)

Historical specs used two independent SP numbering schemes (SP1-SP6 for full-upgrade draft, SP1-SP7 for v2 approved design). Both design documents and their implementation plans have been **completed and removed** (2026-04-30). Current status is captured in the table below and in [wiki-audit-20260430](superpowers/wiki-audit-20260430_222403.md).

Do **not** merge the two SP namespaces when reading older issues or PRs.

## Wiki subsystem (authoritative snapshot)

| Area | Code (primary) | HTTP / runtime | Status note |
|------|----------------|----------------|-------------|
| Wiki routes | `api/routes/wiki_routes.py` (+ `wiki_*_routes.py`) | Prefix `/api/v1/wiki` | Split into page / task / ask / feedback / contradiction routers. |
| **Business wiki async** | `wiki/task_store.py`, `wiki/task_registry.py`, `api/routes/wiki_task_routes.py`, `wiki/bootstrap.py` | **`POST /api/v1/wiki/business/generate`** -> **202** `{task_id, status: "pending"}`; **`GET /api/v1/wiki/business/tasks/{task_id}`** | **Implemented** |
| Wiki tree | `api/routes/wiki_page_routes.py` | `GET /api/v1/wiki/tree?business_id=&view=` | — |
| Contradictions | `wiki/contradiction_detector.py`, `api/routes/wiki_contradiction_routes.py` | `GET /api/v1/wiki/contradictions?page_uid=...`; `PATCH .../acknowledge` / `.../resolve` | List uses **query** `page_uid`. |
| Lint | `wiki/lint.py`, `wiki/lint_scheduler.py` | Periodic lint when `WIKI__LINT_SCHEDULER_ENABLED` | **Phase 0:** `LintScheduler` wired; lint paths call into `run_lint`. |
| **AutoHealer** | `wiki/auto_healer.py` | `WikiLintService.run_lint()` -> `AutoHealer.heal()` | **`AutoHealer`** implements `remove_broken_references` + `deprecate_orphan_pages` only. Stale-page marking is **not** implemented. |
| Confidence / claims / memory v2 | `wiki/confidence_scorer.py`, `store/wiki_*`, etc. | See [wiki-generation-architecture.md](wiki-generation-architecture.md) | Defaults for several flags are **on** in `config.WikiConfig` (e.g. confidence + contradiction); override per env. |

## Phases 0-3 (2026-04-27) — implemented

| Phase | New / touched modules & surfaces | Status |
|-------|----------------------------------|--------|
| **0** | AutoHealer in `run_lint`; `LintScheduler` wired to unified lint | **Implemented** |
| **1** | `WikiCompilationSnapshot`; `FeedbackDrivenRegeneration`; `WikiEventBus`; `wiki_get_snapshot` on both MCP surfaces; AGENTS.md generator | **Implemented** |
| **2** | `CachedCommunityService`; `shortest_path_between_names`; page content editing + versions + diff | **Implemented** |
| **3** | `ReasoningPath`; `WikiOfflinePack`; `wiki_tier` filtering | **Backend implemented** |

## Specs that are not separate files

The following were referenced in older architecture text; they are **not** present as standalone files under `docs/`. Use **[wiki-generation-architecture.md](wiki-generation-architecture.md)** as the primary design reference:

- `2026-04-24-wiki-enhancement-design.md`
- `2026-04-26-wiki-tree-architecture-design.md`
- `2026-04-26-wiki-frontend-redesign.md`

## Verification

- **Python:** `requires-python >=3.12` in root `pyproject.toml` (see also [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Tests:** `uv run pytest`; Dashboard Vitest `pnpm test` (`dashboard/`).
