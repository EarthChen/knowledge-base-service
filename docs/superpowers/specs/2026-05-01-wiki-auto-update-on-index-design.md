# Design Spec: Wiki Auto-Update on Index with Dynamic Dashboard Toggle

> **Status**: Approved (v2 — simplified)
> **Created**: 2026-05-01
> **Goal**: After incremental indexing completes, automatically trigger `WikiService.generate_incremental` to keep wiki in sync with code. The toggle is hot-reloadable from the dashboard.

---

## 1. Problem Statement

When code changes are indexed incrementally (via sync, scheduler, or MCP), the wiki content does not update automatically. The infrastructure exists but is not wired:

1. `IncrementalIndexer._maybe_auto_update_wiki` has the hook point, but the callback is not connected.
2. The `wiki.auto_update_on_index` setting requires a service restart to take effect (reads from `get_settings()` which is `@lru_cache`).
3. Dashboard UI for the toggle already exists (`WikiFeaturesSection`), no frontend changes needed.

## 2. Solution Overview

Reuse the existing, production-proven `WikiService.generate_incremental` as the auto-update callback:

1. **Inject** a callback (`Callable`) wrapping `WikiService.generate_incremental` into `IncrementalIndexer`.
2. **Inject** `SettingsStore` for hot-reading the toggle from SQLite (DB value takes precedence over startup config).
3. **Mark** `wiki.auto_update_on_index` as a hot-reload key in the Settings API response.

### Why Not `WikiIncrementalUpdater`?

`WikiIncrementalUpdater` uses file-level diff and writes only to `WikiCache` (memory). `WikiService.generate_incremental` uses `code_hash` diff and persists to the graph database. For the goal of "wiki stays in sync with code", the latter is more reliable and already proven.

## 3. Detailed Design

### 3.1 IncrementalIndexer — Callback + Dynamic Config

**File**: `indexer/incremental_indexer.py`

Changes to `__init__`:
```python
def __init__(
    self,
    ...,
    wiki_incremental_updater: WikiIncrementalUpdater | None = None,
    wiki_auto_updater: Callable[[str], Awaitable[Any]] | None = None,
    settings_store: SettingsStore | None = None,
) -> None:
    ...
    self._wiki_incremental_updater = wiki_incremental_updater
    self._wiki_auto_updater = wiki_auto_updater
    self._settings_store = settings_store
```

New helper method:
```python
async def _check_auto_update_enabled(self) -> bool:
    """Hot-read from DB, fallback to startup config."""
    if self._settings_store is not None:
        val = await self._settings_store.get("wiki.auto_update_on_index")
        if val is not None:
            return val.strip().lower() in ("true", "1", "yes")
    return get_settings().wiki.auto_update_on_index
```

Updated `_maybe_auto_update_wiki`:
```python
async def _maybe_auto_update_wiki(self, changed_files, repository, wiki_config):
    if repository is None:
        return
    if self._wiki_auto_updater is None and self._wiki_incremental_updater is None:
        return
    if not await self._check_auto_update_enabled():
        return
    try:
        if self._wiki_auto_updater is not None:
            await self._wiki_auto_updater(repository)
        elif self._wiki_incremental_updater is not None:
            await self._wiki_incremental_updater.update_from_index_event(
                repository, changed_files, wiki_config,
            )
    except Exception:
        log.warning("auto_wiki_update_failed", repository=repository, exc_info=True)
```

The `wiki_auto_updater` callback takes priority over `wiki_incremental_updater`, maintaining backward compatibility.

### 3.2 KnowledgeBaseService — Wiring

**File**: `services/kb_service.py`

After `WikiService` is constructed, pass the callback and `SettingsStore`:

```python
self._incremental_indexer = IncrementalIndexer(
    store=self._store,
    graph_builder=self._graph_builder,
    embedding_gen=self._embedding,
    doc_indexer=self._doc_indexer,
    enricher=self._enricher,
    repo_task_manager=self._repo_task_mgr,
    wiki_auto_updater=self._auto_update_wiki,
    settings_store=self._settings_store,
)
```

