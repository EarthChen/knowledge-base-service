# SP1: Backend Architecture Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish typed domain exceptions, request-scoped context, configuration DI, and persistent ConversationStore as foundation for all subsequent sub-projects.

**Architecture:** Replace ad-hoc error handling with a typed exception hierarchy caught by global middleware. Introduce `contextvars` for request-scoped business_id/request_id propagation. Move `get_settings()` out of service layer. Persist conversations to SQLite.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, aiosqlite, contextvars, pytest

---

### Task 1: Typed Domain Exception Hierarchy

**Files:**
- Create: `api/exceptions.py`
- Modify: `api/error_handler.py`
- Test: `tests/api/test_exceptions.py`

- [ ] **Step 1: Write failing test for exception → HTTP mapping**

```python
# tests/api/test_exceptions.py
import pytest
from api.exceptions import KbClientError, KbConflict, KbForbidden, KbNotFound, KbServiceUnavailable


def test_kb_not_found_has_404():
    exc = KbNotFound("repo not found")
    assert exc.status_code == 404
    assert exc.message == "repo not found"


def test_kb_client_error_has_400():
    exc = KbClientError("bad input", detail="field X required")
    assert exc.status_code == 400
    assert exc.detail == "field X required"


def test_kb_conflict_has_409():
    assert KbConflict("already exists").status_code == 409


def test_kb_service_unavailable_has_503():
    assert KbServiceUnavailable("db down").status_code == 503


def test_kb_forbidden_has_403():
    assert KbForbidden("not allowed").status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_exceptions.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.exceptions'`

- [ ] **Step 3: Create the exception module**

```python
# api/exceptions.py
"""Typed domain exception hierarchy for HTTP error mapping."""
from __future__ import annotations


class KbError(Exception):
    """Base for all knowledge-base domain errors."""

    status_code: int = 500

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        self.message = message
        self.detail = detail
        super().__init__(message)


class KbClientError(KbError):
    status_code = 400


class KbNotFound(KbError):
    status_code = 404


class KbConflict(KbError):
    status_code = 409


class KbForbidden(KbError):
    status_code = 403


class KbServiceUnavailable(KbError):
    status_code = 503
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_exceptions.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Wire exceptions into error_handler.py**

Modify `api/error_handler.py` — add KbError handling in `_public_error_for_exception`:

```python
# At the top of _public_error_for_exception, before existing checks:
from api.exceptions import KbError

def _public_error_for_exception(exc: BaseException) -> tuple[int, str, str]:
    if isinstance(exc, KbError):
        code = exc.__class__.__name__
        # Convert CamelCase to snake_case for error code
        import re
        err_code = re.sub(r"(?<!^)(?=[A-Z])", "_", code).lower()
        return exc.status_code, err_code, exc.message
    # ... rest of existing logic unchanged ...
```

- [ ] **Step 6: Write integration test for error handler**

```python
# tests/api/test_exceptions.py (append)
import re
from api.error_handler import _public_error_for_exception
from api.exceptions import KbNotFound, KbClientError


def test_error_handler_maps_kb_not_found():
    status, code, msg = _public_error_for_exception(KbNotFound("repo X"))
    assert status == 404
    assert code == "kb_not_found"
    assert msg == "repo X"


def test_error_handler_maps_kb_client_error():
    status, code, msg = _public_error_for_exception(KbClientError("bad input"))
    assert status == 400
    assert code == "kb_client_error"
    assert msg == "bad input"
```

- [ ] **Step 7: Run all exception tests**

Run: `uv run pytest tests/api/test_exceptions.py -v`
Expected: All 7 tests PASS

- [ ] **Step 8: Commit**

```bash
git add api/exceptions.py api/error_handler.py tests/api/test_exceptions.py
git commit -m "feat(sp1): add typed domain exception hierarchy with error handler integration"
```

---

### Task 2: Request-Scoped Context

**Files:**
- Create: `api/request_context.py`
- Modify: `api/middleware/request_logging.py`
- Test: `tests/api/test_request_context.py`

- [ ] **Step 1: Write failing test for context accessors**

```python
# tests/api/test_request_context.py
import asyncio
import pytest
from api.request_context import (
    get_current_business,
    get_current_request_id,
    set_current_business,
    set_current_request_id,
)


