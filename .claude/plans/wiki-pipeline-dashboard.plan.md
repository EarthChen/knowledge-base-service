# Plan: Wiki Pipeline Dashboard Enhancement

**Complexity**: Large (4 phases, ~17 files)

## Summary

Three-part enhancement to the wiki generation system:
1. **LLM Concurrency Boost** — raise default concurrency limits and add hot-reload support for pipeline config
2. **Rich Pipeline Status Display** — show all 20 pipeline nodes with real-time status, timing, and sub-progress in the dashboard
3. **Full Configuration Panel** — expose all ~60 unexposed `AppWikiFlags` parameters in the dashboard settings, grouped by pipeline stage

## Current Pain Points

- `domain_agent_concurrency` defaults to **3** — too low for repos with many domains
- `module_compose_concurrency` defaults to **6** — bottleneck during leaf module composition
- Frontend shows only 9 abstract phase dots; no visibility into which specific node is running, how long it's been running, or per-domain/per-module progress
- ~60+ `AppWikiFlags` params are not exposed in the dashboard (only configurable via `.env` or direct DB)
- No hot-reload for most pipeline settings — changing concurrency requires a full service restart
- `PipelineConcurrency` semaphore cache is never invalidated, so even DB-persisted config changes don't take effect without restart

## Patterns to Mirror

| Category | Source | Pattern |
|----------|--------|---------|
| Config defaults | `core/config.py:188-427` | `AppWikiFlags` fields with `Field(default=..., ge=..., le=...)` |
| Hot-reload | `api/routes/settings_routes.py` | `HOT_RELOAD_KEYS` set for live config changes |
| Settings sections | `dashboard/src/components/settings/SystemConfigPanel.tsx` | Collapsible sections with `WikiFeaturesSection` pattern |
| Config keys | `dashboard/src/components/settings/systemConfigConstants.ts` | `WIKI_*_KEYS` arrays + `NUMBER_FIELD_CONSTRAINTS` |
| Progress callback | `wiki/pipeline_graph.py:70-140` | `_with_progress()` wrapper pattern |
| SSE events | `api/routes/wiki_task_routes.py:108-144` | `_progress()` → `WikiEventBus.publish()` |
| i18n labels | `dashboard/src/components/settings/configFieldLabels.ts` | `configFieldLabels` record with en/zh |

---

## Phase 1: Backend — Concurrency & Hot-Reload

### Task 1.1: Raise Default Concurrency Limits
- **File**: `core/config.py`
- **Action**: Update defaults for 4 fields:

| Parameter | Current | New |
|-----------|---------|-----|
| `domain_agent_concurrency` | 3 | 6 |
| `module_compose_concurrency` | 6 | 12 |
| `compose_concurrency` | 12 | 16 |
| `heal_concurrency` | 5 | 8 |

- **Validate**: `uv run pytest tests/ -k "config" -x -q`

### Task 1.2: Add Hot-Reload for Pipeline Config
- **File**: `api/routes/settings_routes.py`
- **Action**: Extend `HOT_RELOAD_KEYS` set with all concurrency and pipeline tuning keys:
  - All `*_concurrency` keys (8 keys)
  - `llm_global_rpm_limit`, `llm_global_tpm_limit`
  - `domain_agent_max_iterations_core/standard/skeleton`
  - `heal_max_rounds_core/standard`, `heal_loop_max_total_attempts`
  - `quality_min_score`, `quality_sample_size`
- **Validate**: `uv run pytest tests/api/test_settings_routes.py -x -q`

### Task 1.3: Invalidate Semaphore Cache on Config Change
- **File**: `wiki/pipeline_concurrency.py` — add `PipelineConcurrency.refresh(overrides=None)` class method that clears `_cache` and optionally applies override dict
- **File**: `services/settings_service.py` — after successful hot-reload update touching `wiki.*_concurrency`, call `PipelineConcurrency.refresh()`
- **Validate**: `uv run pytest tests/wiki/ -k "concurrency" -x -q`

### Task 1.4: Add Per-Node Timing to Progress Callbacks
- **File**: `wiki/pipeline_graph.py` — enhance `_with_progress()` to emit `elapsed_sec` in the completion callback (currently only logs it)
- **Validate**: `uv run pytest tests/wiki/test_pipeline_graph.py -x -q`

---

## Phase 2: Backend — Rich Status API

### Task 2.1: Add Per-Node Status Tracking to Pipeline State
- **File**: `wiki/pipeline_state.py`
- **Action**: Add field `node_statuses: NotRequired[dict[str, dict[str, Any]]]` — maps node_name → {status, started_at, completed_at, elapsed_sec, detail, items_processed, items_total}

### Task 2.2: Update `_with_progress()` to Track Node Statuses
- **File**: `wiki/pipeline_graph.py`
- **Action**: Modify `_with_progress()` wrapper:
  - On entry: set `state["node_statuses"][node_name] = {"status": "running", "started_at": time.time()}`
  - On exit: set status to `"completed"`, record `completed_at`, `elapsed_sec`
  - On exception: set status to `"failed"`, record error detail
  - Include `node_statuses` in progress callback payload

### Task 2.3: Enrich SSE Progress Events
- **File**: `api/routes/wiki_task_routes.py`
- **Action**: In `_progress()` callback, pass through `node_statuses`, `items_processed`, `items_total` into `SqliteTaskStore` progress_json, `WikiTaskRegistry`, and `WikiEventBus` events

