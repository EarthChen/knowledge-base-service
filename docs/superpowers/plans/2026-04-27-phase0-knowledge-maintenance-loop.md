# Phase 0: Knowledge Maintenance Loop — Implementation Plan

> **HISTORICAL — see [IMPLEMENTATION-STATUS.md](../../IMPLEMENTATION-STATUS.md) for current state.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the existing `AutoHealer` into `WikiLintService` and enable lint scheduling by default, completing the knowledge maintenance loop.

**Architecture (implemented):** `WikiLintService.run_lint()` runs **lint first** (`lint()`), then **conditionally** `AutoHealer` (via `heal()` → `run_all()`), merges `heal` results, and persists heal metrics to `WikiChangeLog` when a changelog store is available. `WikiConfig` defaults: `lint_scheduler_enabled=True`, `auto_heal_enabled=True`. `LintScheduler` is started from application lifespan when `lint_scheduler_enabled`, and calls `run_lint` so scheduled runs match HTTP/MCP.

**Tech Stack:** Python 3.12+, FastAPI, FalkorDB, pytest

---

## Codebase reality check (read before implementation)

| Topic | Current state | Plan action |
|--------|----------------|-------------|
| `AutoHealer` | `async def run_all(self, repository: str) -> dict[str, Any]`; **no** `heal()` | Add **`async def heal(self, repository: str) -> dict[str, Any]`** that delegates to `run_all` (spec/API compatibility). |
| `WikiLintService` | `async def lint(...)` returns `LintReport`; **no** `run_lint` | Add **`run_lint`** that returns a **unified `dict`**: `LintReport.to_dict()` fields at top level **plus** `auto_heal` (or `null` when disabled). |
| `LintScheduler` | Calls `service.lint(repo)` | Switch to **`await service.run_lint(repo, scope="all")`** and read `len(result.get("issues", []))` for logging. |
| `main.py` / lifespan | `wiki_lint_service_factory` set; **LintScheduler never started** | After `bootstrap_wiki`, if `settings.wiki.lint_scheduler_enabled`, create **`LintScheduler`**, `start()`, attach **`app.state.wiki_lint_scheduler`**, stop in lifespan shutdown. |
| `wiki_lint_service_factory` | No `wiki_changelog_store` passed | Pass **`wiki_changelog_store=getattr(app.state, "wiki_changelog_store", None)`** (factory runs **after** `bootstrap_wiki` on first request, or at scheduler tick — at those times `app.state.wiki_changelog_store` exists). For consistency, set **`app.state.wiki_lint_service_factory`** **after** `await bootstrap_wiki(...)` **or** ensure factory only reads `app.state` at invocation time (closure over `app` is already correct). |
| Order | — | **Strict:** `lint()` → collect report → (if `auto_heal_enabled`) `heal()` → merge → (optional) changelog → return. |

**Working directory** for all commands:  
`/Users/earthchen/ai-work/agent-work/knowledge-base-service`

**Pytest** (project adds `--cov` by default): use `pytest <path> -q` for a single file; add `--no-cov` if you want a faster local loop:  
`pytest tests/wiki/test_auto_healer.py -q --no-cov`

**Full verify** (as required before claiming completion):  
`pytest -q`  
(Expect the full suite; project references “1722+” tests in the spec.)

**Git:** After each **task** (or each **step** if you prefer finer granularity), commit, e.g. `git add -A && git commit -m "feat(wiki): ..."`.

---

## Task 1 — `AutoHealer.heal()` alias (TDD: failing test first)

**Files:** `wiki/auto_healer.py`, `tests/wiki/test_auto_healer.py`

- [x] **Step 1.1 (failing test):** In `tests/wiki/test_auto_healer.py`, add `test_heal_delegates_to_run_all` **before** implementation.

**Complete test to add**

```python
@pytest.mark.asyncio
async def test_heal_delegates_to_run_all() -> None:
    mock_store = MagicMock()
    mock_store.delete_broken_wiki_references = AsyncMock(return_value=1)
    mock_store.deprecate_orphan_wiki_pages = AsyncMock(return_value=2)
    healer = AutoHealer(mock_store)
    result = await healer.heal("my-repo")
    assert result["refs_removed"] == 1
    assert result["pages_deprecated"] == 2
    mock_store.delete_broken_wiki_references.assert_awaited_once_with("my-repo")
    mock_store.deprecate_orphan_wiki_pages.assert_awaited_once_with("my-repo")
```

**Command:** `pytest tests/wiki/test_auto_healer.py::test_heal_delegates_to_run_all -q --no-cov`  
**Expected (before fix):** `AttributeError: 'AutoHealer' object has no attribute 'heal'`

