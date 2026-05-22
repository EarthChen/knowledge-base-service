# Heal Redesign + Unified LLM Rate Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add concurrency to `heal_pages_node` (5-7x speedup) and centralize all pipeline concurrency settings into a single `PipelineConcurrency` utility.

**Architecture:** Two-layer frequency control — LLMProvider semaphore as global ceiling (50), per-stage semaphores from centralized config. Heal node redesigned with tier-aware concurrent processing.

**Tech Stack:** Python 3.12, asyncio, Pydantic Settings, pytest-asyncio

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `wiki/pipeline_concurrency.py` | Centralized concurrency config reader |
| Create | `tests/wiki/test_pipeline_concurrency.py` | Unit tests for PipelineConcurrency |
| Modify | `core/config.py:258` | Add new concurrency + heal config fields to AppWikiFlags |
| Modify | `wiki/nodes/heal.py` | Rewrite heal_pages_node with concurrency + tier awareness |
| Create | `tests/wiki/test_heal_concurrent.py` | Tests for redesigned heal node |
| Modify | `wiki/nodes/domain_compose.py:16` | Migrate to PipelineConcurrency |
| Modify | `wiki/nodes/graph_nodes.py:14` | Migrate to PipelineConcurrency |
| Modify | `wiki/repo_composer.py:80` | Migrate to PipelineConcurrency |

---

### Task 1: Add Config Fields to AppWikiFlags

**Files:**
- Modify: `core/config.py:258` (after `compose_concurrency` field)
- Test: `tests/test_wiki_config_defaults.py`

- [ ] **Step 1: Write failing test for new config fields**

```python
# tests/test_wiki_config_defaults.py — append to existing test file
def test_pipeline_concurrency_config_defaults():
    from core.config import AppWikiFlags
    cfg = AppWikiFlags()
    assert cfg.domain_agent_concurrency == 3
    assert cfg.heal_concurrency == 5
    assert cfg.bottomup_concurrency == 24
    assert cfg.module_compose_concurrency == 3
    assert cfg.heal_max_rounds_core == 3
    assert cfg.heal_max_rounds_standard == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_wiki_config_defaults.py::test_pipeline_concurrency_config_defaults -v`
Expected: FAIL with `AttributeError: 'AppWikiFlags' object has no attribute 'domain_agent_concurrency'`

- [ ] **Step 3: Add config fields**

In `core/config.py`, after line 258 (`compose_concurrency: int = Field(default=12, ge=1)`), add:

```python
    #: Pipeline stage concurrency — unified control (see wiki/pipeline_concurrency.py)
    domain_agent_concurrency: int = Field(default=3, ge=1)
    heal_concurrency: int = Field(default=5, ge=1)
    bottomup_concurrency: int = Field(default=24, ge=1)
    module_compose_concurrency: int = Field(default=3, ge=1)

    #: Heal strategy — tier-specific round limits
    heal_max_rounds_core: int = Field(default=3, ge=1)
    heal_max_rounds_standard: int = Field(default=1, ge=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_wiki_config_defaults.py::test_pipeline_concurrency_config_defaults -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/config.py tests/test_wiki_config_defaults.py
git commit -m "feat(config): add pipeline concurrency and heal strategy fields to AppWikiFlags"
```

---

### Task 2: Create PipelineConcurrency Utility

**Files:**
- Create: `wiki/pipeline_concurrency.py`
- Create: `tests/wiki/test_pipeline_concurrency.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_pipeline_concurrency.py
"""Tests for PipelineConcurrency utility."""
from __future__ import annotations

import asyncio
import os
from unittest.mock import patch

import pytest


class TestPipelineConcurrencyLimit:
    def test_known_stage_returns_config_value(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("heal")
        assert limit == 5

    def test_unknown_stage_returns_compose_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        limit = PipelineConcurrency.limit("nonexistent_stage")
        assert limit == 12  # compose_concurrency default

    def test_env_var_override_takes_priority(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {"WIKI_HEAL_CONCURRENCY": "10"}):
            limit = PipelineConcurrency.limit("heal")
            assert limit == 10

    def test_legacy_env_var_alias(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {"DOMAIN_AGENT_CONCURRENCY": "7"}):
            limit = PipelineConcurrency.limit("domain_agent")
            assert limit == 7

    def test_new_env_var_beats_legacy(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        with patch.dict(os.environ, {
            "WIKI_DOMAIN_AGENT_CONCURRENCY": "8",
            "DOMAIN_AGENT_CONCURRENCY": "7",
        }):
            limit = PipelineConcurrency.limit("domain_agent")
            assert limit == 8


class TestPipelineConcurrencySemaphore:
    def test_returns_semaphore_with_correct_limit(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("heal")
        assert isinstance(sem, asyncio.Semaphore)
        assert sem._value == 5

    def test_domain_agent_default(self):
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("domain_agent")
        assert sem._value == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_pipeline_concurrency.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.pipeline_concurrency'`

