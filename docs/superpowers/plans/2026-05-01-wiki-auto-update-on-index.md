# Wiki Auto-Update on Index Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After incremental indexing completes, automatically trigger `WikiService.generate_incremental` to keep wiki in sync with code, with a hot-reloadable dashboard toggle.

**Architecture:** Inject a `Callable` callback wrapping `WikiService.generate_incremental` into `IncrementalIndexer`. Inject `SettingsStore` for hot-reading the toggle from SQLite (bypassing `@lru_cache`). Unify `SettingsStore` lifecycle to a single app-level instance shared by settings routes and indexer.

**Tech Stack:** Python 3.12, FastAPI, SQLite (SettingsStore), pytest, asyncio

**Spec:** `docs/superpowers/specs/2026-05-01-wiki-auto-update-on-index-design.md`

---

### Task 1: IncrementalIndexer — Add `wiki_auto_updater` + `settings_store` params and dynamic config

**Files:**
- Modify: `indexer/incremental_indexer.py:123-171`
- Test: `tests/wiki/test_incremental_index_hook.py`

- [ ] **Step 1: Write failing tests for callback-based auto-update**

Add these tests to `tests/wiki/test_incremental_index_hook.py`:

```python
@pytest.mark.asyncio
async def test_auto_update_calls_generate_incremental() -> None:
    """wiki_auto_updater callback is invoked when enabled."""
    from indexer.incremental_indexer import IncrementalIndexer

    store = AsyncMock()
    builder = MagicMock()
    embed = MagicMock()
    callback = AsyncMock(return_value={"status": "ok"})

    indexer = IncrementalIndexer(
        store=store,
        graph_builder=builder,
        embedding_gen=embed,
        wiki_auto_updater=callback,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_awaited_once_with("my-repo")


@pytest.mark.asyncio
async def test_auto_update_skips_when_disabled() -> None:
    """wiki_auto_updater callback is NOT invoked when disabled."""
    from indexer.incremental_indexer import IncrementalIndexer

    callback = AsyncMock()
    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_auto_updater=callback,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = False

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_auto_update_error_does_not_block_indexing() -> None:
    """Exception in wiki_auto_updater callback is caught and logged."""
    from indexer.incremental_indexer import IncrementalIndexer

    callback = AsyncMock(side_effect=RuntimeError("wiki broke"))
    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_auto_updater=callback,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        # Should NOT raise
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_auto_updater_takes_priority_over_incremental_updater() -> None:
    """wiki_auto_updater callback takes priority over wiki_incremental_updater."""
    from indexer.incremental_indexer import IncrementalIndexer

    callback = AsyncMock(return_value={"status": "ok"})
    old_updater = AsyncMock()

    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_incremental_updater=old_updater,
        wiki_auto_updater=callback,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_awaited_once_with("my-repo")
    old_updater.update_from_index_event.assert_not_awaited()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_incremental_index_hook.py::test_auto_update_calls_generate_incremental tests/wiki/test_incremental_index_hook.py::test_auto_update_skips_when_disabled tests/wiki/test_incremental_index_hook.py::test_auto_update_error_does_not_block_indexing tests/wiki/test_incremental_index_hook.py::test_auto_updater_takes_priority_over_incremental_updater -v`
Expected: FAIL — `IncrementalIndexer.__init__` does not accept `wiki_auto_updater`

- [ ] **Step 3: Implement IncrementalIndexer changes**

In `indexer/incremental_indexer.py`:

1. Add imports at the top (after existing imports):
```python
from collections.abc import Awaitable
from store.settings_store import SettingsStore
```

2. Modify `__init__` signature to add new params:
```python
class IncrementalIndexer:
    def __init__(
        self,
        store: FalkorDBStore,
        graph_builder: CodeGraphBuilder,
        embedding_gen: EmbeddingGenerator,
        doc_indexer: DocumentIndexer | None = None,
        enricher: CodeSummaryEnricher | None = None,
        repo_task_manager: RepoTaskManager | None = None,
        wiki_incremental_updater: WikiIncrementalUpdater | None = None,
        wiki_auto_updater: Callable[[str], Awaitable[Any]] | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen
        self._doc_indexer = doc_indexer or DocumentIndexer()
        self._enricher = enricher
        self._repo_task_mgr = repo_task_manager
        self._wiki_incremental_updater = wiki_incremental_updater
        self._wiki_auto_updater = wiki_auto_updater
        self._settings_store = settings_store
        self._last_report: IndexReport | None = None
```

3. Add `_check_auto_update_enabled` method (after `enrichment_available` property):
```python
async def _check_auto_update_enabled(self) -> bool:
    """Hot-read from DB, fallback to startup config."""
    if self._settings_store is not None:
        val = await self._settings_store.get("wiki.auto_update_on_index")
        if val is not None:
            return val.strip().lower() in ("true", "1", "yes")
    return get_settings().wiki.auto_update_on_index
```