Where `_auto_update_wiki` is:
```python
async def _auto_update_wiki(self, repository: str) -> Any:
    return await self._wiki_service.generate_incremental(repository)
```

**Note on `language` parameter**: `generate_incremental` defaults to `language="en"`. For auto-update, using the default is acceptable since wiki language is determined at initial generation time and incremental updates re-compose only changed pages using existing page context.

### 3.3 main.py + settings_routes.py — SettingsStore Lifecycle Unification

**Files**: `main.py`, `api/routes/settings_routes.py`

Currently `settings_routes.py` creates a lazy singleton `_settings_store` via `_get_store()`. To share one instance between `IncrementalIndexer` and settings routes:

1. Create `SettingsStore` in `main.py` lifespan, store on `app.state`.
2. Modify `settings_routes.py` to accept the store from `app.state` (remove module-level singleton).

```python
# main.py — in lifespan, after registry.start()
from store.settings_store import SettingsStore
settings_store = SettingsStore()
app.state.settings_store = settings_store
```

```python
# settings_routes.py — replace _get_store()
def _get_store(request: Request) -> SettingsStore:
    return request.app.state.settings_store
```

**Note**: `KnowledgeBaseService` is created inside `ServiceRegistry`, not directly in `main.py`. The `SettingsStore` will be passed via `ServiceRegistry` → `KnowledgeBaseService.from_components()` or by storing it on `app.state` and injecting at the indexer wiring point.

### 3.4 Settings API — Hot-Reload Flag

**File**: `api/routes/settings_routes.py`

```python
HOT_RELOAD_KEYS = frozenset({"wiki.auto_update_on_index"})

# In PUT handler response:
all_hot = all(u["key"] in HOT_RELOAD_KEYS for u in body.settings)
return {
    "status": "ok",
    "updated": str(len(body.settings)),
    "restart_required": not all_hot,
}
```

## 4. Data Flow

```
Code push → SyncScheduler/Webhook → git pull → IncrementalIndexer.index_incremental
  → graph nodes updated (code_hash refreshed)
  → _maybe_auto_update_wiki
    → _check_auto_update_enabled (hot-read from SQLite)
      → True: WikiService.generate_incremental(repository)
        → compute_wiki_diff (compare code_hash with last wiki version)
        → re-compose affected pages
        → persist_pages to graph DB
      → False: skip
```

## 5. Files Changed

| File | Change Type | Description |
|------|------------|-------------|
| `indexer/incremental_indexer.py` | Modify | Add `wiki_auto_updater` + `settings_store` params, dynamic config check |
| `services/kb_service.py` | Modify | Pass callback + settings_store to IncrementalIndexer |
| `main.py` | Modify | Create SettingsStore in lifespan, pass to KnowledgeBaseService |
| `api/routes/settings_routes.py` | Modify | Hot-reload key logic for `wiki.auto_update_on_index` |

## 6. Test Plan

| Test | What It Verifies |
|------|-----------------|
| `test_auto_update_calls_generate_incremental` | When enabled + callback set → `generate_incremental` is called with repository |
| `test_auto_update_skips_when_disabled` | When disabled → callback not called |
| `test_dynamic_config_db_true` | DB value "true" → enabled |
| `test_dynamic_config_db_false` | DB value "false" → disabled |
| `test_dynamic_config_fallback` | No DB value → fallback to `get_settings()` default (False) |
| `test_auto_update_error_does_not_block_indexing` | Exception in callback → logged, indexing still succeeds |
| `test_settings_api_hot_reload_flag` | Updating `wiki.auto_update_on_index` returns `restart_required: false` |
| `test_settings_api_mixed_keys` | Updating mixed keys returns `restart_required: true` |