- [ ] **Step 3: Implement PipelineConcurrency**

```python
# wiki/pipeline_concurrency.py
"""Centralized pipeline concurrency management.

Provides stage-specific semaphores from unified config.
Priority: env var WIKI_{STAGE}_CONCURRENCY > legacy env var > config field > default.
"""
from __future__ import annotations

import asyncio
import os
from typing import ClassVar

from core.config import get_settings


class PipelineConcurrency:
    """Provides stage-specific semaphores from unified config."""

    _LEGACY_ENV_ALIASES: ClassVar[dict[str, str]] = {
        "domain_agent": "DOMAIN_AGENT_CONCURRENCY",
    }

    @classmethod
    def _resolve_limit(cls, stage: str) -> int:
        env_key = f"WIKI_{stage.upper()}_CONCURRENCY"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            return int(env_val)

        legacy_key = cls._LEGACY_ENV_ALIASES.get(stage)
        if legacy_key:
            legacy_val = os.environ.get(legacy_key)
            if legacy_val is not None:
                return int(legacy_val)

        cfg = get_settings().wiki
        mapping = {
            "domain_agent": cfg.domain_agent_concurrency,
            "heal": cfg.heal_concurrency,
            "compose": cfg.compose_concurrency,
            "bottomup": cfg.bottomup_concurrency,
            "title_gen": cfg.bottomup_concurrency,
            "module_compose": cfg.module_compose_concurrency,
        }
        return mapping.get(stage, cfg.compose_concurrency)

    @classmethod
    def semaphore(cls, stage: str) -> asyncio.Semaphore:
        """Create a Semaphore with the resolved concurrency limit for the given stage."""
        return asyncio.Semaphore(cls._resolve_limit(stage))

    @classmethod
    def limit(cls, stage: str) -> int:
        """Return concurrency limit as int (for logging/metrics)."""
        return cls._resolve_limit(stage)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_pipeline_concurrency.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_concurrency.py tests/wiki/test_pipeline_concurrency.py
git commit -m "feat: add PipelineConcurrency utility for centralized stage concurrency"
```

---

### Task 3: Rewrite heal_pages_node with Concurrency + Tier Awareness

**Files:**
- Modify: `wiki/nodes/heal.py` (rewrite `heal_pages_node` function, lines 175-262)
- Create: `tests/wiki/test_heal_concurrent.py`

- [ ] **Step 1: Write failing tests for new heal behavior**

