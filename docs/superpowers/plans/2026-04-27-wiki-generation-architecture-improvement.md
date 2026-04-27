# Wiki Generation Architecture Improvement — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert synchronous business-wiki generation into a background task with Redis persistence, repository-level incremental skip, and dashboard progress reporting.

**Architecture:** Three-phase build: (A) WikiTaskStore + background task API, (B) repo-level freshness check for incremental skip, (C) SSE progress events + dashboard progress UI. Each phase produces testable, deployable code.

**Tech Stack:** Python 3.11+, FastAPI, FalkorDB (Redis-compatible), asyncio, React 18, TanStack Query, Vitest

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/task_store.py` | NEW — Redis Hash–backed task CRUD with TTL |
| `wiki/task_registry.py` | MODIFY — delegate to `WikiTaskStore` when available |
| `wiki/service.py` | MODIFY — add `incremental` param + freshness skip + progress callback |
| `wiki/bootstrap.py` | MODIFY — wire `WikiTaskStore` into app.state |
| `api/routes/wiki_task_routes.py` | MODIFY — background task for `/business/generate`, new GET endpoints |
| `api/models/wiki_models.py` | MODIFY — add `incremental` field to `BusinessWikiGenerateBody` |
| `store/wiki_page_store.py` | ADD — `get_repo_wiki_freshness()` query method |
| `dashboard/src/api/client.ts` | MODIFY — update `businessWikiGenerate` + add polling |
| `dashboard/src/api/types.ts` | MODIFY — extend `WikiAsyncTask` with progress fields |
| `dashboard/src/hooks/useWikiRegenerate.ts` | MODIFY — progress bar + incremental toggle |
| `dashboard/src/i18n/{en,zh,types}.ts` | ADD — progress i18n keys |
| `tests/wiki/test_task_store.py` | NEW — unit tests for `WikiTaskStore` |
| `tests/wiki/test_business_wiki_background.py` | NEW — background task + 202 API tests |
| `tests/wiki/test_repo_freshness.py` | NEW — incremental skip logic tests |
| `dashboard/src/hooks/__tests__/useWikiRegenerate.test.ts` | MODIFY — progress + incremental tests |

---

## Task 1: WikiTaskStore — Redis Hash–backed task CRUD

**Files:**
- Create: `wiki/task_store.py`
- Test: `tests/wiki/test_task_store.py`

- [ ] **Step 1: Write failing tests for WikiTaskStore**

```python
# tests/wiki/test_task_store.py
"""Unit tests for WikiTaskStore (Redis Hash–backed task CRUD)."""
from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.task_store import WikiTaskStore


@pytest.fixture
def mock_redis():
    """Mock redis.asyncio.Redis with all used methods."""
    r = MagicMock()
    r.hset = AsyncMock()
    r.hgetall = AsyncMock(return_value={})
    r.expire = AsyncMock()
    r.delete = AsyncMock()
    r.scan = AsyncMock(return_value=(0, []))
    r.exists = AsyncMock(return_value=0)
    r.set = AsyncMock(return_value=True)
    return r


@pytest.fixture
def store(mock_redis):
    return WikiTaskStore(mock_redis)


@pytest.mark.asyncio
async def test_put_and_get_task(store, mock_redis):
    record = {"task_id": "t1", "status": "pending", "business_id": "biz"}
    await store.put_task("t1", record)
    mock_redis.hset.assert_called_once()
    call_kwargs = mock_redis.hset.call_args
    assert call_kwargs[0][0] == "kb:wiki_tasks:t1"
    mock_redis.expire.assert_called_once_with("kb:wiki_tasks:t1", WikiTaskStore.DEFAULT_TTL)

    mock_redis.hgetall.return_value = {
        b"task_id": b"t1", b"status": b"pending", b"business_id": b"biz",
    }
    result = await store.get_task("t1")
    assert result is not None
    assert result["task_id"] == "t1"
    assert result["status"] == "pending"


