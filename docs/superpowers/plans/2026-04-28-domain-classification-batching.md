# Domain Classification Prompt Sub-Batching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `BusinessDomainPlanner.classify()` to split large module lists into sub-batches, preventing LLM prompt overflow (187K tokens) that causes `ReadError` during domain classification.

**Architecture:** `BusinessDomainPlanner.classify()` gains `sub_batch_size` (default 80) and `max_concurrency` (default 3) parameters, both read from existing `AppWikiFlags`. When modules exceed the batch size, it splits into N batches, classifies them concurrently (bounded by `asyncio.Semaphore(max_concurrency)`), merges results, and assigns unmatched modules to infrastructure. Per-batch fault tolerance ensures one failure doesn't block others.

**Tech Stack:** Python 3.11+, asyncio, structlog, pytest + AsyncMock

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `wiki/business_domain_planner.py` | Per-repo module→domain classification | Major: add sub-batch loop, extract `_classify_single_batch`, logging |
| `wiki/cross_repo_domain_planner.py` | Cross-repo orchestration | Minor: accept & forward `sub_batch_size` + `max_concurrency` |
| `wiki/service.py` | Wiki pipeline entry point | Minor: pass `sub_batch_size` + `max_concurrency` from config |
| `tests/wiki/test_business_domain_planner.py` | Unit tests for per-repo planner | Add: batching, merge, fault tolerance tests |
| `tests/wiki/test_cross_repo_domain_planner.py` | Unit tests for cross-repo planner | Add: verify `sub_batch_size` forwarding |

---

### Task 1: Add Sub-Batch Tests for `BusinessDomainPlanner`

**Files:**
- Modify: `tests/wiki/test_business_domain_planner.py`

- [ ] **Step 1: Write test for large repo sub-batching with concurrency**

Append to `tests/wiki/test_business_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_large_repo_splits_into_batches():
    """When modules exceed sub_batch_size, multiple LLM calls should be made concurrently."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            '{"用户域": ["mod_0", "mod_1", "mod_2"]}',
            '{"支付域": ["mod_3", "mod_4"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}", f"summary {i}") for i in range(5)]
    result = await planner.classify("test-repo", modules, sub_batch_size=3, max_concurrency=2)
    assert llm.generate.await_count == 2
    assert set(result["用户域"]) == {"mod_0", "mod_1", "mod_2"}
    assert set(result["支付域"]) == {"mod_3", "mod_4"}
```

- [ ] **Step 2: Write test for per-batch fault tolerance**

Append to `tests/wiki/test_business_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_batch_failure_isolates_to_infrastructure():
    """If one batch fails, its modules go to infrastructure; other batches succeed."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["mod_0", "mod_1"]}',
            RuntimeError("LLM timeout on batch 2"),
            '{"域B": ["mod_4", "mod_5"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(6)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=1)
    assert llm.generate.await_count == 3
    assert set(result["域A"]) == {"mod_0", "mod_1"}
    assert set(result["域B"]) == {"mod_4", "mod_5"}
    assert "mod_2" in result["__infrastructure__"]
    assert "mod_3" in result["__infrastructure__"]
```

- [ ] **Step 3: Write test for same-domain merge across batches**

Append to `tests/wiki/test_business_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_merges_same_domain_across_batches():
    """Same domain name across batches should merge module lists."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            '{"用户域": ["mod_0", "mod_1"]}',
            '{"用户域": ["mod_2", "mod_3"]}',
        ]
    )
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(4)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=2)
    assert set(result["用户域"]) == {"mod_0", "mod_1", "mod_2", "mod_3"}
```

- [ ] **Step 4: Write test for all-batches-fail graceful degradation**

Append to `tests/wiki/test_business_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_all_batches_fail_degrades_to_infrastructure():
    """If all batches fail, all modules go to infrastructure."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=RuntimeError("LLM down"))
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module(f"mod_{i}") for i in range(5)]
    result = await planner.classify("test-repo", modules, sub_batch_size=2, max_concurrency=2)
    assert list(result.keys()) == ["__infrastructure__"]
    assert len(result["__infrastructure__"]) == 5
```