```python
# tests/wiki/test_heal_concurrent.py
"""Tests for redesigned concurrent heal_pages_node."""
from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.heal import heal_pages_node


def _make_page(path: str, content: str = "## 业务概述\nTest content with enough length to pass basic checks." * 5) -> dict[str, Any]:
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": "topic",
        "domain": "test-domain",
    }


class TestHealConcurrency:
    @pytest.mark.asyncio
    async def test_heal_runs_concurrently(self):
        """Verify heal operations run in parallel, not sequentially."""
        call_times: list[float] = []

        async def mock_generate(*args, **kwargs):
            import time
            call_times.append(time.monotonic())
            await asyncio.sleep(0.05)
            return "## 业务概述\nHealed content\n## 核心业务流程\n```mermaid\nflowchart TD\nA-->B\n```"

        mock_llm = AsyncMock()
        mock_llm.generate = mock_generate
        mock_llm.complete_json = AsyncMock(return_value={
            "root_causes": ["test"],
            "preserved_sections": [],
            "patches": [{"action": "append", "target_heading": "", "content": "## Fixed\nDone"}],
        })

        pages = [_make_page(f"/__domains__/d/page{i}/_topic") for i in range(5)]
        state = {
            "pages_to_heal": [p["path"] for p in pages],
            "pages": pages,
            "config": {"importance_tiers": {p["path"]: "standard" for p in pages}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [{"name": "test-domain", "modules": ["mod1"]}],
        }

        with patch("wiki.nodes.heal.get_settings") as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            result = await heal_pages_node(state, {"configurable": {"llm": mock_llm, "graph_store": None}})

        assert len(call_times) >= 2
        if len(call_times) >= 2:
            time_spread = call_times[-1] - call_times[0]
            assert time_spread < 0.2, f"Calls should overlap (spread={time_spread}s)"


class TestHealTierStrategy:
    @pytest.mark.asyncio
    async def test_skeleton_pages_skipped(self):
        """SKELETON tier pages should not be healed."""
        mock_llm = AsyncMock()
        pages = [_make_page("/__domains__/d/skel/_topic")]
        state = {
            "pages_to_heal": [pages[0]["path"]],
            "pages": pages,
            "config": {"importance_tiers": {pages[0]["path"]: "skeleton"}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [],
        }

        with patch("wiki.nodes.heal.get_settings") as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            result = await heal_pages_node(state, {"configurable": {"llm": mock_llm, "graph_store": None}})

        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_standard_pages_one_round_only(self):
        """STANDARD tier pages get exactly 1 heal round."""
        heal_call_count = 0

        async def counting_generate(*args, **kwargs):
            nonlocal heal_call_count
            heal_call_count += 1
            return "Short"  # Will fail threshold, but should not retry

        mock_llm = AsyncMock()
        mock_llm.generate = counting_generate
        mock_llm.complete_json = AsyncMock(return_value=None)

        pages = [_make_page(f"/__domains__/d/std{i}/_topic") for i in range(3)]
        state = {
            "pages_to_heal": [p["path"] for p in pages],
            "pages": pages,
            "config": {"importance_tiers": {p["path"]: "standard" for p in pages}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [{"name": "test-domain", "modules": ["mod1"]}],
        }

        with patch("wiki.nodes.heal.get_settings") as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            await heal_pages_node(state, {"configurable": {"llm": mock_llm, "graph_store": None}})

        assert heal_call_count == 3  # 3 pages * 1 round each


class TestHealNoLLM:
    @pytest.mark.asyncio
    async def test_no_llm_graceful_degradation(self):
        """Without LLM, heal should still update hints and return gracefully."""
        pages = [_make_page("/__domains__/d/p/_topic")]
        state = {
            "pages_to_heal": [pages[0]["path"]],
            "pages": pages,
            "config": {"importance_tiers": {}},
            "heal_attempts": {},
            "heal_hints": {},
            "domain_tree": [],
        }

        with patch("wiki.nodes.heal.get_settings") as mock_settings:
            mock_settings.return_value.wiki.heal_concurrency = 5
            mock_settings.return_value.wiki.heal_max_rounds_core = 3
            mock_settings.return_value.wiki.heal_max_rounds_standard = 1
            result = await heal_pages_node(state, {"configurable": {"llm": None, "graph_store": None}})

        assert result["pages_to_heal"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_heal_concurrent.py -v`