- [x] **Step 1.2 (implementation):** In `wiki/auto_healer.py`, add:

```python
    async def heal(self, repository: str) -> dict[str, Any]:
        """Run all auto-heal steps (alias for :meth:`run_all`)."""
        return await self.run_all(repository)
```

- [x] **Step 1.3:** Re-run: `pytest tests/wiki/test_auto_healer.py -q --no-cov` — **all tests in file pass**

- [x] **Step 1.4:** `git commit -m "feat(wiki): add AutoHealer.heal() delegating to run_all"`

---

## Task 2 — `WikiChangeLogStore`: store heal metrics on changelog rows

**Files:** `store/wiki_changelog.py`, `tests/store/test_wiki_changelog.py`

- [x] **Step 2.1 (failing test):** Extend `tests/store/test_wiki_changelog.py` (or add a new test) so `persist_changelog` with heal kwargs issues a Cypher that includes `heal_refs_removed` and `heal_pages_deprecated` (or assert `execute_query` was called with params containing the counts).

**Example test (complete)**

```python
import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_persist_changelog_includes_heal_fields() -> None:
    from store.wiki_changelog import WikiChangeLogStore

    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock()
    store = WikiChangeLogStore(mock_graph)
    uid = await store.persist_changelog(
        "acme/r",
        "lint_auto_heal",
        [],
        0,
        files_changed=[],
        errors=[],
        heal_refs_removed=3,
        heal_pages_deprecated=4,
    )
    assert uid.startswith("WikiChangeLog:")
    call_args = mock_graph.execute_query.call_args
    assert "heal_refs_removed" in call_args[0][0] or "heal" in call_args[0][0]
    params = call_args[0][1]
    assert params["heal_refs"] == 3
    assert params["heal_pages"] == 4
```

Adjust the assertion to match the exact param names you use in Cypher (e.g. `$heal_refs` / `$heal_pages`).

**Command:** `pytest tests/store/test_wiki_changelog.py -k heal -q --no-cov`  
**Expected (before fix):** `TypeError: persist_changelog() got an unexpected keyword argument...`

- [x] **Step 2.2 (implementation):** Update `WikiChangeLogStore.persist_changelog` **signature** (backward compatible — new args **optional, default `None`**):

```python
    async def persist_changelog(
        self,
        repository: str,
        trigger: str,
        pages_affected: list[str],
        pages_regenerated: int,
        files_changed: list[str] | None = None,
        errors: list[str] | None = None,
        *,
        heal_refs_removed: int | None = None,
        heal_pages_deprecated: int | None = None,
    ) -> str:
```

Extend the `cypher` `CREATE` to set:

```text
  heal_refs_removed: $heal_refs,
  heal_pages_deprecated: $heal_pages
```

**Params dict** (example):

```python
        "heal_refs": int(heal_refs_removed) if heal_refs_removed is not None else 0,
        "heal_pages": int(heal_pages_deprecated) if heal_pages_deprecated is not None else 0,
```

- [x] **Step 2.3:** `pytest tests/store/test_wiki_changelog.py -q --no-cov` — pass

- [x] **Step 2.4:** `git commit -m "feat(store): persist auto-heal counts on WikiChangeLog"`

---

## Task 3 — `WikiLintService.run_lint()` (lint → heal → merge → changelog)

**Files:** `wiki/lint.py`, `tests/wiki/test_lint.py` (new tests file `tests/wiki/test_lint_run_lint.py` is OK if you prefer isolation)

- [x] **Step 3.1 (failing test):** Add tests that **mock** `WikiLintService.lint` and `AutoHealer.heal` (patch `wiki.lint.AutoHealer` or inject via module patch).

**Complete test file** `tests/wiki/test_lint_run_lint.py` (new file recommended)