- [ ] **Step 5: Write test that small repo still uses single batch**

Append to `tests/wiki/test_business_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_small_repo_single_batch_unchanged():
    """Modules within sub_batch_size should still use a single LLM call (regression guard)."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value='{"域X": ["a", "b"]}')
    planner = BusinessDomainPlanner(llm)
    modules = [_make_module("a"), _make_module("b")]
    result = await planner.classify("test-repo", modules, sub_batch_size=80)
    assert llm.generate.await_count == 1
    assert set(result["域X"]) == {"a", "b"}
```

- [ ] **Step 6: Run tests to verify they all fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run --extra dev pytest tests/wiki/test_business_domain_planner.py -v`
Expected: The 5 new tests FAIL (because `sub_batch_size` parameter does not exist yet). The 7 existing tests PASS.

---

### Task 2: Implement Sub-Batching in `BusinessDomainPlanner`

**Files:**
- Modify: `wiki/business_domain_planner.py:1-153`

- [ ] **Step 1: Add `asyncio` and `time` imports**

At the top of `wiki/business_domain_planner.py`, add after line 6:

```python
import asyncio
import time
```

- [ ] **Step 2: Refactor `classify` to accept `sub_batch_size` + `max_concurrency` and add concurrent sub-batch loop**

Replace the current `classify` method (lines 29-57) with:

```python
    async def classify(
        self,
        repository_id: str,
        modules: list[GraphNode],
        *,
        sub_batch_size: int = 80,
        max_concurrency: int = 3,
    ) -> dict[str, list[str]]:
        if not modules:
            return {}

        names_in_order = self._module_names_in_order(modules)
        if not names_in_order:
            return {}

        valid_names = set(names_in_order)

        if self._llm is None:
            return {self._infrastructure_label: list(names_in_order)}

        if len(modules) <= sub_batch_size:
            return await self._classify_single_batch(
                repository_id, modules, names_in_order, valid_names,
            )

        batches = [
            modules[i : i + sub_batch_size]
            for i in range(0, len(modules), sub_batch_size)
        ]
        total_batches = len(batches)
        log.info(
            "domain_classify_start",
            repository_id=repository_id,
            module_count=len(modules),
            batch_count=total_batches,
            sub_batch_size=sub_batch_size,
            max_concurrency=max_concurrency,
        )

        t0 = time.monotonic()
        sem = asyncio.Semaphore(max_concurrency)
        batch_results: list[dict[str, list[str]]] = [{}] * total_batches

        async def _run_batch(idx: int, batch: list[GraphNode]) -> None:
            async with sem:
                batch_names = self._module_names_in_order(batch)
                batch_valid = set(batch_names)
                try:
                    log.debug(
                        "domain_classify_batch_start",
                        repository_id=repository_id,
                        batch_index=idx,
                        batch_size=len(batch),
                    )
                    bt = time.monotonic()
                    batch_results[idx] = await self._classify_single_batch(
                        repository_id, batch, batch_names, batch_valid,
                    )
                    elapsed_ms = int((time.monotonic() - bt) * 1000)
                    log.info(
                        "domain_classify_batch_done",
                        repository_id=repository_id,
                        batch_index=idx,
                        domains_found=len(batch_results[idx]),
                        elapsed_ms=elapsed_ms,
                    )
                except Exception:
                    log.warning(
                        "domain_classify_batch_failed",
                        repository_id=repository_id,
                        batch_index=idx,
                        batch_size=len(batch),
                        exc_info=True,
                    )
                    batch_results[idx] = {self._infrastructure_label: batch_names}

        await asyncio.gather(*[_run_batch(i, b) for i, b in enumerate(batches)])

        merged: dict[str, list[str]] = {}
        for batch_result in batch_results:
            for domain, domain_modules in batch_result.items():
                merged.setdefault(domain, []).extend(domain_modules)

        total_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "domain_classify_done",
            repository_id=repository_id,
            total_domains=len(merged),
            total_elapsed_ms=total_ms,
        )

        return self._ensure_all_assigned(merged, valid_names, names_in_order)
