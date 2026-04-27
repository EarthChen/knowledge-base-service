# Implementation status (code vs docs)

**Last updated:** 2026-04-27

This file is the **single place** for high-level “what exists in the repo today” vs historical plans. Plan checkboxes in `superpowers/plans/` track execution steps; they are not automatically reconciled with this file—update this table when behavior changes.

## Sub-project numbering (read this first)

| Document | Label | Meaning |
|----------|--------|---------|
| [superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-full-upgrade-design.md) | **SP1–SP6** | **Draft** roadmap: backend/FE hardening → incremental ingest → agent/MCP → lint/heal → deep research (six *sub-projects*). |
| [superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md) | **SP1–SP7** | **Approved** design: three *phases* (engineering → quality → memory) with **different** SP meanings (e.g. v2 SP1 = split `wiki_routes`, not the same as full-upgrade SP1). |
| `superpowers/plans/2026-04-26-sp1-*.md` … `sp6-*.md` | **SP1–SP6** | Implementation plans aligned with the **full-upgrade (draft)** numbering, not v2’s SP list. |

Do **not** merge the two SP namespaces when reading issues or PRs.

## Wiki subsystem (authoritative snapshot)

| Area | Code (primary) | HTTP / runtime | Status note |
|------|----------------|----------------|-------------|
| Wiki routes | `api/routes/wiki_routes.py` (+ `wiki_*_routes.py`) | Prefix `/api/v1/wiki` | Split into page / task / ask / feedback / contradiction routers. |
| Wiki tree | `api/routes/wiki_page_routes.py` | `GET /api/v1/wiki/tree?business_id=&view=` | — |
| Contradictions | `wiki/contradiction_detector.py`, `api/routes/wiki_contradiction_routes.py` | `GET /api/v1/wiki/contradictions?page_uid=...`；`PATCH .../acknowledge` / `.../resolve` | List uses **query** `page_uid`, not `/api/v1/wiki/{repository}/contradictions`. |
| Lint | `wiki/lint.py`, `wiki/lint_scheduler.py` | Periodic lint when `WIKI__LINT_SCHEDULER_ENABLED` | **Phase 0:** `LintScheduler` wired; lint paths call into `run_lint`. |
| **AutoHealer** | `wiki/auto_healer.py` | `WikiLintService.run_lint()` → `AutoHealer.heal()` | **`AutoHealer`** implements `remove_broken_references` + `deprecate_orphan_pages` only. Stale-page marking is **not** implemented (see module docstring). **Phase 0 已完成接入**：当 `WIKI__AUTO_HEAL_ENABLED=true`（默认）时，`run_lint` 在 lint 完成后自动调用 `AutoHealer.heal()`，结果写入 `WikiChangeLog`。HTTP、MCP、`LintScheduler` 均通过 `run_lint` 统一调用。 |
| Confidence / claims / memory v2 | `wiki/confidence_scorer.py`, `store/wiki_*`, etc. | See [wiki-generation-architecture.md](wiki-generation-architecture.md) | Defaults for several flags are **on** in `config.WikiConfig` (e.g. confidence + contradiction); override per env. |

## Phases 0–3 (2026-04-27) — implemented

| Phase | New / touched modules & surfaces | Status |
|-------|----------------------------------|--------|
| **0** | AutoHealer in `run_lint`; `LintScheduler` wired to unified lint | **Implemented** — see [phase0 spec](superpowers/specs/2026-04-27-phase0-knowledge-maintenance-loop-design.md) |
| **1** | `wiki/compilation_snapshot.py` (`WikiCompilationSnapshot`); `wiki/feedback_loop.py` (`FeedbackDrivenRegeneration`); `wiki/event_bus.py` (`WikiEventBus`, typed asyncio SSE broadcast); **`wiki_get_snapshot`** on both MCP surfaces (`api/mcp_wiki_server.py`, `wiki/mcp_tools` / `api/mcp_server.py` dispatch); **AGENTS.md** “Knowledge at a glance” (`wiki/agents_md_generator.py`) | **Implemented** — [spec](superpowers/specs/2026-04-27-phase1-knowledge-compilation-feedback-design.md) |
| **2** | `wiki/community_context.py` (`CachedCommunityService`, `format_communities_markdown`); `store/graph_queries.py` — `shortest_path_between_names`; `store/wiki_page_store.py` — `update_wiki_page_content`, `list_wiki_page_versions`, `get_wiki_page_version_diff`; **HTTP:** `PATCH /wiki/pages/{page_uid}/content`; `GET .../versions` and `GET .../diff` | **Implemented** — [spec](superpowers/specs/2026-04-27-phase2-graph-community-wiki-editing-design.md) |
| **3** | `wiki/reasoning_path.py` (`ReasoningPath`, `ReasoningStage`, entity extraction); `wiki/offline_pack.py` (`WikiOfflinePack` JSON bundle); `store/wiki_tree_store.py` — `wiki_tier` filtering (comprehensive / standard / essential); **HTTP:** `GET /{repository}/offline-pack`; `wiki_tier` query param on `GET /tree` | **Backend implemented** — [spec](superpowers/specs/2026-04-27-phase3-reasoning-visualization-multiview-design.md) (dashboard UI for some items may follow) |

Related plans (checkbox execution): `docs/superpowers/plans/2026-04-27-phase{0,1,2,3}-*.md`.

## Specs that are not separate files

The following were referenced in older architecture text; they are **not** present as standalone files under `docs/`. Use **[wiki-generation-architecture.md](wiki-generation-architecture.md)** and **[2026-04-26-llm-wiki-v2-upgrade-design.md](superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md)** instead:

- `2026-04-24-wiki-enhancement-design.md`
- `2026-04-26-wiki-tree-architecture-design.md`
- `2026-04-26-wiki-frontend-redesign.md`

## Verification

- **Python:** `requires-python >=3.12` in root `pyproject.toml` (see also [DEPLOYMENT.md](DEPLOYMENT.md)).
- **Tests:** `uv run pytest` — last collection **1769** tests (`uv run pytest --collect-only -q`)；仪表盘 Vitest **160** tests（`pnpm test`，`dashboard/`）。