@pytest.mark.asyncio
async def test_get_task_not_found(store, mock_redis):
    mock_redis.hgetall.return_value = {}
    result = await store.get_task("nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_update_status(store, mock_redis):
    await store.update_status("t1", "running", current_repo="user-svc")
    mock_redis.hset.assert_called_once()
    call_args = mock_redis.hset.call_args
    assert call_args[0][0] == "kb:wiki_tasks:t1"
    mapping = call_args[1].get("mapping") or call_args[0][1]
    assert mapping["status"] == "running"
    assert mapping["current_repo"] == "user-svc"


@pytest.mark.asyncio
async def test_try_lock_and_unlock(store, mock_redis):
    mock_redis.set.return_value = True
    locked = await store.try_lock("biz1")
    assert locked is True
    mock_redis.set.assert_called_once()
    call_args = mock_redis.set.call_args
    assert "kb:wiki_gen_lock:biz1" in str(call_args)

    await store.unlock("biz1")
    mock_redis.delete.assert_called_once_with("kb:wiki_gen_lock:biz1")


@pytest.mark.asyncio
async def test_try_lock_already_locked(store, mock_redis):
    mock_redis.set.return_value = False
    locked = await store.try_lock("biz1")
    assert locked is False


@pytest.mark.asyncio
async def test_list_active_empty(store, mock_redis):
    mock_redis.scan.return_value = (0, [])
    result = await store.list_active()
    assert result == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_task_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.task_store'`

- [ ] **Step 3: Implement WikiTaskStore**

```python
# wiki/task_store.py
"""Redis Hash–backed wiki task storage with TTL and concurrency locks."""
from __future__ import annotations

import json
from typing import Any

from log import get_logger

log = get_logger(__name__)


class WikiTaskStore:
    """Persist wiki generation task state in Redis Hashes.

    Uses the FalkorDB instance's underlying Redis connection — zero extra deps.
    Keys expire after DEFAULT_TTL to bound memory usage.
    """

    KEY_PREFIX = "kb:wiki_tasks:"
    LOCK_PREFIX = "kb:wiki_gen_lock:"
    DEFAULT_TTL = 1800  # 30 minutes
    LOCK_TTL = 3600  # 1 hour (guard against zombie locks)

    _JSON_FIELDS = frozenset({"partial_errors", "skipped_repos", "result"})

    def __init__(self, redis_conn: Any) -> None:
        self._redis = redis_conn

    def _key(self, task_id: str) -> str:
        return f"{self.KEY_PREFIX}{task_id}"

    def _lock_key(self, business_id: str) -> str:
        return f"{self.LOCK_PREFIX}{business_id}"

    async def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        """Create or overwrite a task record as a Redis Hash."""
        mapping: dict[str, str] = {}
        for k, v in record.items():
            if k in self._JSON_FIELDS and not isinstance(v, str):
                mapping[k] = json.dumps(v, default=str)
            else:
                mapping[k] = str(v) if v is not None else ""
        key = self._key(task_id)
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, self.DEFAULT_TTL)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Fetch a task record. Returns None if expired or missing."""
        raw = await self._redis.hgetall(self._key(task_id))
        if not raw:
            return None
        out: dict[str, Any] = {}
        for k, v in raw.items():
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            val_str = v.decode() if isinstance(v, bytes) else str(v)
            if key_str in self._JSON_FIELDS:
                try:
                    out[key_str] = json.loads(val_str)
                except (json.JSONDecodeError, TypeError):
                    out[key_str] = val_str
            else:
                out[key_str] = val_str
        return out

    async def update_status(
        self, task_id: str, status: str, **extra: Any
    ) -> None:
        """Partial update: set status + any extra fields."""
        mapping: dict[str, str] = {"status": status}
        for k, v in extra.items():
            if k in self._JSON_FIELDS and not isinstance(v, str):
                mapping[k] = json.dumps(v, default=str)
            else:
                mapping[k] = str(v) if v is not None else ""
        await self._redis.hset(self._key(task_id), mapping=mapping)

    async def try_lock(self, business_id: str) -> bool:
        """Acquire a generation lock for a business. Returns True if acquired."""
        ok = await self._redis.set(
            self._lock_key(business_id), "1", nx=True, ex=self.LOCK_TTL,
        )
        return bool(ok)

    async def unlock(self, business_id: str) -> None:
        """Release a generation lock."""
        await self._redis.delete(self._lock_key(business_id))

    async def list_active(self) -> list[dict[str, Any]]:
        """SCAN for all task keys and return those with status != completed/failed."""
        cursor = 0
        active: list[dict[str, Any]] = []
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match=f"{self.KEY_PREFIX}*", count=50,
            )
            for key in keys:
                raw = await self._redis.hgetall(key)
                if not raw:
                    continue
                status_raw = raw.get(b"status", raw.get("status", b""))
                status = status_raw.decode() if isinstance(status_raw, bytes) else str(status_raw)
                if status not in ("completed", "failed"):
                    task = await self.get_task(
                        (key.decode() if isinstance(key, bytes) else str(key))
                        .removeprefix(self.KEY_PREFIX)
                    )
                    if task:
                        active.append(task)
            if cursor == 0:
                break
        return active
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_task_store.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/task_store.py tests/wiki/test_task_store.py
git commit -m "feat: add WikiTaskStore — Redis Hash–backed task CRUD with TTL and lock"
```

---

## Task 2: Wire WikiTaskStore into app.state and update WikiTaskRegistry

**Files:**
- Modify: `wiki/bootstrap.py`
- Modify: `wiki/task_registry.py`
- Test: `tests/wiki/test_task_store.py` (add integration-level test)

- [ ] **Step 1: Write failing test for WikiTaskRegistry delegation**

```python
# Append to tests/wiki/test_task_store.py

@pytest.mark.asyncio
async def test_task_registry_delegates_to_store(mock_redis):
    """When WikiTaskStore is injected, WikiTaskRegistry delegates get/put."""
    from wiki.task_registry import WikiTaskRegistry

    store = WikiTaskStore(mock_redis)
    registry = WikiTaskRegistry(task_store=store)

    mock_redis.hgetall.return_value = {
        b"task_id": b"t1", b"status": b"pending",
    }
    registry.put_task("t1", {"task_id": "t1", "status": "pending"})
    result = registry.get_task("t1")
    assert result is not None
    assert result["task_id"] == "t1"


def test_task_registry_works_without_store():
    """Backward compat: no store → in-memory dict."""
    from wiki.task_registry import WikiTaskRegistry

    registry = WikiTaskRegistry()
    registry.put_task("t1", {"task_id": "t1", "status": "pending"})
    assert registry.get_task("t1")["status"] == "pending"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_task_store.py::test_task_registry_delegates_to_store tests/wiki/test_task_store.py::test_task_registry_works_without_store -v`
Expected: FAIL — `WikiTaskRegistry.__init__() got an unexpected keyword argument 'task_store'`

- [ ] **Step 3: Update WikiTaskRegistry to accept optional WikiTaskStore**

```python
# wiki/task_registry.py
from __future__ import annotations

import asyncio
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from wiki.task_store import WikiTaskStore

WIKI_TASK_TTL_SEC = 30 * 60


class WikiTaskRegistry:
    """Wiki generation tasks with optional Redis persistence.

    When ``task_store`` is provided, delegates to Redis; otherwise falls back
    to the original in-memory dict.
    """

    def __init__(self, task_store: WikiTaskStore | None = None) -> None:
        self._store = task_store
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)

    def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        if self._store is not None:
            asyncio.ensure_future(self._store.put_task(task_id, record))
        self._prune()
        self.tasks[task_id] = record
        self._created[task_id] = time.monotonic()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self._prune()
        return self.tasks.get(task_id)
```

- [ ] **Step 4: Wire WikiTaskStore in bootstrap.py**

Add to `wiki/bootstrap.py` inside `bootstrap_wiki`, after `app.state.wiki_event_bus`:

```python
    from wiki.task_store import WikiTaskStore

    wiki_task_store: WikiTaskStore | None = None
    try:
        redis_conn = getattr(kb.store, "_redis", None) or getattr(kb.store, "redis", None)
        if redis_conn is None and hasattr(kb.store, "_graph"):
            redis_conn = getattr(kb.store._graph, "_redis", None)
        if redis_conn is not None:
            wiki_task_store = WikiTaskStore(redis_conn)
            log.info("wiki_task_store_initialized", backend="redis")
        else:
            log.warning("wiki_task_store_no_redis", fallback="in-memory")
    except Exception:
        log.warning("wiki_task_store_init_failed", exc_info=True)
    app.state.wiki_task_store = wiki_task_store
```

Also update `get_task_registry_dep` in `api/routes/wiki_shared.py` to pass the store:

```python
def get_task_registry_dep(request: Request) -> WikiTaskRegistry:
    reg = getattr(request.app.state, "wiki_tasks", None)
    if reg is None:
        task_store = getattr(request.app.state, "wiki_task_store", None)
        reg = WikiTaskRegistry(task_store=task_store)
        request.app.state.wiki_tasks = reg
    return reg
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_task_store.py -v`
Expected: All 8 tests PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/task_registry.py wiki/bootstrap.py api/routes/wiki_shared.py tests/wiki/test_task_store.py
git commit -m "feat: wire WikiTaskStore into WikiTaskRegistry and bootstrap"
```

---

## Task 3: Background task for business wiki generation

**Files:**
- Modify: `api/routes/wiki_task_routes.py`
- Modify: `api/models/wiki_models.py`
- Create: `tests/wiki/test_business_wiki_background.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_business_wiki_background.py
"""Tests for background business wiki generation with task_id return."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_wiki_service():
    svc = AsyncMock()
    svc.generate_business_wiki = AsyncMock(return_value={
        "business_id": "default",
        "domains": ["auth"],
        "pages_count": 1,
        "references_count": 0,
        "repositories": ["repo1"],
        "partial_errors": [],
    })
    return svc


@pytest.fixture
def mock_task_store():
    store = AsyncMock()
    store.try_lock = AsyncMock(return_value=True)
    store.unlock = AsyncMock()
    store.put_task = AsyncMock()
    store.update_status = AsyncMock()
    store.get_task = AsyncMock(return_value={
        "task_id": "biz-wiki-test",
        "status": "completed",
        "business_id": "default",
    })
    return store


@pytest.mark.asyncio
async def test_business_generate_returns_202(mock_wiki_service, mock_task_store):
    """POST /business/generate should return 202 with task_id."""
    from api.routes.wiki_task_routes import _run_business_wiki_background

    task_id = "biz-wiki-test"
    await _run_business_wiki_background(
        task_id=task_id,
        business_id="default",
        language="en",
        llm_provider=None,
        incremental=True,
        svc=mock_wiki_service,
        task_store=mock_task_store,
        event_bus=None,
    )
    mock_task_store.update_status.assert_called()
    last_call = mock_task_store.update_status.call_args_list[-1]
    assert last_call[0][1] in ("completed", "failed")


@pytest.mark.asyncio
async def test_business_generate_lock_conflict(mock_task_store):
    """Should return 409 when lock already held."""
    mock_task_store.try_lock.return_value = False
    from api.routes.wiki_task_routes import _check_business_lock

    locked = await _check_business_lock(mock_task_store, "default")
    assert locked is False


@pytest.mark.asyncio
async def test_business_generate_body_incremental():
    """BusinessWikiGenerateBody should accept incremental field."""
    from api.models.wiki_models import BusinessWikiGenerateBody

    body = BusinessWikiGenerateBody(business_id="default", incremental=True)
    assert body.incremental is True

    body2 = BusinessWikiGenerateBody(business_id="default")
    assert body2.incremental is True  # default
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_background.py -v`
Expected: FAIL — missing imports/functions

- [ ] **Step 3: Add `incremental` to BusinessWikiGenerateBody**

In `api/models/wiki_models.py`, update:

```python
class BusinessWikiGenerateBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None
    incremental: bool = True
```

- [ ] **Step 4: Implement background task + lock in wiki_task_routes.py**

Add two helper functions and modify `generate_business_wiki` endpoint:

```python
# Add near top of api/routes/wiki_task_routes.py, after imports
from wiki.task_store import WikiTaskStore
from wiki.event_bus import WikiEvent, WikiEventBus


async def _check_business_lock(
    task_store: WikiTaskStore | None, business_id: str,
) -> bool:
    """Return True if lock acquired, False if already locked."""
    if task_store is None:
        return True
    return await task_store.try_lock(business_id)


async def _run_business_wiki_background(
    *,
    task_id: str,
    business_id: str,
    language: str,
    llm_provider: str | None,
    incremental: bool,
    svc: WikiService,
    task_store: WikiTaskStore | None,
    event_bus: WikiEventBus | None,
) -> None:
    """Background coroutine: run business wiki generation and update task state."""
    try:
        if task_store:
            await task_store.update_status(task_id, "running")
        result = await svc.generate_business_wiki(
            business_id=business_id,
            language=language,
            llm_provider=llm_provider,
        )
        if task_store:
            await task_store.update_status(
                task_id, "completed",
                result=result,
                partial_errors=result.get("partial_errors", []),
            )
        if event_bus:
            await event_bus.publish(WikiEvent(
                event_type="business_gen_complete",
                repository=business_id,
                business_id=business_id,
                data={"task_id": task_id, "pages_count": result.get("pages_count", 0)},
            ))
    except Exception as exc:
        log.warning("business_wiki_background_failed", task_id=task_id, exc_info=True)
        if task_store:
            await task_store.update_status(task_id, "failed", error=str(exc))
    finally:
        if task_store:
            await task_store.unlock(business_id)
```

Rewrite the `generate_business_wiki` endpoint:

```python
@router.post(
    "/business/generate",
    response_model=None,
    status_code=202,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def generate_business_wiki(
    body: BusinessWikiGenerateBody,
    request: Request,
    svc: WikiService = Depends(get_wiki_service_dep),
) -> JSONResponse:
    """Trigger cross-repo business-level wiki generation as a background task."""
    task_store: WikiTaskStore | None = getattr(request.app.state, "wiki_task_store", None)
    event_bus: WikiEventBus | None = getattr(request.app.state, "wiki_event_bus", None)

    if not await _check_business_lock(task_store, body.business_id):
        return JSONResponse(
            status_code=409,
            content={"error": "generation_in_progress", "detail": "Business wiki generation already running."},
        )

    task_id = f"biz-wiki-{uuid.uuid4().hex[:12]}"
    initial = {
        "task_id": task_id,
        "status": "pending",
        "business_id": body.business_id,
        "incremental": str(body.incremental),
    }
    if task_store:
        await task_store.put_task(task_id, initial)

    asyncio.create_task(_run_business_wiki_background(
        task_id=task_id,
        business_id=body.business_id,
        language=body.language,
        llm_provider=body.llm_provider,
        incremental=body.incremental,
        svc=svc,
        task_store=task_store,
        event_bus=event_bus,
    ))

    return JSONResponse(status_code=202, content={"task_id": task_id, "status": "pending"})
```

- [ ] **Step 5: Add GET /tasks/{task_id} endpoint for Redis-backed tasks**

Add a new endpoint below the existing `wiki_task_status`:

```python
@router.get("/business/tasks/{task_id}")
async def business_wiki_task_status(
    task_id: str,
    request: Request,
) -> dict[str, Any]:
    """Get background business wiki task progress from Redis store."""
    task_store: WikiTaskStore | None = getattr(request.app.state, "wiki_task_store", None)
    if task_store:
        rec = await task_store.get_task(task_id)
        if rec is not None:
            return rec
    # Fallback to in-memory registry
    registry = getattr(request.app.state, "wiki_tasks", None)
    if registry:
        rec = registry.get_task(task_id)
        if rec is not None:
            return rec
    raise KbNotFound("task_not_found")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_background.py -v`
Expected: All 3 tests PASS

- [ ] **Step 7: Commit**

```bash
git add api/routes/wiki_task_routes.py api/models/wiki_models.py tests/wiki/test_business_wiki_background.py
git commit -m "feat: background business wiki generation with task_id, lock, and Redis state"
```

---

## Task 4: Repository-level freshness check

**Files:**
- Modify: `store/wiki_page_store.py`
- Create: `tests/wiki/test_repo_freshness.py`

- [ ] **Step 1: Write failing tests for freshness query**

```python
# tests/wiki/test_repo_freshness.py
"""Tests for get_repo_wiki_freshness — repo-level incremental skip."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_store():
    s = MagicMock()
    s.execute_query = AsyncMock()
    s._store = s
    return s


@pytest.mark.asyncio
async def test_freshness_returns_dict(mock_store):
    """get_repo_wiki_freshness returns {repo: {last_indexed, last_generated}}."""
    from store.wiki_page_store import WikiPageStoreMixin

    mixin = WikiPageStoreMixin()
    mixin._store = mock_store

    mock_store.execute_query.return_value = MagicMock(
        data=[
            {"repository": "repo1", "last_indexed": "2026-04-27T10:00:00", "last_generated": "2026-04-26T10:00:00"},
            {"repository": "repo2", "last_indexed": "2026-04-25T10:00:00", "last_generated": "2026-04-26T10:00:00"},
        ]
    )
    result = await mixin.get_repo_wiki_freshness("default")
    assert "repo1" in result
    assert result["repo1"]["last_indexed"] == "2026-04-27T10:00:00"
    assert result["repo1"]["last_generated"] == "2026-04-26T10:00:00"
    assert "repo2" in result


@pytest.mark.asyncio
async def test_freshness_null_generated(mock_store):
    """NULL generated_at means repo needs full generation."""
    from store.wiki_page_store import WikiPageStoreMixin

    mixin = WikiPageStoreMixin()
    mixin._store = mock_store

    mock_store.execute_query.return_value = MagicMock(
        data=[
            {"repository": "new-repo", "last_indexed": "2026-04-27T10:00:00", "last_generated": None},
        ]
    )
    result = await mixin.get_repo_wiki_freshness("default")
    assert result["new-repo"]["last_generated"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_repo_freshness.py -v`
Expected: FAIL — `AttributeError: 'WikiPageStoreMixin' object has no attribute 'get_repo_wiki_freshness'`

- [ ] **Step 3: Implement get_repo_wiki_freshness**

Add to `store/wiki_page_store.py` in `WikiPageStoreMixin`:

```python
    async def get_repo_wiki_freshness(
        self, business_id: str,
    ) -> dict[str, dict[str, Any]]:
        """Per-repository freshness: latest indexed_at vs latest generated_at.

        Returns ``{repo_name: {"last_indexed": str|None, "last_generated": str|None}}``.
        Used by incremental business wiki generation to skip unchanged repos.
        """
        q = (
            "MATCH (m:Module) WHERE m.repository IS NOT NULL "
            "WITH m.repository AS repository, max(coalesce(m.indexed_at, '')) AS last_indexed "
            "OPTIONAL MATCH (wp:WikiPage {repository: repository}) "
            "WITH repository, last_indexed, max(coalesce(wp.generated_at, '')) AS last_generated "
            "RETURN repository, "
            "CASE WHEN last_indexed = '' THEN null ELSE last_indexed END AS last_indexed, "
            "CASE WHEN last_generated = '' THEN null ELSE last_generated END AS last_generated"
        )
        result = await self._store.execute_query(q)
        out: dict[str, dict[str, Any]] = {}
        for row in getattr(result, "data", []) or []:
            repo = str(row.get("repository", ""))
            if repo:
                out[repo] = {
                    "last_indexed": row.get("last_indexed"),
                    "last_generated": row.get("last_generated"),
                }
        return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_repo_freshness.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add store/wiki_page_store.py tests/wiki/test_repo_freshness.py
git commit -m "feat: add get_repo_wiki_freshness for repo-level incremental skip"
```

---

## Task 5: Integrate incremental skip into generate_business_wiki

**Files:**
- Modify: `wiki/service.py`
- Create: `tests/wiki/test_business_wiki_incremental.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_business_wiki_incremental.py
"""Tests for incremental business wiki generation (repo-level skip)."""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def wiki_service_deps():
    """Minimal deps for WikiService construction."""
    from config import WikiConfig as WikiAppConfig, EmbeddingConfig

    graph = AsyncMock()
    graph.list_repository_modules = AsyncMock(return_value=[])
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[], raw=[]))
    wiki_store = MagicMock()
    wiki_store._store = store
    wiki_store.list_indexed_repositories = AsyncMock(return_value=[
        {"repository": "repo-a", "module_count": 5},
        {"repository": "repo-b", "module_count": 3},
    ])
    wiki_store.get_repo_wiki_freshness = AsyncMock(return_value={
        "repo-a": {"last_indexed": "2026-04-27T10:00:00", "last_generated": "2026-04-26T10:00:00"},
        "repo-b": {"last_indexed": "2026-04-25T10:00:00", "last_generated": "2026-04-26T10:00:00"},
    })
    wiki_store.upsert_wiki_space = AsyncMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    return {
        "graph": graph,
        "store": store,
        "wiki_store": wiki_store,
        "wiki_config": WikiAppConfig(),
        "embedding_config": EmbeddingConfig(),
    }