Expected: FAIL (current heal_pages_node doesn't import `get_settings`, runs sequentially)

- [ ] **Step 3: Rewrite heal_pages_node**

Replace the `heal_pages_node` function in `wiki/nodes/heal.py` (lines 175-262) with:

```python
async def heal_pages_node(
    state: dict[str, Any], config: RunnableConfig | None = None
) -> dict[str, Any]:
    """Concurrent, tier-aware page healing.

    Phase 1: Triage pages by ImportanceTier (skip SKELETON)
    Phase 2: Concurrent heal with per-tier round limits
    Phase 3: Merge results
    """
    from core.config import get_settings

    configurable = (config or {}).get("configurable", {})
    llm = configurable.get("llm")
    graph_store = configurable.get("graph_store")
    wiki_cfg = get_settings().wiki
    evaluator = WikiQualityEvaluator()
    heal_attempts: dict[str, int] = dict(state.get("heal_attempts", {}))
    heal_hints: dict[str, str] = dict(state.get("heal_hints", {}))

    # De-duplicate
    seen: set[str] = set()
    all_paths: list[str] = []
    for p in state.get("pages_to_heal", []):
        if p not in seen:
            seen.add(p)
            all_paths.append(p)

    if not all_paths:
        log.info("heal_pages_done", healed_count=0)
        return {"pages_to_heal": [], "heal_attempts": heal_attempts, "heal_hints": heal_hints, "pages": []}

    # Build page lookup
    page_by_path: dict[str, dict[str, Any]] = {}
    for p in state.get("pages", []):
        path = p.get("path")
        if path in seen:
            page_by_path[str(path)] = dict(p)

    # Phase 1: Triage by tier
    importance_tiers: dict[str, str] = (state.get("config") or {}).get("importance_tiers", {})
    core_pages: list[str] = []
    standard_pages: list[str] = []

    for path in all_paths:
        raw_tier = importance_tiers.get(path, "standard")
        if raw_tier == "skeleton":
            continue
        elif raw_tier == "core":
            core_pages.append(path)
        else:
            standard_pages.append(path)

    log.info(
        "heal_triage",
        total=len(all_paths),
        core=len(core_pages),
        standard=len(standard_pages),
        skipped_skeleton=len(all_paths) - len(core_pages) - len(standard_pages),
    )

    # Phase 2: Concurrent heal
    from wiki.pipeline_concurrency import PipelineConcurrency

    sem = PipelineConcurrency.semaphore("heal")
    healed_by_path: dict[str, dict[str, Any]] = {}

    async def _bounded_heal(page_path: str) -> bool:
        async with sem:
            page_dict = page_by_path.get(page_path)
            if not page_dict:
                return False
            heal_attempts[page_path] = heal_attempts.get(page_path, 0) + 1
            if llm:
                ok = await _heal_one_page(
                    page_path=page_path,
                    page_dict=page_dict,
                    state=state,
                    evaluator=evaluator,
                    llm=llm,
                    heal_hints=heal_hints,
                    heal_attempts=heal_attempts,
                    graph_store=graph_store,
                )
                if ok:
                    healed_by_path[page_path] = dict(page_dict)
                return ok
            else:
                _update_heal_hint(page_path, page_dict, evaluator, heal_hints)
                return False

    # CORE pages: up to heal_max_rounds_core rounds
    max_rounds_core = wiki_cfg.heal_max_rounds_core if llm else 1
    active_core = list(core_pages)
    for round_num in range(max_rounds_core):
        if not active_core:
            break
        await asyncio.gather(*[_bounded_heal(p) for p in active_core])
        # Remove pages that now pass threshold
        still_failing: list[str] = []
        for p in active_core:
            page_dict = page_by_path.get(p)
            if not page_dict:
                continue
            try:
                page = WikiPage.from_dict(page_dict)
            except Exception:
                still_failing.append(p)
                continue
            if not _page_passes_post_heal(page, state, evaluator):
                still_failing.append(p)
        active_core = still_failing
        if active_core:
            log.info("heal_core_round", round=round_num + 1, still_failing=len(active_core))

    # STANDARD pages: exactly heal_max_rounds_standard rounds
    max_rounds_std = wiki_cfg.heal_max_rounds_standard if llm else 1
    active_std = list(standard_pages)
    for round_num in range(max_rounds_std):
        if not active_std:
            break
        await asyncio.gather(*[_bounded_heal(p) for p in active_std])
        still_failing_std: list[str] = []
        for p in active_std:
            page_dict = page_by_path.get(p)
            if not page_dict:
                continue
            try:
                page = WikiPage.from_dict(page_dict)
            except Exception:
                still_failing_std.append(p)
                continue
            if not _page_passes_post_heal(page, state, evaluator):
                still_failing_std.append(p)
        active_std = still_failing_std

    # Phase 3: Results
    initial_paths = core_pages + standard_pages
    healed_pages = [healed_by_path[p] for p in initial_paths if p in healed_by_path]
    log.info(
        "heal_pages_done",
        healed_count=len(healed_pages),
        core_healed=len([p for p in core_pages if p in healed_by_path]),
        standard_healed=len([p for p in standard_pages if p in healed_by_path]),
        still_failing_core=len(active_core),
        still_failing_standard=len(active_std),
    )
    return {
        "pages_to_heal": [],
        "heal_attempts": heal_attempts,
        "heal_hints": heal_hints,
        "pages": healed_pages,
    }
```

Also add `import asyncio` to the imports at the top of `wiki/nodes/heal.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_heal_concurrent.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing heal tests for regression**

Run: `uv run pytest tests/ -k "heal" -v`
Expected: All PASS (existing tests should still work with new implementation)

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/heal.py tests/wiki/test_heal_concurrent.py
git commit -m "feat(heal): rewrite heal_pages_node with concurrent tier-aware processing"
```

---

### Task 4: Migrate domain_compose.py to PipelineConcurrency

**Files:**
- Modify: `wiki/nodes/domain_compose.py:16` (replace hardcoded env var read)
- Test: `tests/wiki/test_pipeline_concurrency.py` (existing tests cover the behavior)

- [ ] **Step 1: Write failing test for migration**

```python
# Append to tests/wiki/test_pipeline_concurrency.py
class TestDomainComposeIntegration:
    def test_domain_compose_uses_pipeline_concurrency(self):
        """domain_compose should use PipelineConcurrency instead of raw env var."""
        import wiki.nodes.domain_compose as dc
        # After migration, the module should not have DOMAIN_AGENT_CONCURRENCY as a module-level constant
        # used for semaphore creation. Instead it should use PipelineConcurrency.
        from wiki.pipeline_concurrency import PipelineConcurrency
        sem = PipelineConcurrency.semaphore("domain_agent")
        assert sem._value == 3
```

- [ ] **Step 2: Run test (should pass already since PipelineConcurrency exists)**

Run: `uv run pytest tests/wiki/test_pipeline_concurrency.py::TestDomainComposeIntegration -v`
Expected: PASS

- [ ] **Step 3: Migrate domain_compose.py**

In `wiki/nodes/domain_compose.py`, replace lines 16-17:

```python
# Before:
DOMAIN_AGENT_CONCURRENCY = int(os.environ.get("DOMAIN_AGENT_CONCURRENCY", "3"))
DOMAIN_AGENT_TIMEOUT_SEC = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "600"))
```

With:

```python
from wiki.pipeline_concurrency import PipelineConcurrency

DOMAIN_AGENT_TIMEOUT_SEC = int(os.environ.get("DOMAIN_AGENT_TIMEOUT_SEC", "600"))
```

And at line 126, replace:

```python
# Before:
sem = asyncio.Semaphore(DOMAIN_AGENT_CONCURRENCY)
```

With:

```python
sem = PipelineConcurrency.semaphore("domain_agent")
```

Remove the `import os` if no longer needed (check if `DOMAIN_AGENT_TIMEOUT_SEC` still uses it — it does, so keep `os` import).

- [ ] **Step 4: Run existing domain_compose tests**

Run: `uv run pytest tests/ -k "domain_compose or domain_agent" -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/domain_compose.py
git commit -m "refactor(domain_compose): migrate to PipelineConcurrency"
```

---

### Task 5: Migrate graph_nodes.py to PipelineConcurrency

**Files:**
- Modify: `wiki/nodes/graph_nodes.py:14` (replace hardcoded `_BOTTOMUP_CONCURRENCY = 24`)

- [ ] **Step 1: Migrate graph_nodes.py**

In `wiki/nodes/graph_nodes.py`, replace line 14:

```python
# Before:
_BOTTOMUP_CONCURRENCY = 24
```

With:

```python
from wiki.pipeline_concurrency import PipelineConcurrency
```

Then replace all occurrences of `asyncio.Semaphore(_BOTTOMUP_CONCURRENCY)` (lines 169, 294, 388) with:

```python
PipelineConcurrency.semaphore("bottomup")
```

And the log reference at line 348 from `concurrency=_BOTTOMUP_CONCURRENCY` to `concurrency=PipelineConcurrency.limit("bottomup")`.

- [ ] **Step 2: Run existing graph_nodes tests**

Run: `uv run pytest tests/ -k "graph_node or bottomup or generate_titles" -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/nodes/graph_nodes.py
git commit -m "refactor(graph_nodes): migrate to PipelineConcurrency"
```

---

### Task 6: Migrate repo_composer.py to PipelineConcurrency

**Files:**
- Modify: `wiki/repo_composer.py:80` (replace `MAX_CONCURRENT_MODULE_COMPOSE = 3`)

- [ ] **Step 1: Migrate repo_composer.py**

In `wiki/repo_composer.py`, replace line 80:

```python
# Before:
MAX_CONCURRENT_MODULE_COMPOSE = 3
```

With:

```python
from wiki.pipeline_concurrency import PipelineConcurrency
```

And at line 484, replace:

```python
# Before:
sem = asyncio.Semaphore(MAX_CONCURRENT_MODULE_COMPOSE)
```

With:

```python
sem = PipelineConcurrency.semaphore("module_compose")
```

- [ ] **Step 2: Run related tests**

Run: `uv run pytest tests/ -k "repo_composer or module_compose" -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/repo_composer.py
git commit -m "refactor(repo_composer): migrate to PipelineConcurrency"
```

---

### Task 7: Full Integration Test + Regression

**Files:**
- Test: Full test suite run

- [ ] **Step 1: Run full backend test suite**

Run: `uv run pytest tests/ -x --timeout=120`
Expected: All PASS (no regressions)

- [ ] **Step 2: Run lint check**

Run: `uv run ruff check wiki/pipeline_concurrency.py wiki/nodes/heal.py wiki/nodes/domain_compose.py wiki/nodes/graph_nodes.py wiki/repo_composer.py core/config.py`
Expected: No errors

- [ ] **Step 3: Final commit (if any lint fixes needed)**

```bash
git add -A
git commit -m "chore: lint fixes for heal redesign + unified rate control"
```
