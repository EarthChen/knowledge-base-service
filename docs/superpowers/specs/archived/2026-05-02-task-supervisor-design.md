# B-15: TaskSupervisor — Unified Background Task Supervision

**Created**: 2026-05-02  
**Status**: Approved  
**Addresses**: B-15 (P2) — Background tasks lack supervision, cancellation, retry

---

## Problem

The project has **12 call sites** that use bare `asyncio.create_task()` with no centralized tracking. Consequences:

1. **No visibility** — cannot enumerate running background tasks
2. **No retry** — task failures are logged but silently lost
3. **No cancellation** — shutdown cannot cleanly stop in-flight tasks
4. **No health check** — no way to detect stuck/hung tasks

## Approach

Lightweight in-process `TaskSupervisor` registered in `AppContainer`, replacing all 12 bare `asyncio.create_task` calls. Three call sites (#13–15 in the analysis) are excluded as they are internal mechanisms or short-lived tasks.

## Design

### Core: `core/task_supervisor.py`

```python
@dataclass
class TaskRecord:
    task_id: str
    name: str
    asyncio_task: asyncio.Task
    created_at: float
    retry_count: int = 0
    max_retries: int = 0
    timeout: float | None = None

class TaskSupervisor:
    def spawn(
        self,
        coro_factory: Callable[[], Coroutine],
        *,
        name: str,
        max_retries: int = 0,
        retry_delay: float = 5.0,
        timeout: float | None = None,
        on_failure: Callable[[str, BaseException], None] | None = None,
    ) -> str:
        """Register and launch a background task. Returns task_id."""

    def cancel(self, task_id: str) -> bool:
        """Cancel a task by ID. Returns True if found and cancelled."""

    async def shutdown(self, timeout: float = 30.0) -> None:
        """Graceful shutdown: wait for tasks to finish or cancel after timeout."""

    @property
    def active_tasks(self) -> dict[str, dict[str, Any]]:
        """Snapshot of all active tasks (for health/metrics)."""

    @property
    def stats(self) -> dict[str, int]:
        """Counters: total_spawned, total_completed, total_failed, total_retried."""
```

### Key Design Decisions

**`coro_factory` instead of `coro`**: `spawn` accepts a zero-argument callable that returns a coroutine, not a coroutine object directly. This enables retry — a consumed coroutine cannot be restarted.

**Retry strategy**: Fixed delay × exponential backoff factor (2×), capped at 60s. Only non-`CancelledError` exceptions trigger retry.

**Timeout**: Wraps the coroutine with `asyncio.wait_for`. On timeout, `CancelledError` is raised inside the task.

**Task naming convention**: `{category}:{action}` prefix (e.g., `wiki:generate`, `indexing:enrich`, `scheduler:lint`).

**Shutdown sequence**:
1. Set `_shutting_down = True` — new `spawn()` calls raise `RuntimeError`
2. `asyncio.wait(all_tasks, timeout=timeout)`
3. Cancel any remaining tasks
4. Await cancellation completion

**on_failure callback**: Optional; invoked after all retries exhausted. Can be used for alerting/logging.

### Task Classification

| Category | Tasks | max_retries | timeout |
|----------|-------|-------------|---------|
| `indexing:*` | #1-4 | 2 | None |
| `wiki:generate/quick/business` | #5-7 | 1 | None |
| `wiki:feedback-regen/sync-regen` | #8-9 | 0 | None |
| `scheduler:*` | #10-12 | 3 | None |

Scheduler tasks (#10-12) are daemon loops; on failure, they should restart. The supervisor handles this via retry with the loop coroutine factory.

### Integration Points

1. **`core/container.py`**: Add `task_supervisor: TaskSupervisor` field to `AppContainer`
2. **`main.py` lifespan**:
   - Init: `container.task_supervisor = TaskSupervisor()`
   - Shutdown: `await container.task_supervisor.shutdown()` (before store shutdown)
3. **Health endpoint**: Add `background_tasks` field with `active_tasks` count and `stats`
4. **12 call sites**: Replace `asyncio.create_task(coro)` with `supervisor.spawn(lambda: coro, name="...")`

### Migration per call site

| # | File | Current | After |
|---|------|---------|-------|
| 1 | `indexing_routes.py:86` | `asyncio.create_task(throttled_index_task(...))` | `supervisor.spawn(lambda: throttled_index_task(...), name="indexing:index", max_retries=2)` |
| 2 | `indexing_routes.py:186` | `asyncio.create_task(_throttled_index(...))` | `supervisor.spawn(lambda: _throttled_index(...), name="indexing:reindex", max_retries=2)` |
| 3 | `indexing_routes.py:221` | `asyncio.create_task(run_enrich_task(...))` | `supervisor.spawn(lambda: run_enrich_task(...), name="indexing:enrich", max_retries=2)` |
| 4 | `enrichment_coordinator.py:141` | `asyncio.create_task(self.run_enrichment_background(...))` | `supervisor.spawn(lambda: self.run_enrichment_background(...), name="indexing:enrichment-bg", max_retries=2)` |
| 5 | `wiki_task_routes.py:266` | `asyncio.create_task(_run_wiki_task(...))` | `supervisor.spawn(lambda: _run_wiki_task(...), name="wiki:generate", max_retries=1)` |
| 6 | `wiki_task_routes.py:361` | `asyncio.create_task(_run_wiki_quick_task(...))` | `supervisor.spawn(lambda: _run_wiki_quick_task(...), name="wiki:quick", max_retries=1)` |
| 7 | `wiki_task_routes.py:586` | `asyncio.create_task(_run_business_wiki_background(...))` | `supervisor.spawn(lambda: _run_business_wiki_background(...), name="wiki:business", max_retries=1)` |
| 8 | `bootstrap.py:147` | `asyncio.create_task(_task())` | `supervisor.spawn(lambda: _task(), name="wiki:feedback-regen")` |
| 9 | `business_sync_routes.py:478` | `asyncio.create_task(_wiki_bg())` | `supervisor.spawn(lambda: _wiki_bg(), name="wiki:sync-regen")` |
| 10 | `wiki_scheduler.py:68` | `asyncio.create_task(self._run_loop())` | `supervisor.spawn(lambda: self._run_loop(), name="scheduler:wiki", max_retries=3)` |
| 11 | `lint_scheduler.py:43` | `asyncio.create_task(self._loop())` | `supervisor.spawn(lambda: self._loop(), name="scheduler:lint", max_retries=3)` |
| 12 | `services/scheduler.py:134` | `asyncio.create_task(self._schedule_loop(...))` | `supervisor.spawn(lambda: self._schedule_loop(...), name="scheduler:sync", max_retries=3)` |

### Excluded (no migration)

| # | File | Reason |
|---|------|--------|
| 13 | `debounce.py:160` | Short-lived debounce timer, self-managed |
| 14 | `gateway_client.py:438` | Internal cleanup loop, self-managed lifecycle |
| 15 | `incremental_indexer.py:268` | Internal coroutine within same function scope |

## Test Plan

1. **spawn + done callback**: Verify task runs and is removed from `active_tasks` on completion
2. **cancel**: Verify task is cancelled and removed
3. **retry logic**: Failing task retries up to `max_retries`, then stops
4. **retry backoff**: Delay increases exponentially, capped at 60s
5. **timeout**: Task cancelled after timeout duration
6. **shutdown**: All tasks finish or are cancelled within timeout
7. **shutdown rejects new tasks**: `spawn()` raises `RuntimeError` after `shutdown()` called
8. **stats**: Counters increment correctly
9. **on_failure callback**: Called after retries exhausted
10. **concurrent tasks**: Multiple tasks can run simultaneously without interference
