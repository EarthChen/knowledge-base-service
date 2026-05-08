# TaskSupervisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace all 12 bare `asyncio.create_task` calls with a centralized `TaskSupervisor` that provides visibility, retry, cancellation, and graceful shutdown.

**Architecture:** New `core/task_supervisor.py` module registered in `AppContainer`. All background task creation flows through `supervisor.spawn()`. Health endpoint exposes active task counts. Shutdown awaits or cancels all tasks.

**Tech Stack:** Python asyncio, structlog, pytest

**Spec:** `docs/superpowers/specs/2026-05-02-task-supervisor-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `core/task_supervisor.py` | TaskSupervisor class with spawn/cancel/shutdown/stats |
| Create | `tests/core/test_task_supervisor.py` | Unit tests for TaskSupervisor |
| Modify | `core/container.py` | Add `task_supervisor` field |
| Modify | `main.py` | Init supervisor in lifespan, shutdown before stores |
| Modify | `api/routes/public_health_routes.py` | Expose `background_tasks` in health response |
| Modify | `wiki/bootstrap.py` | Migrate 1 call site (#8) |
| Modify | `api/routes/indexing_routes.py` | Migrate 3 call sites (#1,2,3) |
| Modify | `api/routes/wiki_task_routes.py` | Migrate 3 call sites (#5,6,7) |
| Modify | `api/routes/business_sync_routes.py` | Migrate 1 call site (#9) |
| Modify | `wiki/enrichment_coordinator.py` | Migrate 1 call site (#4) |
| Modify | `wiki/scheduler/wiki_scheduler.py` | Migrate 1 call site (#10) |
| Modify | `wiki/lint_scheduler.py` | Migrate 1 call site (#11) |
| Modify | `services/scheduler.py` | Migrate 1 call site (#12) |

---

### Task 1: Core TaskSupervisor — Implementation + Tests

**Files:**
- Create: `core/task_supervisor.py`
- Create: `tests/core/test_task_supervisor.py`

- [ ] **Step 1: Write failing tests for spawn + completion**

```python
# tests/core/test_task_supervisor.py
"""Unit tests for TaskSupervisor."""
from __future__ import annotations

import asyncio

import pytest

from core.task_supervisor import TaskSupervisor


@pytest.fixture
def supervisor() -> TaskSupervisor:
    return TaskSupervisor()


@pytest.mark.asyncio
async def test_spawn_runs_task(supervisor: TaskSupervisor) -> None:
    result: list[int] = []

    async def work() -> None:
        result.append(42)

    tid = supervisor.spawn(lambda: work(), name="test:basic")
    assert tid
    assert len(supervisor.active_tasks) == 1
    await asyncio.sleep(0.05)
    assert result == [42]
    assert len(supervisor.active_tasks) == 0
    assert supervisor.stats["total_spawned"] == 1
    assert supervisor.stats["total_completed"] == 1


@pytest.mark.asyncio
async def test_cancel_task(supervisor: TaskSupervisor) -> None:
    async def forever() -> None:
        await asyncio.sleep(999)

    tid = supervisor.spawn(lambda: forever(), name="test:cancel")
    assert supervisor.cancel(tid) is True
    await asyncio.sleep(0.05)
    assert len(supervisor.active_tasks) == 0
    assert supervisor.cancel("nonexistent") is False