4. Replace `_maybe_auto_update_wiki` method:
```python
async def _maybe_auto_update_wiki(
    self,
    changed_files: list[tuple[str, str | None, str | None]],
    repository: str | None,
    wiki_config: WikiConfig,
) -> None:
    """When wiki auto-update is enabled, run incremental wiki refresh."""
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_incremental_index_hook.py -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 5: Commit**

```bash
git add indexer/incremental_indexer.py tests/wiki/test_incremental_index_hook.py
git commit -m "feat(indexer): add wiki_auto_updater callback + dynamic settings to IncrementalIndexer"
```

---

### Task 2: Dynamic config — SettingsStore hot-read tests

**Files:**
- Test: `tests/wiki/test_incremental_index_hook.py`

- [ ] **Step 1: Write failing tests for SettingsStore-based dynamic config**

Add to `tests/wiki/test_incremental_index_hook.py`:

```python
@pytest.mark.asyncio
async def test_dynamic_config_db_true() -> None:
    """SettingsStore value 'true' enables auto-update regardless of startup config."""
    from indexer.incremental_indexer import IncrementalIndexer
    from store.settings_store import SettingsStore

    callback = AsyncMock(return_value={"status": "ok"})
    settings_store = AsyncMock(spec=SettingsStore)
    settings_store.get = AsyncMock(return_value="true")

    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_auto_updater=callback,
        settings_store=settings_store,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = False  # startup config says NO

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_awaited_once_with("my-repo")
    settings_store.get.assert_awaited_once_with("wiki.auto_update_on_index")


@pytest.mark.asyncio
async def test_dynamic_config_db_false() -> None:
    """SettingsStore value 'false' disables auto-update even if startup config says True."""
    from indexer.incremental_indexer import IncrementalIndexer
    from store.settings_store import SettingsStore

    callback = AsyncMock()
    settings_store = AsyncMock(spec=SettingsStore)
    settings_store.get = AsyncMock(return_value="false")

    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_auto_updater=callback,
        settings_store=settings_store,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True  # startup config says YES

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_dynamic_config_fallback_no_db_value() -> None:
    """When SettingsStore has no value, fallback to get_settings() default."""
    from indexer.incremental_indexer import IncrementalIndexer
    from store.settings_store import SettingsStore

    callback = AsyncMock(return_value={"status": "ok"})
    settings_store = AsyncMock(spec=SettingsStore)
    settings_store.get = AsyncMock(return_value=None)

    indexer = IncrementalIndexer(
        store=AsyncMock(),
        graph_builder=MagicMock(),
        embedding_gen=MagicMock(),
        wiki_auto_updater=callback,
        settings_store=settings_store,
    )

    fake_settings = MagicMock()
    fake_settings.wiki.auto_update_on_index = True

    with patch("indexer.incremental_indexer.get_settings", return_value=fake_settings):
        await indexer._maybe_auto_update_wiki(
            [("M", "a.py", "a.py")],
            "my-repo",
            wiki_config=WikiConfig(
                repository="my-repo", mode="structure", format="markdown", language="en",
            ),
        )

    callback.assert_awaited_once()
```

- [ ] **Step 2: Run tests to verify they pass (implementation already done in Task 1)**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_incremental_index_hook.py::test_dynamic_config_db_true tests/wiki/test_incremental_index_hook.py::test_dynamic_config_db_false tests/wiki/test_incremental_index_hook.py::test_dynamic_config_fallback_no_db_value -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/wiki/test_incremental_index_hook.py
git commit -m "test(indexer): add SettingsStore-based dynamic config tests for auto-update"
```

---

### Task 3: KnowledgeBaseService + ServiceRegistry — Wiring

**Files:**
- Modify: `services/kb_service.py:44-77,155-166`
- Modify: `services/service_registry.py:28-38,148-165`
- Test: `tests/services/test_kb_service_auto_update_wiring.py` (create)

- [ ] **Step 1: Write failing test for wiring**

Create `tests/services/test_kb_service_auto_update_wiring.py`:

```python
"""Verify KnowledgeBaseService wires wiki_auto_updater callback into IncrementalIndexer."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_kb_service_wires_auto_updater_to_indexer() -> None:
    """IncrementalIndexer created by KnowledgeBaseService has _wiki_auto_updater set."""
    from config import Settings
    from services.kb_service import KnowledgeBaseService
    from store.settings_store import SettingsStore

    settings = MagicMock(spec=Settings)
    settings.falkordb = MagicMock()
    settings.falkordb.password = ""
    settings.falkordb_password = ""
    settings.embedding = MagicMock()
    settings.embedding.dimension = 384
    settings.llm = MagicMock()
    settings.llm.enabled = False
    settings.hybrid_search = MagicMock()
    settings.hybrid_search.use_child_chunks = False
    settings.hybrid_search.child_chunk_window_chars = 512
    settings.hybrid_search.child_chunk_stride_chars = 256
    settings.hybrid_search.child_chunk_min_parent_chars = 256
    settings.hybrid_search.include_raw_docs_in_results = False
    settings.hybrid_search.query_expansion_enabled = False
    settings.hybrid_search.enable_bm25 = False
    settings.hybrid_search.bm25_weight = 0.3
    settings.rerank = MagicMock()
    settings.rerank.enabled = False
    settings.file_extensions = [".py"]
    settings.supported_languages = ["python"]
    settings.exclude_dirs = []
    settings.wiki = MagicMock()
    settings.wiki.community_context_enabled = False

    store = AsyncMock()
    settings_store = AsyncMock(spec=SettingsStore)

    with patch("services.kb_service.EmbeddingGenerator") as mock_emb, \
         patch("services.kb_service.FalkorDBStore"), \
         patch("services.kb_service.WikiSearchService"), \
         patch("services.kb_service.WikiService"), \
         patch("services.kb_service.WikiPipelineAdapter"), \
         patch("services.kb_service.KnowledgeBaseMCPHandler"):
        mock_emb.shared.return_value = MagicMock()

        svc = KnowledgeBaseService.from_components(
            store=store,
            settings=settings,
            settings_store=settings_store,
        )

        assert svc._incremental_indexer._wiki_auto_updater is not None
        assert svc._incremental_indexer._settings_store is settings_store
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/services/test_kb_service_auto_update_wiring.py -v`
Expected: FAIL — `from_components` does not accept `settings_store`

- [ ] **Step 3: Implement KnowledgeBaseService changes**

In `services/kb_service.py`:

1. Add import at top:
```python
from store.settings_store import SettingsStore
```

2. Modify `from_components` to accept `settings_store`:
```python
@classmethod
def from_components(
    cls,
    store: FalkorDBStore,
    settings: Settings,
    *,
    index_task_status_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    repo_registry: Any | None = None,
    settings_store: SettingsStore | None = None,
) -> KnowledgeBaseService:
    """Create a service with a pre-built store (used by ServiceRegistry for per-business instances)."""
    instance = cls.__new__(cls)
    instance._settings = settings
    instance._store = store
    instance._index_task_status_lookup = index_task_status_lookup
    instance._repo_registry = repo_registry
    instance._settings_store = settings_store
    instance._init_components(settings)
    return instance
```

3. In `__init__`, add `self._settings_store = None` before `_init_components`:
```python
def __init__(self, settings: Settings) -> None:
    self._settings = settings
    # ... existing store setup ...
    self._settings_store: SettingsStore | None = None
    self._init_components(settings)
```

4. In `_init_components`, modify `IncrementalIndexer` creation to pass callback + settings_store:
```python
self._incremental_indexer = IncrementalIndexer(
    store=self._store,
    graph_builder=self._graph_builder,
    embedding_gen=self._embedding,
    doc_indexer=self._doc_indexer,
    enricher=self._enricher,
    repo_task_manager=self._repo_task_mgr,
    wiki_auto_updater=self._auto_update_wiki,
    settings_store=getattr(self, "_settings_store", None),
)
```

5. Add `_auto_update_wiki` method after `_init_components`:
```python
async def _auto_update_wiki(self, repository: str) -> Any:
    """Callback for IncrementalIndexer: triggers WikiService.generate_incremental."""
    return await self._wiki_service.generate_incremental(repository)
```

- [ ] **Step 4: Implement ServiceRegistry changes**

In `services/service_registry.py`:

1. Add import:
```python
from store.settings_store import SettingsStore
```

2. Add `settings_store` param to `__init__`:
```python
def __init__(
    self,
    settings: Settings,
    *,
    index_task_status_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    repo_registry: Any | None = None,
    settings_store: SettingsStore | None = None,
) -> None:
    self._settings = settings
    # ... existing ...
    self._settings_store = settings_store
```

3. Pass `settings_store` in `_create_service_once`:
```python
svc = KnowledgeBaseService.from_components(
    store=store,
    settings=self._settings,
    index_task_status_lookup=self._index_task_status_lookup,
    repo_registry=self._repo_registry,
    settings_store=self._settings_store,
)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd knowledge-base-service && python -m pytest tests/services/test_kb_service_auto_update_wiring.py -v`
Expected: PASS