### Task 2.4: Add Pipeline Config Snapshot to Task Response
- **File**: `api/routes/wiki_task_routes.py`
- **Action**: Include `config_snapshot` dict in `GET /wiki/business/tasks/{taskId}` response with current concurrency/rate-limit values
- **Validate**: `uv run pytest tests/api/test_wiki_task_routes.py -x -q`

---

## Phase 3: Frontend — Pipeline Node Visualization

### Task 3.1: Create `WikiPipelineVisualization` Component
- **New file**: `dashboard/src/components/wiki/WikiPipelineVisualization.tsx`
- **Action**: Vertical timeline showing all 20 nodes with:
  - Status icons: green check (completed), blue spinner (running), gray circle (waiting), red X (failed)
  - Node name with i18n label
  - Elapsed time for completed/running nodes
  - Sub-progress bar + counter for running node (e.g., "45/120 modules")
  - Tooltip with start time and detail

### Task 3.2: Update `WikiActiveTasks` Component
- **File**: `dashboard/src/components/wiki/WikiActiveTasks.tsx`
- **Action**: Replace 9-dot stage flow indicator with collapsible `<WikiPipelineVisualization />`. Keep task header (ID, cancel, overall progress bar).

### Task 3.3: Update SSE Event Handling
- **File**: `dashboard/src/hooks/useWikiEvents.ts`
- **Action**: Add `business_gen_progress` event type with `node_statuses` payload

### Task 3.4: Update `WikiAsyncTask` Type
- **File**: `dashboard/src/api/types.ts`
- **Action**: Add `node_statuses` and `config_snapshot` optional fields

### Task 3.5: Update i18n Labels
- **Files**: `dashboard/src/i18n/zh.ts`, `dashboard/src/i18n/en.ts`
- **Action**: Add translations for all 20 pipeline node display names

- **Validate Phase 3**: `cd dashboard && pnpm build && pnpm test`

---

## Phase 4: Frontend — Full Configuration Panel

### Task 4.1: Add New Config Sections
- **File**: `dashboard/src/components/settings/SystemConfigPanel.tsx`
- **Action**: Add 8 new collapsible sections exposing ~60 unexposed parameters:

| Section | Keys (count) |
|---------|-------------|
| Domain Agent | 9 params (concurrency, iterations, timeout, explore) |
| Composition | 8 params (concurrency x5, toggles, language) |
| Domain Reassembly | 8 params (toggles, thresholds) |
| Healing & Quality | 12 params (concurrency, rounds, thresholds, mode) |
| LLM Rate Limiting | 2 params (RPM, TPM) |
| Delegation & Enrichment | 7 params (toggles, limits) |
| Business Domain | 5 params (toggles, batch/timeout/concurrency/TTL) |
| Incremental & Budget | 7 params (toggles, budgets, percentiles, strategy) |

### Task 4.2: Update `systemConfigConstants.ts`
- **File**: `dashboard/src/components/settings/systemConfigConstants.ts`
- **Action**: Add new key arrays, update `NUMBER_FIELD_CONSTRAINTS` with min/max for all new number fields

### Task 4.3: Update `configFieldLabels.ts`
- **File**: `dashboard/src/components/settings/configFieldLabels.ts`
- **Action**: Add en/zh labels for all newly exposed fields

### Task 4.4: Hot-Reload Indicator
- **File**: `dashboard/src/components/settings/SystemConfigPanel.tsx`
- **Action**: Show green "Applied" badge for hot-reloadable keys vs amber "Restart required" for others

- **Validate Phase 4**: `cd dashboard && pnpm build && pnpm test && pnpm lint`

---

## Phase 5 (Optional): Per-Run Config Overrides

### Task 5.1: Accept Config Overrides in Generate API
- **File**: `api/routes/wiki_task_routes.py`
- **Action**: `POST /wiki/business/generate` accepts optional `config_overrides` body field

### Task 5.2: Merge Config Overrides in Pipeline
- **File**: `wiki/pipeline_orchestrator.py`
- **Action**: Merge `config_overrides` into `state["config"]` and call `PipelineConcurrency.refresh(overrides=...)`

- **Validate**: `uv run pytest tests/wiki/test_pipeline_orchestrator.py -x -q`

---

## Validation Commands

```bash
# Backend
uv run pytest tests/wiki/ -x -q
uv run pytest tests/api/ -x -q
uv run ruff check wiki/ api/ services/ core/config.py

# Frontend
cd dashboard && pnpm build
cd dashboard && pnpm test
cd dashboard && pnpm lint
```

## Risks

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| Higher concurrency overwhelms LLM provider | Medium | Keep `llm_global_rpm_limit`/`llm_global_tpm_limit` as safety net; defaults stay 0 (disabled) |
| Hot-reload race on semaphore cache | Low | `refresh()` clears cache atomically; existing held semaphores gracefully drain |
| Too many settings overwhelm users | Medium | Collapsible sections with defaults shown; group rarely-changed params |
| SSE events flood client | Low | Events fire ~20/node + per-item in heavy nodes — same as current 5s polling |

## Acceptance

- [ ] `domain_agent_concurrency` default = 6, `module_compose_concurrency` = 12
- [ ] Concurrency settings hot-reload without restart
- [ ] All 20 pipeline nodes visible in dashboard with real-time status
- [ ] Running node shows sub-progress and elapsed time
- [ ] All `AppWikiFlags` params accessible in dashboard, grouped by category
- [ ] Per-run config overrides supported via API
- [ ] All tests pass, no lint errors