@pytest.mark.asyncio
async def test_shutdown_cancels_remaining(supervisor: TaskSupervisor) -> None:
    async def forever() -> None:
        await asyncio.sleep(999)

    supervisor.spawn(lambda: forever(), name="test:sd1")
    supervisor.spawn(lambda: forever(), name="test:sd2")
    assert len(supervisor.active_tasks) == 2
    await supervisor.shutdown(timeout=0.5)
    assert len(supervisor.active_tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_rejects_new_spawn(supervisor: TaskSupervisor) -> None:
    await supervisor.shutdown(timeout=0.1)
    with pytest.raises(RuntimeError, match="shutting down"):
        supervisor.spawn(lambda: asyncio.sleep(0), name="test:rejected")


@pytest.mark.asyncio
async def test_retry_on_failure(supervisor: TaskSupervisor) -> None:
    attempts: list[int] = []

    async def flaky() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise ValueError("not yet")

    supervisor.spawn(lambda: flaky(), name="test:retry", max_retries=3, retry_delay=0.01)
    await asyncio.sleep(0.3)
    assert len(attempts) == 3
    assert supervisor.stats["total_retried"] >= 2
    assert supervisor.stats["total_completed"] == 1


@pytest.mark.asyncio
async def test_retry_exhausted_calls_on_failure(supervisor: TaskSupervisor) -> None:
    failures: list[str] = []

    async def always_fail() -> None:
        raise ValueError("boom")

    def on_fail(task_id: str, exc: BaseException) -> None:
        failures.append(task_id)

    supervisor.spawn(
        lambda: always_fail(),
        name="test:exhaust",
        max_retries=1,
        retry_delay=0.01,
        on_failure=on_fail,
    )
    await asyncio.sleep(0.2)
    assert len(failures) == 1
    assert supervisor.stats["total_failed"] == 1


@pytest.mark.asyncio
async def test_timeout_cancels_task(supervisor: TaskSupervisor) -> None:
    async def slow() -> None:
        await asyncio.sleep(999)

    supervisor.spawn(lambda: slow(), name="test:timeout", timeout=0.05)
    await asyncio.sleep(0.3)
    assert len(supervisor.active_tasks) == 0
    assert supervisor.stats["total_failed"] == 1


@pytest.mark.asyncio
async def test_active_tasks_snapshot(supervisor: TaskSupervisor) -> None:
    async def hold() -> None:
        await asyncio.sleep(1)

    supervisor.spawn(lambda: hold(), name="test:snap1")
    supervisor.spawn(lambda: hold(), name="test:snap2")
    snap = supervisor.active_tasks
    assert len(snap) == 2
    for info in snap.values():
        assert "name" in info
        assert "created_at" in info
        assert "retry_count" in info
    await supervisor.shutdown(timeout=0.5)


@pytest.mark.asyncio
async def test_concurrent_tasks(supervisor: TaskSupervisor) -> None:
    results: list[int] = []

    async def job(n: int) -> None:
        await asyncio.sleep(0.01)
        results.append(n)

    for i in range(5):
        supervisor.spawn(lambda i=i: job(i), name=f"test:concurrent-{i}")
    await asyncio.sleep(0.2)
    assert sorted(results) == [0, 1, 2, 3, 4]
    assert supervisor.stats["total_completed"] == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/core/test_task_supervisor.py -v --no-cov`
Expected: FAIL with `ModuleNotFoundError: No module named 'core.task_supervisor'`

- [ ] **Step 3: Implement TaskSupervisor**

```python
# core/task_supervisor.py
"""Centralized background task supervision with retry, cancellation, and health reporting."""
from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_MAX_RETRY_DELAY = 60.0


@dataclass
class _TaskRecord:
    task_id: str
    name: str
    asyncio_task: asyncio.Task[None]
    created_at: float
    retry_count: int = 0
    max_retries: int = 0


class TaskSupervisor:
    """Manages background asyncio tasks with retry, cancellation, and graceful shutdown."""

    def __init__(self) -> None:
        self._tasks: dict[str, _TaskRecord] = {}
        self._shutting_down = False
        self._total_spawned = 0
        self._total_completed = 0
        self._total_failed = 0
        self._total_retried = 0

    def spawn(
        self,
        coro_factory: Callable[[], Coroutine[Any, Any, None]],
        *,
        name: str,
        max_retries: int = 0,
        retry_delay: float = 5.0,
        timeout: float | None = None,
        on_failure: Callable[[str, BaseException], None] | None = None,
    ) -> str:
        if self._shutting_down:
            raise RuntimeError("TaskSupervisor is shutting down; cannot spawn new tasks")

        task_id = f"{name}:{uuid.uuid4().hex[:8]}"
        self._total_spawned += 1

        async def _wrapper() -> None:
            retries = 0
            delay = retry_delay
            while True:
                try:
                    coro = coro_factory()
                    if timeout is not None:
                        await asyncio.wait_for(coro, timeout=timeout)
                    else:
                        await coro
                    self._total_completed += 1
                    log.info("task_completed", task_id=task_id, name=name)
                    return
                except asyncio.CancelledError:
                    log.info("task_cancelled", task_id=task_id, name=name)
                    raise
                except Exception as exc:
                    if retries < max_retries:
                        retries += 1
                        self._total_retried += 1
                        if task_id in self._tasks:
                            self._tasks[task_id].retry_count = retries
                        log.warning(
                            "task_retry",
                            task_id=task_id,
                            name=name,
                            attempt=retries,
                            max_retries=max_retries,
                            delay=delay,
                            error=str(exc),
                        )
                        await asyncio.sleep(delay)
                        delay = min(delay * 2, _MAX_RETRY_DELAY)
                    else:
                        self._total_failed += 1
                        log.error(
                            "task_failed",
                            task_id=task_id,
                            name=name,
                            retries=retries,
                            error=str(exc),
                            exc_info=True,
                        )
                        if on_failure is not None:
                            try:
                                on_failure(task_id, exc)
                            except Exception:
                                log.warning("task_on_failure_callback_error", task_id=task_id, exc_info=True)
                        return

        def _done_cb(t: asyncio.Task[None]) -> None:
            self._tasks.pop(task_id, None)

        atask = asyncio.create_task(_wrapper(), name=task_id)
        atask.add_done_callback(_done_cb)
        self._tasks[task_id] = _TaskRecord(
            task_id=task_id,
            name=name,
            asyncio_task=atask,
            created_at=time.monotonic(),
            max_retries=max_retries,
        )
        log.info("task_spawned", task_id=task_id, name=name)
        return task_id

    def cancel(self, task_id: str) -> bool:
        record = self._tasks.get(task_id)
        if record is None:
            return False
        record.asyncio_task.cancel()
        return True

    async def shutdown(self, timeout: float = 30.0) -> None:
        self._shutting_down = True
        if not self._tasks:
            return
        tasks = [r.asyncio_task for r in self._tasks.values()]
        log.info("task_supervisor_shutdown_start", active=len(tasks), timeout=timeout)
        done, pending = await asyncio.wait(tasks, timeout=timeout)
        for t in pending:
            t.cancel()
        if pending:
            await asyncio.wait(pending, timeout=5.0)
            log.warning("task_supervisor_shutdown_cancelled", count=len(pending))
        log.info("task_supervisor_shutdown_complete")

    @property
    def active_tasks(self) -> dict[str, dict[str, Any]]:
        now = time.monotonic()
        return {
            tid: {
                "name": r.name,
                "created_at": r.created_at,
                "running_for_s": round(now - r.created_at, 1),
                "retry_count": r.retry_count,
                "max_retries": r.max_retries,
            }
            for tid, r in self._tasks.items()
        }

    @property
    def stats(self) -> dict[str, int]:
        return {
            "total_spawned": self._total_spawned,
            "total_completed": self._total_completed,
            "total_failed": self._total_failed,
            "total_retried": self._total_retried,
            "active": len(self._tasks),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/core/test_task_supervisor.py -v --no-cov`
Expected: All 10 tests PASS

- [ ] **Step 5: Verify no regressions**

Run: `uv run pytest --tb=short -q`
Expected: 2656+ tests PASS, 82%+ coverage

---

### Task 2: Integration — AppContainer + Lifespan + Health

**Files:**
- Modify: `core/container.py`
- Modify: `main.py`
- Modify: `api/routes/public_health_routes.py`

- [ ] **Step 1: Add `task_supervisor` field to `AppContainer`**

In `core/container.py`, add import and field:

```python
# Add at top-level imports:
from core.task_supervisor import TaskSupervisor

# Add field to AppContainer dataclass (after index_sem):
    task_supervisor: TaskSupervisor = field(default_factory=TaskSupervisor)
```

Also update `create_test` defaults:

```python
"task_supervisor": TaskSupervisor(),
```

- [ ] **Step 2: Initialize supervisor in lifespan, shutdown before stores**

In `main.py`, modify `lifespan()`:
- The `container = AppContainer(...)` call already creates `TaskSupervisor` via `default_factory`.
- No additional init needed.

In `_shutdown_all()`, add supervisor shutdown **before** existing shutdown logic:

```python
async def _shutdown_all(container: AppContainer, app: FastAPI) -> None:
    """Reverse-order teardown."""
    # Drain background tasks first
    await container.task_supervisor.shutdown(timeout=30.0)

    ls = getattr(app.state, "wiki_lint_scheduler", None)
    # ... rest unchanged
```

- [ ] **Step 3: Expose background_tasks in health endpoint**

In `api/routes/public_health_routes.py`, add supervisor stats to health response:

```python
@public_router.get("/health")
async def health() -> JSONResponse:
    if kb_state.registry is None:
        return JSONResponse(
            status_code=503,
            content={"status": "initializing", "detail": "registry not started"},
        )
    body, status_code = await kb_state.registry.readiness()
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=body)

    falkordb = await kb_state.registry.falkordb_graph_ping()
    payload: dict[str, Any] = dict(body)
    components: dict[str, str] = dict(payload.get("components") or {})
    components["falkordb"] = falkordb
    payload["components"] = components
    if falkordb != "ready":
        payload["status"] = "degraded"
        payload["falkordb"] = "unreachable"

    # Background task supervision stats
    container = getattr(kb_state, "_container", None)
    if container is not None and hasattr(container, "task_supervisor"):
        payload["background_tasks"] = container.task_supervisor.stats

    return JSONResponse(status_code=200, content=payload)
```

- [ ] **Step 4: Run tests to verify**

Run: `uv run pytest tests/core/test_task_supervisor.py tests/api/test_public_health_falkordb.py -v --no-cov`
Expected: All PASS

---

### Task 3: Migrate Indexing Routes (3 call sites)

**Files:**
- Modify: `api/routes/indexing_routes.py`

- [ ] **Step 1: Add supervisor import and helper**

At the top of `indexing_routes.py`, add:

```python
from core.task_supervisor import TaskSupervisor
```

Add a helper to retrieve the supervisor from app state:

```python
def _get_supervisor(request: Request) -> TaskSupervisor:
    return request.app.state.container.task_supervisor
```

- [ ] **Step 2: Replace call site #1 (index task, ~line 86)**

Replace:
```python
asyncio.create_task(throttled_index_task(task.task_id, req, business_id))
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda tid=task.task_id, r=req, bid=business_id: throttled_index_task(tid, r, bid),
    name="indexing:index",
    max_retries=2,
)
```

- [ ] **Step 3: Replace call site #2 (reindex task, ~line 186)**

Replace:
```python
asyncio.create_task(
    _throttled_index(kb_state.reindex_sem, task.task_id, idx, business_id)
)
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda s=kb_state.reindex_sem, tid=task.task_id, i=idx, bid=business_id: _throttled_index(s, tid, i, bid),
    name="indexing:reindex",
    max_retries=2,
)
```

- [ ] **Step 4: Replace call site #3 (enrich task, ~line 221)**

Replace:
```python
asyncio.create_task(run_enrich_task(task.task_id, req, business_id))
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda tid=task.task_id, r=req, bid=business_id: run_enrich_task(tid, r, bid),
    name="indexing:enrich",
    max_retries=2,
)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/api/ -v --no-cov -q`
Expected: All PASS

---

### Task 4: Migrate Wiki Task Routes (3 call sites)

**Files:**
- Modify: `api/routes/wiki_task_routes.py`

- [ ] **Step 1: Add supervisor import and helper**

```python
from core.task_supervisor import TaskSupervisor