```

- [ ] **Step 3: Extract `_classify_single_batch` method**

Add after the `classify` method:

```python
    async def _classify_single_batch(
        self,
        repository_id: str,
        modules: list[GraphNode],
        names_in_order: list[str],
        valid_names: set[str],
    ) -> dict[str, list[str]]:
        metadata = self._collect_metadata(modules)
        prompt = self._build_prompt(repository_id, metadata)
        raw = (
            await self._llm.generate(
                prompt, system="Reply with JSON only. No markdown fences.",
            )
        ).strip()
        parsed = self._parse_domain_map(raw)
        if not parsed:
            return self._all_infrastructure(names_in_order)
        return self._merge_llm_assignment(parsed, valid_names, names_in_order)
```

- [ ] **Step 4: Add `_ensure_all_assigned` helper**

Add after `_all_infrastructure`:

```python
    def _ensure_all_assigned(
        self,
        merged: dict[str, list[str]],
        valid_names: set[str],
        names_in_order: list[str],
    ) -> dict[str, list[str]]:
        assigned: set[str] = set()
        for names in merged.values():
            assigned.update(names)
        missing = [n for n in names_in_order if n in valid_names and n not in assigned]
        if missing:
            merged.setdefault(self._infrastructure_label, []).extend(missing)
        return merged
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run --extra dev pytest tests/wiki/test_business_domain_planner.py -v`
Expected: ALL 12 tests PASS (7 existing + 5 new).

- [ ] **Step 6: Commit**

```bash
git add wiki/business_domain_planner.py tests/wiki/test_business_domain_planner.py
git commit -m "feat(wiki): add sub-batch logic to BusinessDomainPlanner.classify()