def test_default_business_id():
    assert get_current_business() == "default"


def test_default_request_id():
    assert get_current_request_id() == ""


def test_set_and_get_business():
    token = set_current_business("acme")
    assert get_current_business() == "acme"
    # Reset
    from api.request_context import _business_id
    _business_id.reset(token)
    assert get_current_business() == "default"


@pytest.mark.asyncio
async def test_context_isolated_across_tasks():
    """Concurrent tasks should not see each other's context."""
    results = []

    async def worker(biz: str):
        set_current_business(biz)
        await asyncio.sleep(0.01)
        results.append(get_current_business())

    await asyncio.gather(worker("alpha"), worker("beta"))
    assert set(results) == {"alpha", "beta"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_request_context.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.request_context'`

- [ ] **Step 3: Create request context module**

```python
# api/request_context.py
"""Request-scoped context propagation via contextvars."""
from __future__ import annotations

from contextvars import ContextVar, Token

_business_id: ContextVar[str] = ContextVar("business_id", default="default")
_request_id: ContextVar[str] = ContextVar("request_id", default="")


def get_current_business() -> str:
    return _business_id.get()


def set_current_business(business_id: str) -> Token[str]:
    return _business_id.set(business_id)


def get_current_request_id() -> str:
    return _request_id.get()


def set_current_request_id(request_id: str) -> Token[str]:
    return _request_id.set(request_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_request_context.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Wire into RequestLoggingMiddleware**

Modify `api/middleware/request_logging.py` — set context vars at request start:

```python
# Add import at top:
from api.request_context import set_current_request_id

# In dispatch(), after request_id assignment (line 21):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get("x-request-id", str(uuid.uuid4())[:8])
        rid_token = set_current_request_id(request_id)
        start = time.monotonic()
        try:
            # ... existing logic ...
        finally:
            from api.request_context import _request_id
            _request_id.reset(rid_token)
```

- [ ] **Step 6: Run existing tests to verify no regression**

Run: `uv run pytest tests/ -x --timeout=30 -q`
Expected: No failures introduced

- [ ] **Step 7: Commit**

```bash
git add api/request_context.py api/middleware/request_logging.py tests/api/test_request_context.py
git commit -m "feat(sp1): add request-scoped context with contextvars"
```

---

### Task 3: ConversationStore SQLite Persistence

**Files:**
- Create: `store/conversation_store.py`
- Modify: `wiki/ask.py` (replace in-memory ConversationStore)
- Test: `tests/store/test_conversation_store.py`

- [ ] **Step 1: Write failing test for SQLite store**

```python
# tests/store/test_conversation_store.py
import asyncio
import tempfile
import pytest
from store.conversation_store import SqliteConversationStore, ConversationHistory, ConversationTurn


@pytest.fixture
def tmp_db(tmp_path):
    return str(tmp_path / "conv.db")


@pytest.mark.asyncio
async def test_create_and_get(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db)
    await store.initialize()
    history = await store.create("repo-a", scope="module")
    assert history.repository == "repo-a"
    assert history.conversation_id

    fetched = await store.get(history.conversation_id)
    assert fetched is not None
    assert fetched.repository == "repo-a"
    await store.close()


@pytest.mark.asyncio
async def test_save_turns_and_retrieve(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db)
    await store.initialize()
    history = await store.create("repo-b")
    history.turns.append(ConversationTurn(role="user", content="hello"))
    history.turns.append(ConversationTurn(role="assistant", content="hi"))
    await store.save(history)

    fetched = await store.get(history.conversation_id)
    assert fetched is not None
    assert len(fetched.turns) == 2
    assert fetched.turns[0].content == "hello"
    await store.close()


@pytest.mark.asyncio
async def test_ttl_expiration(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db, ttl_seconds=0)
    await store.initialize()
    history = await store.create("repo-c")
    await asyncio.sleep(0.05)
    fetched = await store.get(history.conversation_id)
    assert fetched is None
    await store.close()


@pytest.mark.asyncio
async def test_lru_eviction(tmp_db):
    store = SqliteConversationStore(db_path=tmp_db, max_conversations=2)
    await store.initialize()
    h1 = await store.create("repo-1")
    h2 = await store.create("repo-2")
    h3 = await store.create("repo-3")

    assert await store.get(h1.conversation_id) is None
    assert await store.get(h2.conversation_id) is not None
    assert await store.get(h3.conversation_id) is not None
    await store.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/store/test_conversation_store.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement SqliteConversationStore**

```python
# store/conversation_store.py
"""SQLite-backed conversation store with TTL and LRU eviction."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import aiosqlite


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationHistory:
    conversation_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    repository: str = ""
    scope: str | None = None
    business_id: str = "default"


class SqliteConversationStore:
    def __init__(
        self,
        db_path: str = "data/conversations.db",
        max_conversations: int = 200,
        max_turns: int = 10,
        ttl_seconds: int = 1800,
    ) -> None:
        self._db_path = db_path
        self._max_conversations = max_conversations
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL DEFAULT 'default',
                repository TEXT NOT NULL DEFAULT '',
                scope TEXT,
                turns_json TEXT NOT NULL DEFAULT '[]',
                last_active REAL NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def get(self, conversation_id: str) -> ConversationHistory | None:
        if not self._db:
            return None
        now = time.time()
        cursor = await self._db.execute(
            "SELECT conversation_id, business_id, repository, scope, turns_json, last_active "
            "FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        last_active = row[5]
        if now - last_active > self._ttl_seconds:
            await self._db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            await self._db.commit()
            return None

        await self._db.execute(
            "UPDATE conversations SET last_active = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )
        await self._db.commit()

        turns_raw = json.loads(row[4]) if row[4] else []
        turns = [
            ConversationTurn(role=t["role"], content=t["content"], timestamp=t.get("timestamp", 0))
            for t in turns_raw
        ]

        return ConversationHistory(
            conversation_id=row[0],
            business_id=row[1],
            repository=row[2],
            scope=row[3],
            turns=turns,
            last_active=now,
        )

    async def save(self, history: ConversationHistory) -> None:
        if not self._db:
            return
        history.last_active = time.time()
        if len(history.turns) > self._max_turns:
            history.turns = history.turns[-self._max_turns:]

        turns_json = json.dumps(
            [{"role": t.role, "content": t.content, "timestamp": t.timestamp} for t in history.turns],
            ensure_ascii=False,
        )
        await self._db.execute(
            """INSERT INTO conversations (conversation_id, business_id, repository, scope, turns_json, last_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                turns_json = excluded.turns_json,
                last_active = excluded.last_active""",
            (
                history.conversation_id,
                history.business_id,
                history.repository,
                history.scope,
                turns_json,
                history.last_active,
                history.last_active,
            ),
        )
        await self._db.commit()
        await self._evict_lru()

    async def create(self, repository: str, scope: str | None = None, business_id: str = "default") -> ConversationHistory:
        cid = str(uuid.uuid4())
        h = ConversationHistory(
            conversation_id=cid,
            repository=repository,
            scope=scope,
            business_id=business_id,
        )
        await self.save(h)
        return h

    async def _evict_lru(self) -> None:
        if not self._db:
            return
        cursor = await self._db.execute("SELECT COUNT(*) FROM conversations")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        if count <= self._max_conversations:
            return
        excess = count - self._max_conversations
        await self._db.execute(
            "DELETE FROM conversations WHERE conversation_id IN "
            "(SELECT conversation_id FROM conversations ORDER BY last_active ASC LIMIT ?)",
            (excess,),
        )
        await self._db.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/store/test_conversation_store.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add store/conversation_store.py tests/store/test_conversation_store.py
git commit -m "feat(sp1): add SQLite-backed ConversationStore with TTL and LRU eviction"
```

---

### Task 4: Migrate WikiAskService to Use New ConversationStore

**Files:**
- Modify: `wiki/ask.py`
- Modify: `main.py` (wire SqliteConversationStore)
- Test: `tests/wiki/test_ask_store_compat.py`

- [ ] **Step 1: Write compatibility test**

```python
# tests/wiki/test_ask_store_compat.py
import pytest
from wiki.ask import ConversationStore as LegacyConversationStore


def test_legacy_store_still_works():
    """Ensure the in-memory store still functions as fallback."""
    store = LegacyConversationStore()
    h = store.create("test-repo")
    assert h.conversation_id
    assert store.get(h.conversation_id) is not None
```

- [ ] **Step 2: Run to verify it passes (baseline)**

Run: `uv run pytest tests/wiki/test_ask_store_compat.py -v`
Expected: PASS (existing code works)

- [ ] **Step 3: Update main.py to wire SqliteConversationStore**

In `main.py:wire_wiki_app_state()`, after creating WikiAskService, pass the store:

```python
# In wire_wiki_app_state(), add:
from store.conversation_store import SqliteConversationStore

conv_store_path = str(Path(settings.git.clone_base_path).resolve().parent / "conversations.db")
conv_store = SqliteConversationStore(db_path=conv_store_path)
await conv_store.initialize()
app.state.conversation_store = conv_store

# Pass to WikiAskService:
if kb.llm_provider is not None:
    app.state.wiki_ask_service = WikiAskService(
        search=wiki_search,
        llm=_wrap_llm(kb.llm_provider),
        graph=kb.store,
        memory_loop=wiki_mem,
        # conversation_store parameter already exists in WikiAskService.__init__
    )
```

- [ ] **Step 4: Run full test suite to verify no regression**

Run: `uv run pytest tests/ -x --timeout=60 -q`
Expected: No new failures

- [ ] **Step 5: Commit**

```bash
git add main.py wiki/ask.py
git commit -m "feat(sp1): wire SqliteConversationStore into WikiAskService"
```

---

### Task 5: Migrate Route Handlers to Use Typed Exceptions

**Files:**
- Modify: `api/routes/wiki_routes.py`
- Modify: `api/routes/settings_routes.py`
- Modify: `api/routes/repository_routes.py`

- [ ] **Step 1: Search for HTTPException usage in route modules**

Run: `rg "raise HTTPException" api/routes/ --files-with-matches`

- [ ] **Step 2: Replace HTTPException(404) with KbNotFound in wiki_routes.py**

Find all `raise HTTPException(status_code=404, ...)` and replace with `raise KbNotFound(...)`. Add import at top: `from api.exceptions import KbNotFound, KbClientError, KbServiceUnavailable`.

- [ ] **Step 3: Replace HTTPException(400) with KbClientError**

Find all `raise HTTPException(status_code=400, ...)` and replace with `raise KbClientError(...)`.

- [ ] **Step 4: Repeat for settings_routes.py and repository_routes.py**

Apply same pattern: 404 → KbNotFound, 400 → KbClientError, 503 → KbServiceUnavailable.

- [ ] **Step 5: Run tests to verify no regression**

Run: `uv run pytest tests/ -x --timeout=60 -q`
Expected: No new failures

- [ ] **Step 6: Commit**

```bash
git add api/routes/
git commit -m "refactor(sp1): migrate route handlers to typed domain exceptions"
```

---

### Task 6: Verify No get_settings() in Service Layer (Grep Check)

**Files:**
- Verify: `wiki/service.py`, `wiki/ask.py`, `wiki/memory_loop.py`, `wiki/quality_score.py`

- [ ] **Step 1: Check current usage**

Run: `rg "get_settings\(\)" wiki/ store/ --files-with-matches`

- [ ] **Step 2: For each file found, refactor config access to constructor injection**

For `wiki/service.py`: The `generate()` method calls `get_settings().wiki` multiple times. Extract the needed config values into `WikiService.__init__()` parameters.

- [ ] **Step 3: Update test fixtures to pass config directly**

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -x --timeout=60 -q`
Expected: No new failures

- [ ] **Step 5: Verify grep shows zero hits in service layer**

Run: `rg "get_settings\(\)" wiki/ store/ --count`
Expected: 0 matches (or only in boundary files like `__init__.py`)

- [ ] **Step 6: Commit**

```bash
git add wiki/ store/ tests/
git commit -m "refactor(sp1): remove get_settings() calls from service layer, use constructor DI"
```