```python
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import WikiConfig
from wiki.lint import LintReport, WikiLintService


def _make_report() -> LintReport:
    return LintReport(
        issues=[],
        stats={"total": 0, "errors": 0, "warnings": 0, "info": 0},
        checked_at="t0",
        scope="all",
    )


@pytest.mark.asyncio
async def test_run_lint_merges_heal_when_auto_heal_enabled() -> None:
    mock_store = MagicMock()
    mock_store.list_wiki_pages_for_repo = AsyncMock(return_value=MagicMock(data=[]))
    # ... stub any other methods lint() may call on your mock graph; prefer patching lint:
    cfg = MagicMock(spec=WikiConfig)
    cfg.auto_heal_enabled = True
    cfg.contradiction_detection_enabled = False
    cfg.confidence_scoring_enabled = False
    cfg.forgetting_enabled = False
    cfg.memory_tiers_enabled = False
    cfg.schema_validation_enabled = False

    svc = WikiLintService(
        mock_store,
        wiki_config=cfg,
    )
    with patch.object(svc, "lint", new_callable=AsyncMock) as m_lint:
        m_lint.return_value = _make_report()
        with patch("wiki.lint.AutoHealer") as m_heal_cls:
            m_heal = MagicMock()
            m_heal.heal = AsyncMock(return_value={"refs_removed": 5, "pages_deprecated": 1})
            m_heal_cls.return_value = m_heal
            out = await svc.run_lint("repo-a", scope="all")
    assert out["scope"] == "all"
    assert out["auto_heal"] == {"refs_removed": 5, "pages_deprecated": 1}
    m_heal.heal.assert_awaited_once_with("repo-a")
    m_lint.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_lint_skips_heal_when_auto_heal_disabled() -> None:
    mock_store = MagicMock()
    cfg = MagicMock(spec=WikiConfig)
    cfg.auto_heal_enabled = False
    cfg.contradiction_detection_enabled = False
    cfg.confidence_scoring_enabled = False
    cfg.forgetting_enabled = False
    cfg.memory_tiers_enabled = False
    cfg.schema_validation_enabled = False

    svc = WikiLintService(mock_store, wiki_config=cfg)
    with patch.object(svc, "lint", new_callable=AsyncMock) as m_lint:
        m_lint.return_value = _make_report()
        with patch("wiki.lint.AutoHealer") as m_heal_cls:
            out = await svc.run_lint("repo-b", scope="all")
    assert out.get("auto_heal") is None
    m_heal_cls.assert_not_called()
```

**Note:** You may need to **stub** `mock_store` methods that `lint()` touches for your project’s `WikiLintService.lint` implementation, **or** keep using `patch.object(svc, "lint", ...)` as above so the real `lint` body does not run. The patch approach is the intended minimal unit test.

**Command:** `pytest tests/wiki/test_lint_run_lint.py -q --no-cov`  
**Expected (before `run_lint` exists):** `AttributeError` on `run_lint`

- [x] **Step 3.2 (implementation):** In `wiki/lint.py`:

1. **Constructor:** add optional `wiki_changelog_store: Any | None = None` (or import `WikiChangeLogStore` and type it) and assign `self._wiki_changelog_store`.
2. Add **`async def run_lint(self, repository: str, *, scope: str = "all") -> dict[str, Any]:`**:

**Complete method (drop-in)**

```python
    async def run_lint(self, repository: str, *, scope: str = "all") -> dict[str, Any]:
        """Run wiki lint, then optional auto-heal; return a unified dict for APIs and schedulers.

        Order: ``lint`` (collect issues) → ``AutoHealer.heal`` (if enabled) → merge.
        """
        report = await self.lint(repository, scope=scope)
        body: dict[str, Any] = report.to_dict()
        body["auto_heal"] = None

        c = self._wiki_config
        if c is not None and bool(getattr(c, "auto_heal_enabled", False)):
            from wiki.auto_healer import AutoHealer

            healer = AutoHealer(self._wiki_store)
            heal_result = await healer.heal(repository)
            body["auto_heal"] = heal_result

            cl = getattr(self, "_wiki_changelog_store", None)
            if cl is not None and heal_result is not None:
                try:
                    await cl.persist_changelog(
                        repository,
                        "lint_auto_heal",
                        [],
                        0,
                        files_changed=[],
                        errors=[],
                        heal_refs_removed=int(heal_result.get("refs_removed", 0) or 0),
                        heal_pages_deprecated=int(heal_result.get("pages_deprecated", 0) or 0),
                    )
                except Exception:  # noqa: BLE001 — observability must not break lint
                    log.warning("lint_auto_heal_changelog_failed", repository=repository, exc_info=True)

        return body
```

`Any` and `log` are already available at module level in `wiki/lint.py`.

- [x] **Step 3.3:** `pytest tests/wiki/test_lint_run_lint.py -q --no-cov` — pass

- [x] **Step 3.4:** `git commit -m "feat(wiki): add WikiLintService.run_lint with heal merge and changelog"`

---

## Task 4 — HTTP route + MCP + factory: use `run_lint`

**Files:** `api/routes/wiki_feedback_routes.py`, `wiki/mcp_tools.py`, `main.py` (lint factory), optionally `api/routes/wiki_shared.py` if a shared builder exists

- [x] **Step 4.1 (failing test / update):** Update `tests/api/test_wiki_lint_api.py` to mock **`run_lint`** instead of **`lint`**, return body including `auto_heal: None`:

**Replace mock block (illustration)**

```python
    async def _fake_run_lint(repo: str, scope: str = "all") -> dict:
        return {
            "issues": [],
            "stats": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
            "checked_at": "2026-01-01T00:00:00+00:00",
            "scope": scope,
            "auto_heal": None,
        }

    mock_lint.run_lint = AsyncMock(side_effect=_fake_run_lint)
```

**Route change:** in `api/routes/wiki_feedback_routes.py` `wiki_lint` handler, replace:

```python
    report = await lint_svc.lint(repository, scope=scope)
    return report.to_dict()
```

**With:**

```python
    return await lint_svc.run_lint(repository, scope=scope)
```

- [x] **Step 4.2:** In `wiki/mcp_tools.py` `handle_wiki_lint`, replace `report = await svc.lint(...); return {"status": "success", **report.to_dict()}` with:

```python
            payload = await svc.run_lint(repository, scope=scope)
        except Exception:
            ...
        return {"status": "success", **payload}
```

(Keep exception handling; ensure you do not double-wrap `status`.)

- [x] **Step 4.3:** In `main.py` `wiki_lint_service_factory`, add **`wiki_changelog_store=None`** in the `WikiLintService(...)` call — use **`getattr(app.state, "wiki_changelog_store", None)`** so each invocation picks up the store created in `wiki/bootstrap.py`.

**Complete factory fragment**

```python
        return WikiLintService(
            kb.store,
            wiki_cache=getattr(app.state, "wiki_cache", None),
            repo_registry=kb_state.repo_registry,
            wiki_config=settings.wiki,
            contradiction_detector=det,
            wiki_changelog_store=getattr(app.state, "wiki_changelog_store", None),
        )
```

**Note:** `WikiLintService.__init__` must accept `wiki_changelog_store=` (Task 3).

- [x] **Step 4.4:** `pytest tests/api/test_wiki_lint_api.py -q --no-cov` — pass

- [x] **Step 4.5:** `git commit -m "feat(api): expose unified run_lint from HTTP and MCP wiki_lint"`

- [x] **Step 4.6:** Grep for `WikiLintService(` and add keyword `wiki_changelog_store=...` only where a dedicated factory instantiates the service (e.g. `wiki/mcp_tools.py` if it creates its own `WikiLintService` without changelog — that path will not get changelog unless you pass a store; optional follow-up, not required for `main` factory). Run `pytest tests/wiki/test_lint.py -q --no-cov` to catch signature regressions.

---

## Task 5 — `LintScheduler` calls `run_lint`

**Files:** `wiki/lint_scheduler.py`, `tests/wiki/test_lint_scheduler.py`

- [x] **Step 5.1 (failing test):** In `tests/wiki/test_lint_scheduler.py`, change mock from `lint` to `run_lint` returning a **dict** compatible with the new shape:

**Complete test replacement (core part)**

```python
    mock_lint_service = AsyncMock()
    mock_lint_service.run_lint = AsyncMock(
        return_value={
            "issues": [],
            "stats": {"total": 0, "errors": 0, "warnings": 0, "info": 0},
            "checked_at": "",
            "scope": "all",
            "auto_heal": None,
        },
    )
```

Assert `mock_lint_service.run_lint.assert_called()`.

- [x] **Step 5.2:** In `wiki/lint_scheduler.py` `_loop`:

**Replace**

```python
                    result = await service.lint(repo)
                    log.info(
                        "lint_scheduler_repo_completed",
                        repository=repo,
                        issues=len(result.issues) if result is not None else 0,
                    )
```

**With**

```python
                    result = await service.run_lint(repo, scope="all")
                    issues = result.get("issues", []) if isinstance(result, dict) else []
                    log.info(
                        "lint_scheduler_repo_completed",
                        repository=repo,
                        issues=len(issues),
                    )
```

- [x] **Step 5.3:** `pytest tests/wiki/test_lint_scheduler.py -q --no-cov` — pass

- [x] **Step 5.4:** `git commit -m "feat(wiki): LintScheduler uses run_lint for heal pipeline"`

---

## Task 6 — Start / stop `LintScheduler` in lifespan (config-gated)

**Files:** `main.py`

- [x] **Step 6.1 (failing test — optional but recommended):** Add `tests/test_main_lint_scheduler_lifespan.py` using `httpx`/`TestClient` with lifespan, **mock** `get_settings` / registry — only if the team wants coverage; otherwise manual verification is acceptable. Minimal pattern: `with TestClient(app) as c:` and assert `app.state.wiki_lint_scheduler` exists when config mocked to enabled.