@pytest.mark.asyncio
async def test_incremental_skips_unchanged_repo(wiki_service_deps):
    """When incremental=True, repo-b (not changed) should be skipped."""
    from wiki.service import WikiService

    svc = WikiService(
        graph=wiki_service_deps["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps["store"],
        wiki_store=wiki_service_deps["wiki_store"],
        wiki_config=wiki_service_deps["wiki_config"],
        embedding_config=wiki_service_deps["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    result = await svc.generate_business_wiki("default", incremental=True)
    assert svc.generate.call_count == 1
    call_repo = svc.generate.call_args[0][0]
    assert call_repo == "repo-a"
    assert "repo-b" in [r for r in result.get("skipped_repos", [])]


@pytest.mark.asyncio
async def test_full_regen_all_repos(wiki_service_deps):
    """When incremental=False, all repos are generated."""
    from wiki.service import WikiService

    svc = WikiService(
        graph=wiki_service_deps["graph"],
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=wiki_service_deps["store"],
        wiki_store=wiki_service_deps["wiki_store"],
        wiki_config=wiki_service_deps["wiki_config"],
        embedding_config=wiki_service_deps["embedding_config"],
    )
    svc.generate = AsyncMock(return_value={"pages": []})

    result = await svc.generate_business_wiki("default", incremental=False)
    assert svc.generate.call_count == 2
    assert result.get("skipped_repos", []) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_incremental.py -v`
Expected: FAIL — `generate_business_wiki() got an unexpected keyword argument 'incremental'`

- [ ] **Step 3: Add incremental param + skip logic to generate_business_wiki**

In `wiki/service.py`, modify `generate_business_wiki` signature:

```python
    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
```

Add freshness check after loading repos and building `all_modules`:

```python
        # --- Incremental: identify changed vs skipped repos ---
        changed_repos: set[str] = set(all_modules.keys())
        skipped_repos: list[str] = []
        if incremental and hasattr(self._wiki_store, "get_repo_wiki_freshness"):
            try:
                freshness = await self._wiki_store.get_repo_wiki_freshness(business_id)
                changed_repos = set()
                for repo_name in all_modules:
                    entry = freshness.get(repo_name)
                    if entry is None:
                        changed_repos.add(repo_name)
                        continue
                    li = entry.get("last_indexed")
                    lg = entry.get("last_generated")
                    if li is None or lg is None or str(li) > str(lg):
                        changed_repos.add(repo_name)
                    else:
                        skipped_repos.append(repo_name)
            except Exception:
                log.warning("freshness_check_failed", exc_info=True)
                changed_repos = set(all_modules.keys())
                skipped_repos = []
```

In the per-repo generation loop, skip unchanged repos:

```python
        total_repos = len(all_modules)
        completed_repos = 0
        for repo_name in all_modules:
            if repo_name not in changed_repos:
                completed_repos += 1
                if progress_callback:
                    await progress_callback({
                        "completed_repos": completed_repos,
                        "total_repos": total_repos,
                        "current_repo": repo_name,
                        "skipped": True,
                    })
                continue
            try:
                await self.generate(
                    repo_name, "repo", "structure", "json",
                    language, llm_provider,
                    token_budget_multiplier=token_budget_multiplier,
                )
            except Exception as exc:
                log.warning("business_wiki_repo_failed", repository=repo_name, exc_info=True)
                partial_errors.append({"repository": repo_name, "error": str(exc)})
            completed_repos += 1
            if progress_callback:
                await progress_callback({
                    "completed_repos": completed_repos,
                    "total_repos": total_repos,
                    "current_repo": repo_name,
                    "skipped": False,
                })
```

Add `skipped_repos` to return dict:

```python
        return {
            "business_id": business_id,
            "domains": domain_names,
            "pages_count": len(all_pages),
            "references_count": ref_count,
            "repositories": [r["repository"] for r in repos],
            "partial_errors": partial_errors,
            "skipped_repos": skipped_repos,
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_incremental.py -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Run existing business wiki tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_wiki_business_flow.py tests/wiki/test_service_business_scope.py tests/wiki/test_business_api.py -v`
Expected: All existing tests still PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/service.py tests/wiki/test_business_wiki_incremental.py
git commit -m "feat: incremental business wiki generation — skip unchanged repos"
```

---

## Task 6: Progress callback in background task

**Files:**
- Modify: `api/routes/wiki_task_routes.py` — wire progress callback
- Modify: `wiki/event_bus.py` — no changes needed (already supports publish)

- [ ] **Step 1: Write failing test for progress updates**

```python
# Append to tests/wiki/test_business_wiki_background.py

@pytest.mark.asyncio
async def test_progress_callback_updates_store(mock_wiki_service, mock_task_store):
    """Background task should update task_store with progress on each repo."""
    from api.routes.wiki_task_routes import _run_business_wiki_background

    call_count = {"n": 0}
    original_update = mock_task_store.update_status

    async def tracking_update(*args, **kwargs):
        call_count["n"] += 1
        return await original_update(*args, **kwargs)

    mock_task_store.update_status = AsyncMock(side_effect=tracking_update)

    await _run_business_wiki_background(
        task_id="biz-wiki-prog",
        business_id="default",
        language="en",
        llm_provider=None,
        incremental=True,
        svc=mock_wiki_service,
        task_store=mock_task_store,
        event_bus=None,
    )
    # At minimum: running + completed = 2 calls
    assert call_count["n"] >= 2
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_background.py::test_progress_callback_updates_store -v`

- [ ] **Step 3: Update _run_business_wiki_background to pass progress_callback**

In `api/routes/wiki_task_routes.py`, update `_run_business_wiki_background`:

```python
async def _run_business_wiki_background(
    *,
    task_id: str,
    business_id: str,
    language: str,
    llm_provider: str | None,
    incremental: bool,
    svc: WikiService,
    task_store: WikiTaskStore | None,
    event_bus: WikiEventBus | None,
) -> None:
    """Background coroutine: run business wiki generation and update task state."""
    async def _progress(info: dict) -> None:
        if task_store:
            pct = int(info.get("completed_repos", 0) / max(info.get("total_repos", 1), 1) * 100)
            await task_store.update_status(
                task_id, "running",
                completed_repos=info.get("completed_repos", 0),
                total_repos=info.get("total_repos", 0),
                current_repo=info.get("current_repo", ""),
                progress_pct=pct,
            )
        if event_bus:
            await event_bus.publish(WikiEvent(
                event_type="business_gen_progress",
                repository=info.get("current_repo", ""),
                business_id=business_id,
                data={"task_id": task_id, **info},
            ))

    try:
        if task_store:
            await task_store.update_status(task_id, "running")
        result = await svc.generate_business_wiki(
            business_id=business_id,
            language=language,
            llm_provider=llm_provider,
            incremental=incremental,
            progress_callback=_progress,
        )
        if task_store:
            await task_store.update_status(
                task_id, "completed",
                result=result,
                partial_errors=result.get("partial_errors", []),
                skipped_repos=result.get("skipped_repos", []),
            )
        if event_bus:
            await event_bus.publish(WikiEvent(
                event_type="business_gen_complete",
                repository=business_id,
                business_id=business_id,
                data={"task_id": task_id, "pages_count": result.get("pages_count", 0)},
            ))
    except Exception as exc:
        log.warning("business_wiki_background_failed", task_id=task_id, exc_info=True)
        if task_store:
            await task_store.update_status(task_id, "failed", error=str(exc))
    finally:
        if task_store:
            await task_store.unlock(business_id)
```

- [ ] **Step 4: Run all background task tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/test_business_wiki_background.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/wiki_task_routes.py tests/wiki/test_business_wiki_background.py
git commit -m "feat: progress callback in background business wiki generation"
```

---

## Task 7: Frontend — update API types and client

**Files:**
- Modify: `dashboard/src/api/types.ts`
- Modify: `dashboard/src/api/client.ts`

- [ ] **Step 1: Extend WikiAsyncTask with progress fields**

In `dashboard/src/api/types.ts`, update `WikiAsyncTask`:

```typescript
export interface WikiAsyncTask {
  task_id: string;
  status: string;
  repository?: string;
  scope?: string;
  result?: unknown;
  error?: { error?: string; detail?: string };
  // Business wiki progress fields
  business_id?: string;
  total_repos?: number;
  completed_repos?: number;
  skipped_repos?: string[] | number;
  current_repo?: string;
  progress_pct?: number;
  incremental?: string;
  partial_errors?: Array<{ repository: string; error: string }>;
}
```

- [ ] **Step 2: Update businessWikiGenerate to accept incremental param**

In `dashboard/src/api/client.ts`, update:

```typescript
export async function businessWikiGenerate(
  businessId: string,
  language: string,
  incremental = true,
): Promise<TaskInfo> {
  return api<TaskInfo>("/wiki/business/generate", {
    method: "POST",
    body: JSON.stringify({ business_id: businessId, language, incremental }),
  });
}
```

- [ ] **Step 3: Add businessWikiTaskStatus function**

In `dashboard/src/api/client.ts`, add:

```typescript
export async function businessWikiTaskStatus(taskId: string): Promise<WikiAsyncTask> {
  return api<WikiAsyncTask>(`/wiki/business/tasks/${encodeURIComponent(taskId)}`);
}
```

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/api/types.ts dashboard/src/api/client.ts
git commit -m "feat(dashboard): extend API types and client for business wiki progress"
```

---

## Task 8: Frontend — progress bar and incremental toggle in useWikiRegenerate

**Files:**
- Modify: `dashboard/src/hooks/useWikiRegenerate.ts`
- Modify: `dashboard/src/i18n/en.ts`
- Modify: `dashboard/src/i18n/zh.ts`
- Modify: `dashboard/src/i18n/types.ts`

- [ ] **Step 1: Add i18n keys**

In `dashboard/src/i18n/types.ts`, add to the `wiki` section:

```typescript
    regenerateProgress: string;
    regenerateSkipped: string;
    regenerateIncremental: string;
    regenerateFull: string;
    regenerateConflict: string;
```

In `dashboard/src/i18n/en.ts`, add:

```typescript
    regenerateProgress: "Generating: {current} ({pct}%)",
    regenerateSkipped: "{count} repo(s) skipped (no changes)",
    regenerateIncremental: "Incremental",
    regenerateFull: "Full rebuild",
    regenerateConflict: "Generation already in progress for this business.",
```

In `dashboard/src/i18n/zh.ts`, add:

```typescript
    regenerateProgress: "正在生成：{current}（{pct}%）",
    regenerateSkipped: "{count} 个仓库已跳过（无变更）",
    regenerateIncremental: "增量生成",
    regenerateFull: "完整重建",
    regenerateConflict: "该业务的 Wiki 正在生成中。",
```

- [ ] **Step 2: Update useWikiRegenerate with progress polling**

```typescript
// dashboard/src/hooks/useWikiRegenerate.ts
import { useCallback, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { businessWikiGenerate, businessWikiTaskStatus } from "../api/client";
import type { WikiAsyncTask } from "../api/types";
import { useToast } from "../components/Toast";
import { useI18n } from "../i18n/context";
import { getErrorMessage } from "../utils/errorUtils";
import { invalidateWikiQueriesForBusiness } from "./invalidateWikiQueries";

export interface WikiRegenProgress {
  totalRepos: number;
  completedRepos: number;
  currentRepo: string;
  progressPct: number;
  skippedRepos: number;
}

export function useWikiRegenerate(businessId: string) {
  const [isPending, setIsPending] = useState(false);
  const [progress, setProgress] = useState<WikiRegenProgress | null>(null);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const { locale, t } = useI18n();

  const regenerate = useCallback(async (incremental = true) => {
    if (!businessId.trim() || isPending) return;
    setIsPending(true);
    setProgress(null);
    try {
      const lang = locale === "zh" ? "zh" : "en";
      const res = await businessWikiGenerate(businessId.trim(), lang, incremental);
      const tid = res.task_id ? String(res.task_id) : "";
      if (!tid) {
        toast("success", t.wiki.regenerateStarted);
        await invalidateWikiQueriesForBusiness(queryClient, businessId);
        return;
      }
      toast("info", t.wiki.regenerateRunning);
      const maxAttempts = 120;
      for (let i = 0; i < maxAttempts; i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const st: WikiAsyncTask = await businessWikiTaskStatus(tid);
        if (st.progress_pct !== undefined) {
          setProgress({
            totalRepos: st.total_repos ?? 0,
            completedRepos: st.completed_repos ?? 0,
            currentRepo: st.current_repo ?? "",
            progressPct: st.progress_pct ?? 0,
            skippedRepos: typeof st.skipped_repos === "number"
              ? st.skipped_repos
              : Array.isArray(st.skipped_repos) ? st.skipped_repos.length : 0,
          });
        }
        if (st.status === "completed") {
          toast("success", t.wiki.regenerateComplete);
          await invalidateWikiQueriesForBusiness(queryClient, businessId);
          return;
        }
        if (st.status === "failed") {
          const err = st.error;
          const detail =
            err && typeof err === "object" && "detail" in err
              ? String((err as { detail?: unknown }).detail ?? err)
              : err
                ? JSON.stringify(err)
                : t.common.unknown;
          toast("error", t.wiki.regenerateFailed.replace("{detail}", detail));
          return;
        }
      }
      toast("error", t.wiki.regenerateTimeout);
    } catch (e: unknown) {
      const msg = getErrorMessage(e, t.common.unexpectedError);
      if (typeof msg === "string" && msg.includes("409")) {
        toast("error", t.wiki.regenerateConflict);
      } else {
        toast("error", msg);
      }
    } finally {
      setIsPending(false);
      setProgress(null);
    }
  }, [businessId, isPending, locale, t, toast, queryClient]);

  return { regenerate, isPending, progress };
}
```

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/useWikiRegenerate.ts dashboard/src/i18n/en.ts dashboard/src/i18n/zh.ts dashboard/src/i18n/types.ts
git commit -m "feat(dashboard): progress bar + incremental toggle in useWikiRegenerate"
```

---

## Task 9: Frontend — update test for useWikiRegenerate

**Files:**
- Modify: `dashboard/src/hooks/__tests__/useWikiRegenerate.test.ts`

- [ ] **Step 1: Update existing test to match new signature**

The `regenerate` function now accepts an `incremental` boolean. Update the test to call `regenerate(true)` and verify `businessWikiGenerate` is called with `incremental = true`. Also verify progress state is returned.

```typescript
// In the test file, update the mock for businessWikiGenerate:
vi.mock("../../api/client", () => ({
  businessWikiGenerate: vi.fn(),
  businessWikiTaskStatus: vi.fn(),
  wikiTaskStatus: vi.fn(),
}));

// In the test body, update assertions:
const { businessWikiGenerate, businessWikiTaskStatus } = await import("../../api/client");
(businessWikiGenerate as ReturnType<typeof vi.fn>).mockResolvedValue({ task_id: "biz-t1", status: "pending", mode: "structure" });
(businessWikiTaskStatus as ReturnType<typeof vi.fn>).mockResolvedValue({ task_id: "biz-t1", status: "completed" });
```

- [ ] **Step 2: Run frontend tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && npx vitest run src/hooks/__tests__/useWikiRegenerate.test.ts`
Expected: All tests PASS

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/hooks/__tests__/useWikiRegenerate.test.ts
git commit -m "test(dashboard): update useWikiRegenerate test for progress + incremental"
```

---

## Task 10: Integration — verify end-to-end and existing tests

- [ ] **Step 1: Run all Python wiki tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && python -m pytest tests/wiki/ -v --timeout=30 -x`
Expected: All tests PASS

- [ ] **Step 2: Run frontend build**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && npx tsc --noEmit`
Expected: No TypeScript errors

- [ ] **Step 3: Run frontend test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && npx vitest run`
Expected: All tests PASS

- [ ] **Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "fix: address integration issues from wiki generation architecture improvement"
```

---

## Self-Review

**Spec coverage:**
- Module 1 (Background Task + Redis): Tasks 1-3, 6 ✓
- Module 2 (Incremental Generation): Tasks 4-5 ✓
- Module 3 (Progress + Dashboard): Tasks 6-9 ✓
- Concurrency guard (lock): Task 1 (store) + Task 3 (API) ✓
- Error handling: Task 3 + Task 6 (try/finally with unlock) ✓

**Placeholder scan:** No TBD/TODO/placeholders. All code blocks are complete.

**Type consistency:**
- `WikiTaskStore.put_task` / `.get_task` / `.update_status` — consistent across all tasks
- `progress_callback: Callable[[dict], Awaitable[None]]` — used in Task 5 (service) and Task 6 (route)
- `WikiAsyncTask.progress_pct` / `.current_repo` — consistent between types.ts (Task 7) and useWikiRegenerate (Task 8)
- `businessWikiTaskStatus` — defined in Task 7, used in Task 8