def _get_supervisor(request: Request) -> TaskSupervisor:
    return request.app.state.container.task_supervisor
```

- [ ] **Step 2: Replace call site #5 (~line 266)**

Replace:
```python
asyncio.create_task(_run_wiki_task(task_id, svc, body, registry, sem))
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda: _run_wiki_task(task_id, svc, body, registry, sem),
    name="wiki:generate",
    max_retries=1,
)
```

- [ ] **Step 3: Replace call site #6 (~line 361)**

Replace:
```python
asyncio.create_task(
    _run_wiki_quick_task(
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda: _run_wiki_quick_task(
```
(Ensure the lambda wraps the entire call with all parameters captured.)

- [ ] **Step 4: Replace call site #7 (~line 586)**

Replace:
```python
asyncio.create_task(
    _run_business_wiki_background(
```
With:
```python
supervisor = _get_supervisor(request)
supervisor.spawn(
    lambda: _run_business_wiki_background(
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/api/ tests/wiki/ -v --no-cov -q`
Expected: All PASS

---

### Task 5: Migrate Bootstrap + Business Sync + Enrichment Coordinator (3 call sites)

**Files:**
- Modify: `wiki/bootstrap.py`
- Modify: `api/routes/business_sync_routes.py`
- Modify: `wiki/enrichment_coordinator.py`

- [ ] **Step 1: Migrate bootstrap.py call site #8**

In `_make_enqueue_regenerate`, change to accept supervisor:

```python
def _make_enqueue_regenerate(
    app_state: Any,
    supervisor: TaskSupervisor,
) -> Callable[[str, str, float], Awaitable[None]]:
    async def enqueue_regenerate(
        page_uid: str, priority: str, token_multiplier: float
    ) -> None:
        async def _task() -> None:
            try:
                await _run_feedback_wiki_regen(
                    app_state, page_uid, priority, token_multiplier
                )
            except Exception:
                log.warning("feedback_regen_background_failed", page_uid=page_uid, exc_info=True)

        supervisor.spawn(lambda: _task(), name="wiki:feedback-regen")

    return enqueue_regenerate
```

Update `bootstrap_wiki` to pass supervisor:

```python
from core.task_supervisor import TaskSupervisor

# In bootstrap_wiki, get supervisor from app.state.container:
supervisor = app.state.container.task_supervisor

app.state.wiki_feedback_regen = FeedbackDrivenRegeneration(
    graph=kb.store,
    wiki_config=settings.wiki,
    enqueue_regenerate=_make_enqueue_regenerate(app.state, supervisor),
)
```

- [ ] **Step 2: Migrate business_sync_routes.py call site #9**

Replace:
```python
asyncio.create_task(_wiki_bg())
```
With:
```python
supervisor = request.app.state.container.task_supervisor
supervisor.spawn(lambda: _wiki_bg(), name="wiki:sync-regen")
```

- [ ] **Step 3: Migrate enrichment_coordinator.py call site #4**

Replace:
```python
asyncio.create_task(
    self.run_enrichment_background(repository, llm_port, task_id),
    name=f"enrichment-{task_id}",
)
```
With:
```python
self._supervisor.spawn(
    lambda r=repository, lp=llm_port, tid=task_id: self.run_enrichment_background(r, lp, tid),
    name="indexing:enrichment-bg",
    max_retries=2,
)
```

The enrichment coordinator needs to receive the supervisor. Add it to `__init__`:

```python
def __init__(self, ..., supervisor: TaskSupervisor | None = None) -> None:
    ...
    self._supervisor = supervisor
```

And fall back to `asyncio.create_task` if supervisor is None (for backward compatibility).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/ tests/api/ -v --no-cov -q`
Expected: All PASS

---

### Task 6: Migrate Schedulers (3 call sites)

**Files:**
- Modify: `wiki/scheduler/wiki_scheduler.py`
- Modify: `wiki/lint_scheduler.py`
- Modify: `services/scheduler.py`

- [ ] **Step 1: Migrate wiki_scheduler.py call site #10**

Add optional `supervisor` parameter to the scheduler class. Replace:
```python
self._loop_task = asyncio.create_task(self._run_loop(), name="wiki-scheduler")
```
With:
```python
if self._supervisor is not None:
    self._loop_task_id = self._supervisor.spawn(
        lambda: self._run_loop(), name="scheduler:wiki", max_retries=3, retry_delay=10.0
    )
else:
    self._loop_task = asyncio.create_task(self._run_loop(), name="wiki-scheduler")
```

- [ ] **Step 2: Migrate lint_scheduler.py call site #11**

Add optional `supervisor` parameter. Replace:
```python
self._task = asyncio.create_task(self._loop())
```
With:
```python
if self._supervisor is not None:
    self._task_id = self._supervisor.spawn(
        lambda: self._loop(), name="scheduler:lint", max_retries=3, retry_delay=10.0
    )
else:
    self._task = asyncio.create_task(self._loop())
```

- [ ] **Step 3: Migrate services/scheduler.py call site #12**

Replace:
```python
self._tasks[repo_name] = asyncio.create_task(
    self._schedule_loop(repo_name),
    name=f"sync_schedule:{repo_name}",
)
```
With:
```python
if self._supervisor is not None:
    tid = self._supervisor.spawn(
        lambda rn=repo_name: self._schedule_loop(rn),
        name=f"scheduler:sync:{repo_name}",
        max_retries=3,
        retry_delay=10.0,
    )
    self._tasks[repo_name] = tid
else:
    self._tasks[repo_name] = asyncio.create_task(
        self._schedule_loop(repo_name),
        name=f"sync_schedule:{repo_name}",
    )
```

- [ ] **Step 4: Wire supervisor into scheduler creation in main.py/bootstrap**

Pass `supervisor` when creating scheduler instances.

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest --tb=short -q`
Expected: 2656+ tests PASS

---

### Task 7: Update Documentation

**Files:**
- Modify: `docs/superpowers/DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md`

- [ ] **Step 1: Mark B-15 as fixed in DEEP_ANALYSIS**

Change:
```
| B-15 | P2 | `wiki/bootstrap.py` | **后台任务缺乏监管** | `asyncio.create_task` 创建反馈再生任务——无集中式任务监督、取消或重试机制。 |
```
To:
```
| B-15 | ~~P2~~ **已修复** | `core/task_supervisor.py` | ~~后台任务缺乏监管~~ | 引入 `TaskSupervisor` 集中管理所有 12 处后台任务，支持重试、超时、取消、优雅关闭和健康检查。 |
```

- [ ] **Step 2: Update version history**

Add v9 entry.

- [ ] **Step 3: Final regression test**

Run: `uv run pytest --tb=short -q`
Expected: All tests PASS