**Skip** if time-boxed; document manual: start app with `WIKI__LINT_SCHEDULER_ENABLED=true` and check logs for `lint_scheduler_repo_completed` after interval (not ideal for CI).

- [x] **Step 6.2 (implementation):** **After** `await bootstrap_wiki(app, settings)` in `main.py` lifespan, add:

**Complete block**

```python
    app.state.wiki_lint_scheduler = None
    if settings.wiki.lint_scheduler_enabled:
        from wiki.lint_scheduler import LintScheduler

        def _list_repos() -> list[str]:
            reg = kb_state.repo_registry
            if reg is None:
                return []
            return [str(e["repository"]) for e in reg.list_all() if e.get("repository")]

        interval = float(max(1, settings.wiki.lint_scheduler_interval_hours) * 3600)
        lint_sched = LintScheduler(
            app.state.wiki_lint_service_factory,
            repositories=_list_repos,
            interval_seconds=interval,
        )
        lint_sched.start()
        app.state.wiki_lint_scheduler = lint_sched
        log.info(
            "wiki_lint_scheduler_started",
            interval_hours=settings.wiki.lint_scheduler_interval_hours,
        )
```

**Shutdown (before** `teardown_wiki` **or after — prefer before closing registry if scheduler needs graph):** 

```python
    ls = getattr(app.state, "wiki_lint_scheduler", None)
    if ls is not None:
        await ls.stop()
        app.state.wiki_lint_scheduler = None
```

Place `await ls.stop()` in the `yield` cleanup section with other `await` stops.

- [x] **Step 6.3:** Run: `python -c "from main import create_app; create_app()"` to ensure no import errors

- [x] **Step 6.4:** `git commit -m "feat(main): start LintScheduler from lifespan when enabled"`

---

## Task 7 — `WikiConfig` default flags

**File:** `config.py`

- [x] **Step 7.1 (failing test):** Add `tests/test_wiki_config_defaults.py` (or extend existing config test):

```python
from config import WikiConfig


def test_wiki_lint_and_auto_heal_defaults_enabled() -> None:
    c = WikiConfig()
    assert c.lint_scheduler_enabled is True
    assert c.auto_heal_enabled is True
```

**Command:** `pytest tests/test_wiki_config_defaults.py -q --no-cov` — fails before edit

- [x] **Step 7.2:** In `config.py` `WikiConfig`:

```python
    lint_scheduler_enabled: bool = True
    ...
    auto_heal_enabled: bool = True
```

- [x] **Step 7.3:** `pytest tests/test_wiki_config_defaults.py -q --no-cov` — pass

- [x] **Step 7.4:** `git commit -m "feat(config): enable lint scheduler and auto-heal by default"`

---

## Task 8 — Documentation: `docs/DEPLOYMENT.md`

**File:** `docs/DEPLOYMENT.md`

- [x] **Step 8.1:** Update the table row for `WIKI__LINT_SCHEDULER_ENABLED` default from `false` to `true` (and add a one-line note that auto-heal follows `WIKI__AUTO_HEAL_ENABLED`, default `true`).

- [x] **Step 8.2:** `git commit -m "docs: update deployment defaults for phase0 maintenance loop"`

---

## Task 9 — Full verification

- [x] **Step 9.1:** `pytest -q` from project root (expect full suite green; if coverage or unrelated flakes occur, run twice).

**Expected output pattern:** `... passed` / summary with **0** failures

- [x] **Step 9.2:** (Optional) `ruff check wiki api store main.py` if the project uses Ruff (see `pyproject.toml`)

- [x] **Step 9.3:** Final commit if any fixups: `git commit -m "chore: phase0 knowledge maintenance loop verification fixes"`

---

## Out of scope (do not block Phase 0)

- Incremental ingest post-hook that calls `run_lint` (spec §2.2.3 **optional**).
- Physical deletion of pages (AutoHealer only removes edges and marks orphans deprecated — already documented in `auto_healer.py`).

---

## Checklist (success criteria from spec, mapped)

- [x] `WIKI__AUTO_HEAL_ENABLED` true (default after Task 8) results in `run_lint` invoking `AutoHealer.heal` after lint
- [x] Dangling `WIKI_REFERENCES` and orphan deprecations are applied via existing store methods (already covered by `tests/wiki/test_auto_healer.py`)
- [x] `WikiChangeLog` receives heal counts when changelog store is attached
- [x] `LintScheduler` runs `run_lint` and starts when `lint_scheduler_enabled` is true (and `main` wires it)
- [x] Full pytest run passes