- [ ] **Step 6: Run all existing tests to verify no regressions**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_incremental_index_hook.py tests/services/ -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add services/kb_service.py services/service_registry.py tests/services/test_kb_service_auto_update_wiring.py
git commit -m "feat(wiring): connect wiki_auto_updater callback through ServiceRegistry → KBService → IncrementalIndexer"
```

---

### Task 4: main.py — SettingsStore Lifecycle + Settings Routes Unification

**Files:**
- Modify: `main.py:110-148`
- Modify: `api/routes/settings_routes.py:25-37`
- Test: `tests/api/test_settings_api.py`

- [ ] **Step 1: Write failing test for hot-reload flag**

Add to `tests/api/test_settings_api.py`:

```python
@pytest.mark.asyncio
async def test_batch_update_hot_reload_key_no_restart_required(client):
    resp = await client.put(
        "/api/v1/settings",
        json={"settings": [{"key": "wiki.auto_update_on_index", "value": "true", "category": "wiki"}]},
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restart_required"] is False


@pytest.mark.asyncio
async def test_batch_update_mixed_keys_restart_required(client):
    resp = await client.put(
        "/api/v1/settings",
        json={
            "settings": [
                {"key": "wiki.auto_update_on_index", "value": "true", "category": "wiki"},
                {"key": "llm.model", "value": "gpt-4", "category": "llm"},
            ]
        },
        headers=AUTH_HEADER,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["restart_required"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd knowledge-base-service && python -m pytest tests/api/test_settings_api.py::test_batch_update_hot_reload_key_no_restart_required -v`
Expected: FAIL — `restart_required` is always `True`

- [ ] **Step 3: Implement settings_routes.py changes**

In `api/routes/settings_routes.py`:

1. Add `Request` import and `HOT_RELOAD_KEYS`:
```python
from fastapi import APIRouter, Body, Depends, Path, Request

HOT_RELOAD_KEYS = frozenset({"wiki.auto_update_on_index"})
```

2. Replace `_settings_store` singleton pattern with `app.state`-based injection:
```python
def _get_store(request: Request) -> SettingsStore:
    store = getattr(request.app.state, "settings_store", None)
    if store is None:
        store = SettingsStore()
        request.app.state.settings_store = store
    return store


def _get_service(request: Request) -> SettingsService:
    return SettingsService(_get_store(request))
```

3. Update `update_settings_batch` to return hot-reload flag:
```python
@settings_router.put("")
async def update_settings_batch(
    body: SettingsBatchUpdate,
    request: Request,
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        await service.update_settings([s.model_dump() for s in body.settings])
    except ValueError as e:
        raise KbClientError(str(e)) from e
    all_hot = all(s.key in HOT_RELOAD_KEYS for s in body.settings)
    return {
        "status": "ok",
        "updated": str(len(body.settings)),
        "restart_required": not all_hot,
    }
```

4. Update endpoint function signatures that use `_get_service` or `_get_store` to accept `Request`:
```python
@settings_router.get("")
async def get_all_settings(
    request: Request,
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    ...

@settings_router.get("/{category}")
async def get_category_settings(
    request: Request,
    category: str = Path(...),
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    ...
```

- [ ] **Step 4: Implement main.py changes**

In `main.py`, inside `lifespan` function, after `kb_state.repo_registry = RepoRegistry(...)` and before `kb_state.registry = ServiceRegistry(...)`:

```python
from store.settings_store import SettingsStore
settings_store = SettingsStore()
app.state.settings_store = settings_store
```

Pass `settings_store` to `ServiceRegistry`:
```python
kb_state.registry = ServiceRegistry(
    settings,
    index_task_status_lookup=_index_task_status_for_mcp,
    repo_registry=kb_state.repo_registry,
    settings_store=settings_store,
)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/api/test_settings_api.py -v --timeout=60`
Expected: ALL PASS

- [ ] **Step 6: Run full test suite related to indexer and settings**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_incremental_index_hook.py tests/api/test_settings_api.py tests/services/test_kb_service_auto_update_wiring.py tests/store/test_settings_store.py tests/services/test_settings_service.py -v --timeout=120`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add main.py api/routes/settings_routes.py tests/api/test_settings_api.py
git commit -m "feat(settings): unify SettingsStore lifecycle + add hot-reload flag for wiki.auto_update_on_index"
```

---

### Task 5: Integration Verification

**Files:**
- All modified files from Tasks 1-4

- [ ] **Step 1: Run full wiki-related test suite**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ tests/api/ tests/services/ tests/store/test_settings_store.py -v --timeout=180`
Expected: ALL PASS

- [ ] **Step 2: Verify no import errors or circular dependencies**

Run: `cd knowledge-base-service && python -c "from indexer.incremental_indexer import IncrementalIndexer; from services.kb_service import KnowledgeBaseService; from services.service_registry import ServiceRegistry; print('All imports OK')"`
Expected: "All imports OK"

- [ ] **Step 3: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: resolve any integration issues from wiki auto-update wiring"
```