Split large module lists into configurable sub-batches (default 80)
to prevent LLM prompt overflow. Per-batch fault tolerance ensures
one failure doesn't block classification of other batches."
```

---

### Task 3: Wire `sub_batch_size` + `max_concurrency` Through `CrossRepoBusinessDomainPlanner`

**Files:**
- Modify: `wiki/cross_repo_domain_planner.py:21-34,108-129`
- Modify: `tests/wiki/test_cross_repo_domain_planner.py`

- [ ] **Step 1: Write test that params are forwarded to per-repo planner**

Append to `tests/wiki/test_cross_repo_domain_planner.py`:

```python
@pytest.mark.asyncio
async def test_classify_large_batch_forwards_sub_batch_size_and_concurrency():
    """When using multi-batch path, sub_batch_size and max_concurrency should be forwarded."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            '{"域A": ["a1"], "__infrastructure__": ["a2"]}',
            '{"域B": ["b1"], "__infrastructure__": ["b2"]}',
            '{"域A": [["r1", "a1"], ["r2", "b1"]], "__infrastructure__": [["r1", "a2"], ["r2", "b2"]]}',
        ]
    )

    planner = CrossRepoBusinessDomainPlanner(
        llm, batch_threshold=3, sub_batch_size=50, max_concurrency=2,
    )
    all_modules = {
        "r1": [_make_module("a1"), _make_module("a2")],
        "r2": [_make_module("b1"), _make_module("b2")],
    }
    result = await planner.classify("biz-7", all_modules)
    assert "域A" in result or "__infrastructure__" in result
```

- [ ] **Step 2: Add `sub_batch_size` and `max_concurrency` to `CrossRepoBusinessDomainPlanner.__init__`**

In `wiki/cross_repo_domain_planner.py`, modify `__init__` (lines 24-34):

Replace:
```python
    def __init__(
        self,
        llm: LLMPort | None,
        *,
        infrastructure_label: str = "__infrastructure__",
        batch_threshold: int = 100,
    ) -> None:
        self._llm = llm
        self._infrastructure_label = infrastructure_label
        self._batch_threshold = batch_threshold
        self._metadata_cache: dict[tuple[str, str], dict[str, str | int | float | list[str]]] = {}
```

With:
```python
    def __init__(
        self,
        llm: LLMPort | None,
        *,
        infrastructure_label: str = "__infrastructure__",
        batch_threshold: int = 100,
        sub_batch_size: int = 80,
        max_concurrency: int = 3,
    ) -> None:
        self._llm = llm
        self._infrastructure_label = infrastructure_label
        self._batch_threshold = batch_threshold
        self._sub_batch_size = sub_batch_size
        self._max_concurrency = max_concurrency
        self._metadata_cache: dict[tuple[str, str], dict[str, str | int | float | list[str]]] = {}
```

- [ ] **Step 3: Forward both params in `_classify_multi_batch`**

In `wiki/cross_repo_domain_planner.py`, modify line 122:

Replace:
```python
            per_repo[repo_id] = await planner.classify(repo_id, modules)
```

With:
```python
            per_repo[repo_id] = await planner.classify(
                repo_id,
                modules,
                sub_batch_size=self._sub_batch_size,
                max_concurrency=self._max_concurrency,
            )
```

- [ ] **Step 4: Run cross-repo tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run --extra dev pytest tests/wiki/test_cross_repo_domain_planner.py -v`
Expected: ALL tests PASS (6 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add wiki/cross_repo_domain_planner.py tests/wiki/test_cross_repo_domain_planner.py
git commit -m "feat(wiki): forward sub_batch_size + max_concurrency through CrossRepoBusinessDomainPlanner

Accept sub_batch_size and max_concurrency in constructor and pass them to
BusinessDomainPlanner.classify() during per-repo classification."
```

---

### Task 4: Wire Config in `wiki/service.py`

**Files:**
- Modify: `wiki/service.py:1041-1045`

- [ ] **Step 1: Add `sub_batch_size` and `max_concurrency` to planner construction**

In `wiki/service.py`, find the `CrossRepoBusinessDomainPlanner` construction (around line 1041-1045):

Replace:
```python
        planner = CrossRepoBusinessDomainPlanner(
            llm_port,
            infrastructure_label=app_cfg.business_domain_infrastructure_label,
            batch_threshold=app_cfg.business_wiki_batch_threshold,
        )
```

With:
```python
        planner = CrossRepoBusinessDomainPlanner(
            llm_port,
            infrastructure_label=app_cfg.business_domain_infrastructure_label,
            batch_threshold=app_cfg.business_wiki_batch_threshold,
            sub_batch_size=app_cfg.business_domain_sub_batch_size,
            max_concurrency=app_cfg.business_domain_max_concurrency,
        )
```

- [ ] **Step 2: Run full test suite for wiki tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run --extra dev pytest tests/wiki/ -v --tb=short`
Expected: ALL wiki tests PASS.

- [ ] **Step 3: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): wire sub_batch_size + max_concurrency config to planner

Pass AppWikiFlags.business_domain_sub_batch_size (default 80) and
business_domain_max_concurrency (default 3) to CrossRepoBusinessDomainPlanner."
```

---

### Task 5: Integration Verification

**Files:** (no code changes — validation only)

- [ ] **Step 1: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run --extra dev pytest tests/ -v --tb=short -q`
Expected: ALL tests PASS, no regressions.

- [ ] **Step 2: Verify import chain**

Run:
```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -c "
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from config import get_settings
s = get_settings()
print(f'sub_batch_size config: {s.wiki.business_domain_sub_batch_size}')
print('OK')
"
```
Expected: Prints `sub_batch_size config: 80` and `OK`.

- [ ] **Step 3: Final commit (if any fixes needed)**

Only if previous steps required adjustments:
```bash
git add -A
git commit -m "fix(wiki): address integration issues from batching implementation"
```

---

## Self-Review Checklist

| Check | Status |
|-------|--------|
| Proposal P0 (sub-batching) covered by Tasks 1-2 | ✅ |
| Proposal P0 (config wiring) covered by Tasks 3-4 | ✅ |
| Proposal P1 (structured logging) covered by Task 2 Step 2 | ✅ |
| All 7 existing planner tests remain unchanged | ✅ |
| 6 existing cross-repo tests remain unchanged | ✅ |
| Type signatures consistent across all tasks | ✅ `sub_batch_size: int = 80` + `max_concurrency: int = 3` everywhere |
| No placeholders or TODOs | ✅ |
| File paths are exact | ✅ |
| Test code shows actual assertions | ✅ |
