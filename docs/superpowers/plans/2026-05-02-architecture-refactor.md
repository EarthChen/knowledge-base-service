# Architecture Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate global mutable singletons, decompose the monolithic lifespan, auto-register MCP tools, and clean up code duplication across frontend and backend.

**Architecture:** Introduce an `AppContainer` dataclass as the single service holder, decompose `lifespan` into focused `_init_*` functions, replace MCP's dict dispatch with `@mcp_tool` decorators, and unify duplicated utilities.

**Tech Stack:** Python 3.12, FastAPI, FalkorDB, React 18, TypeScript, Vitest, pytest

**Spec:** `docs/superpowers/specs/2026-05-02-architecture-refactor-design.md`

---

## Phase 1 — Foundation (Pure Additive, No Behavior Change)

### Task 1: Create `store/fqn_utils.py`

**Files:**
- Create: `store/fqn_utils.py`
- Modify: `store/traversal_store.py`
- Modify: `query/hybrid_query.py`
- Create: `tests/test_fqn_utils.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_fqn_utils.py`:

```python
"""Tests for store.fqn_utils — shared FQN regex and helpers."""
from __future__ import annotations

import pytest

from store.fqn_utils import FQN_RE, extract_fqns, is_fqn, parse_fqn


class TestIsFqn:
    def test_valid_three_segment(self):
        assert is_fqn("com.example.MyClass") is True

    def test_valid_with_method(self):
        assert is_fqn("com.example.MyClass#doStuff") is True

    def test_valid_with_method_params(self):
        assert is_fqn("com.example.MyClass#doStuff(int, str)") is True

    def test_two_segments_rejected(self):
        assert is_fqn("example.MyClass") is False

    def test_simple_name_rejected(self):
        assert is_fqn("MyClass") is False

    def test_empty_rejected(self):
        assert is_fqn("") is False


class TestParseFqn:
    def test_simple_name_returns_none_fqn(self):
        fqn, simple = parse_fqn("MyClass")
        assert fqn == "MyClass"
        assert simple is None

    def test_fqn_returns_last_segment(self):
        fqn, simple = parse_fqn("com.example.MyClass")
        assert fqn == "com.example.MyClass"
        assert simple == "MyClass"

    def test_fqn_with_method_hash(self):
        fqn, simple = parse_fqn("com.example.MyClass#doStuff")
        assert fqn == "com.example.MyClass#doStuff"
        assert simple == "doStuff"


class TestExtractFqns:
    def test_extracts_from_text(self):
        text = "Call com.example.MyClass#run and org.foo.Bar.baz"
        result = extract_fqns(text)
        assert "com.example.MyClass#run" in result
        assert "org.foo.Bar.baz" in result

    def test_strips_params(self):
        text = "com.example.Foo#bar(int)"
        result = extract_fqns(text)
        assert result == ["com.example.Foo#bar"]

    def test_empty_text(self):
        assert extract_fqns("") == []
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fqn_utils.py -x -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'store.fqn_utils'`

- [x] **Step 3: Write minimal implementation**

Create `store/fqn_utils.py`:

```python
"""Shared FQN (Fully Qualified Name) regex and parsing utilities.

Consolidates duplicate _FQN_RE definitions from traversal_store.py and hybrid_query.py.
"""
from __future__ import annotations

import re

FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)


def is_fqn(text: str) -> bool:
    """Return True if *text* is a valid fully-qualified name."""
    return bool(FQN_RE.fullmatch(text.strip()))


def parse_fqn(raw: str) -> tuple[str, str | None]:
    """Parse user input which may be a simple name or FQN.

    Returns (cleaned_input, simple_name_or_None).
    """
    text = raw.strip()
    if not FQN_RE.fullmatch(text):
        return text, None
    if "#" in text:
        return text, text.rsplit("#", 1)[1].split("(")[0]
    return text, text.rsplit(".", 1)[-1]


def extract_fqns(text: str) -> list[str]:
    """Extract all FQN occurrences from free text, stripping method params."""
    return [m.split("(")[0].strip() for m in FQN_RE.findall(text)]
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_fqn_utils.py -x -v`
Expected: PASS (all 9 tests)

- [x] **Step 5: Update `store/traversal_store.py` to import from fqn_utils**

In `store/traversal_store.py`, replace the local `_FQN_RE` definition and `_parse_input` with imports:

```python
# Remove:
# _FQN_RE = re.compile(...)
# def _parse_input(raw: str) -> tuple[str, str | None]:
#     if _FQN_RE.fullmatch(raw.strip()): ...

# Add:
from store.fqn_utils import FQN_RE as _FQN_RE, parse_fqn as _parse_input
```

Keep the `import re` if still used elsewhere in the file; remove if not.

- [x] **Step 6: Update `query/hybrid_query.py` to import from fqn_utils**

In `query/hybrid_query.py`, replace the local `_FQN_RE` definition:

```python
# Remove:
# _FQN_RE = re.compile(...)

# Add:
from store.fqn_utils import FQN_RE as _FQN_RE
```

- [x] **Step 7: Run full backend tests**

Run: `uv run pytest tests/ -x --timeout=30 -q`
Expected: All tests pass (no behavior change)

- [x] **Step 8: Commit**

```bash
git add store/fqn_utils.py tests/test_fqn_utils.py store/traversal_store.py query/hybrid_query.py
git commit -m "refactor: extract shared FQN parsing to store/fqn_utils.py"
```

---

### Task 2: Create `api/mcp_registry.py`

**Files:**
- Create: `api/mcp_registry.py`
- Create: `tests/api/test_mcp_registry.py`

- [x] **Step 1: Write the failing test**

Create `tests/api/test_mcp_registry.py`:

```python
"""Tests for api.mcp_registry — MCP tool decorator and collector."""
from __future__ import annotations

from auth import Role
from api.mcp_registry import collect_tools, mcp_tool


class _FakeServer:
    @mcp_tool("tool_a", min_role=Role.VIEWER)
    async def handle_a(self, args):
        return {"ok": True}

    @mcp_tool("tool_b", min_role=Role.EDITOR)
    async def handle_b(self, args):
        return {"ok": True}

    async def not_a_tool(self, args):
        return {}


def test_collect_tools_finds_decorated_methods():
    server = _FakeServer()
    tools = collect_tools(server)
    assert "tool_a" in tools
    assert "tool_b" in tools
    assert "not_a_tool" not in tools


def test_collect_tools_preserves_role():
    server = _FakeServer()
    tools = collect_tools(server)
    _, role_a = tools["tool_a"]
    _, role_b = tools["tool_b"]
    assert role_a == Role.VIEWER
    assert role_b == Role.EDITOR


def test_collected_handler_is_bound():
    server = _FakeServer()
    tools = collect_tools(server)
    handler, _ = tools["tool_a"]
    assert handler.__self__ is server
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_mcp_registry.py -x -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'api.mcp_registry'`

- [x] **Step 3: Write minimal implementation**

Create `api/mcp_registry.py`:

```python
"""MCP tool auto-registration via decorators.

Usage:
    @mcp_tool("tool_name", min_role=Role.VIEWER)
    async def handle_tool(self, args: dict) -> dict: ...

    tools = collect_tools(server_instance)
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from auth import Role


def mcp_tool(name: str, *, min_role: Role = Role.VIEWER) -> Callable:
    """Mark an async method as an MCP tool handler."""
    def decorator(fn: Callable) -> Callable:
        fn._mcp_tool_name = name  # type: ignore[attr-defined]
        fn._mcp_tool_min_role = min_role  # type: ignore[attr-defined]
        return fn
    return decorator


def collect_tools(instance: object) -> dict[str, tuple[Callable[..., Any], Role]]:
    """Scan *instance* for @mcp_tool-decorated methods. Returns {name: (bound_method, role)}."""
    tools: dict[str, tuple[Callable[..., Any], Role]] = {}
    for attr_name in dir(instance):
        if attr_name.startswith("__"):
            continue
        method = getattr(instance, attr_name, None)
        if callable(method) and hasattr(method, "_mcp_tool_name"):
            tools[method._mcp_tool_name] = (method, method._mcp_tool_min_role)
    return tools
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_mcp_registry.py -x -v`
Expected: PASS (all 3 tests)

- [x] **Step 5: Commit**

```bash
git add api/mcp_registry.py tests/api/test_mcp_registry.py
git commit -m "feat: add MCP tool auto-registration decorator"
```

---

### Task 3: Create `core/container.py`

**Files:**
- Create: `core/__init__.py`
- Create: `core/container.py`
- Create: `tests/test_container.py`

- [x] **Step 1: Write the failing test**

Create `tests/test_container.py`:

```python
"""Tests for core.container — AppContainer dataclass."""
from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from core.container import AppContainer


def test_container_creation_with_required_fields():
    container = AppContainer(
        settings=MagicMock(),
        registry=MagicMock(),
        task_manager=MagicMock(),
        repo_registry=MagicMock(),
        scheduler=MagicMock(),
        settings_store=MagicMock(),
        reindex_sem=asyncio.Semaphore(1),
        index_sem=asyncio.Semaphore(2),
    )
    assert container.registry is not None
    assert container.wiki_store is None
    assert container.wiki_service_factory is None


def test_container_wiki_fields_default_to_none():
    container = AppContainer(
        settings=MagicMock(),
        registry=MagicMock(),
        task_manager=MagicMock(),
        repo_registry=MagicMock(),
        scheduler=MagicMock(),
        settings_store=MagicMock(),
        reindex_sem=asyncio.Semaphore(1),
        index_sem=asyncio.Semaphore(2),
    )
    wiki_fields = [
        "wiki_store", "wiki_service_factory", "wiki_search_service",
        "wiki_ask_service", "wiki_event_bus", "wiki_task_store",
    ]
    for field in wiki_fields:
        assert getattr(container, field) is None, f"{field} should default to None"
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_container.py -x -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'core'`

- [x] **Step 3: Write minimal implementation**

Create `core/__init__.py`:
```python
```

Create `core/container.py`:

```python
"""Application service container — replaces module-level globals in api/kb_state.py."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from config import Settings
from indexer.task_manager import IndexTaskManager
from services.repo_registry import RepoRegistry
from services.scheduler import SyncScheduler
from services.service_registry import ServiceRegistry
from store.settings_store import SettingsStore


@dataclass
class AppContainer:
    """Holds every long-lived service instance for the application."""

    # Core (required)
    settings: Settings
    registry: ServiceRegistry
    task_manager: IndexTaskManager
    repo_registry: RepoRegistry
    scheduler: SyncScheduler
    settings_store: SettingsStore
    reindex_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(1))
    index_sem: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(2))

    # Wiki subsystem (populated by bootstrap_wiki)
    wiki_store: Any = None
    wiki_service_factory: Any = None
    wiki_search_service: Any = None
    wiki_ask_service: Any = None
    wiki_event_bus: Any = None
    wiki_task_store: Any = None
    wiki_feedback_store: Any = None
    wiki_feedback_regen: Any = None
    wiki_cache: Any = None
    wiki_lint_service_factory: Any = None
    wiki_lint_scheduler: Any = None
    graph_query_service: Any = None
    conversation_store: Any = None
    change_detector: Any = None
    wiki_changelog_store: Any = None
    wiki_memory_loop: Any = None
    wiki_deep_research_service: Any = None
    mcp_wiki_server: Any = None

    @classmethod
    def create_test(cls, **overrides: Any) -> AppContainer:
        """Factory for tests — all fields mocked unless overridden."""
        from unittest.mock import MagicMock

        defaults = {
            "settings": MagicMock(spec=Settings),
            "registry": MagicMock(spec=ServiceRegistry),
            "task_manager": MagicMock(spec=IndexTaskManager),
            "repo_registry": MagicMock(spec=RepoRegistry),
            "scheduler": MagicMock(spec=SyncScheduler),
            "settings_store": MagicMock(spec=SettingsStore),
            "reindex_sem": asyncio.Semaphore(1),
            "index_sem": asyncio.Semaphore(2),
        }
        defaults.update(overrides)
        return cls(**defaults)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_container.py -x -v`
Expected: PASS (all 2 tests)

- [x] **Step 5: Commit**

```bash
git add core/__init__.py core/container.py tests/test_container.py
git commit -m "feat: add AppContainer service container"
```

---

## Phase 2 — Backend Refactor

### Task 4: Decompose `main.py` lifespan

**Files:**
- Modify: `main.py`
- Modify: `api/kb_state.py` (add container shim)
- Create: `tests/test_lifespan_decomposition.py`

- [x] **Step 1: Write the test**

Create `tests/test_lifespan_decomposition.py`:

```python
"""Verify that the decomposed lifespan produces the same container state."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI

from core.container import AppContainer


@pytest.mark.asyncio
async def test_lifespan_creates_container():
    """After lifespan startup, app.state.container is an AppContainer."""
    from main import lifespan

    app = FastAPI()
    mock_registry = MagicMock()
    mock_registry.start = AsyncMock()
    mock_registry.stop = AsyncMock()
    mock_registry.get_service = AsyncMock(return_value=MagicMock(
        store=MagicMock(_redis=None, redis=None, _graph=None, _db=None),
        semantic_query=MagicMock(),
        _embedding=MagicMock(),
        llm_provider=None,
        graph_query=MagicMock(),
        wiki_deferred_enrichment=None,
        wiki_flow_inferencer=None,
    ))

    with patch("main.ServiceRegistry", return_value=mock_registry), \
         patch("main.SyncScheduler") as mock_sched_cls, \
         patch("main.get_settings") as mock_settings:
        mock_sched = MagicMock()
        mock_sched.start = AsyncMock()
        mock_sched.stop = AsyncMock()
        mock_sched_cls.return_value = mock_sched
        settings = mock_settings.return_value
        settings.host = "127.0.0.1"
        settings.port = 8100
        settings.log_level = "INFO"
        settings.require_auth = False
        settings.api_token = ""
        settings.api_tokens = ""
        settings.tokens_file = "/dev/null"
        settings.git.clone_base_path = "/tmp/kb-test-clones"
        settings.cors_origins = ""
        settings.wiki.community_context_enabled = False
        settings.wiki.mcp_server_enabled = False
        settings.wiki.lint_scheduler_enabled = False
        settings.wiki.memory_tiers_enabled = False
        settings.embedding = MagicMock()

        async with lifespan(app):
            assert hasattr(app.state, "container")
            assert isinstance(app.state.container, AppContainer)
            assert app.state.container.registry is mock_registry
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_lifespan_decomposition.py -x -v`
Expected: FAIL (app.state.container doesn't exist yet)

- [x] **Step 3: Refactor `main.py` lifespan**

Extract the lifespan body into focused functions and create the container:

1. Add `from core.container import AppContainer` import
2. Create `_init_core_services(container: AppContainer) -> None` — moves lines 119-148 (task_manager, repo_registry, registry, scheduler creation)
3. Create `_init_wiki_and_lint(container: AppContainer, app: FastAPI) -> None` — moves lines 154-230 (wiki cache, lint factory, bootstrap_wiki, lint scheduler)
4. Create `_shutdown_all(container: AppContainer, app: FastAPI) -> None` — moves lines 236-254
5. The lifespan itself creates the container, calls the init functions, and stores it on `app.state.container`
6. Also mirror key fields to `app.state.*` for backward compat (e.g., `app.state.registry = container.registry`)

- [x] **Step 4: Update `api/kb_state.py` to be a transition shim**

Add a `_container` reference that main.py sets after creating the container:

```python
"""Transition shim — re-exports from AppContainer for backward compatibility."""
from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.container import AppContainer

MAX_CONCURRENT_REINDEX = 1
reindex_sem = asyncio.Semaphore(MAX_CONCURRENT_REINDEX)
MAX_CONCURRENT_INDEX = 2
index_sem = asyncio.Semaphore(MAX_CONCURRENT_INDEX)

_container: AppContainer | None = None

@property
def registry():
    return _container.registry if _container else None

# ... similar for task_manager, repo_registry, scheduler
```

Actually, since this is a module (not a class), use `__getattr__` for dynamic attribute access:

```python
_container: AppContainer | None = None

def _bind(container: AppContainer) -> None:
    global _container
    _container = container

def __getattr__(name: str):
    if _container is not None and hasattr(_container, name):
        return getattr(_container, name)
    raise AttributeError(f"module 'api.kb_state' has no attribute '{name}'")
```

Keep the semaphore module-level vars for now (they're used directly).

- [x] **Step 5: Run tests**

Run: `uv run pytest tests/test_lifespan_decomposition.py tests/test_wiki_app_state.py -x -v`
Expected: PASS

- [x] **Step 6: Run full backend tests**

Run: `uv run pytest tests/ -x --timeout=30 -q`
Expected: All pass

- [x] **Step 7: Commit**

```bash
git add main.py api/kb_state.py core/container.py tests/test_lifespan_decomposition.py
git commit -m "refactor: decompose lifespan, introduce AppContainer"
```

---

### Task 5: Apply `@mcp_tool` decorators to MCP server

**Files:**
- Modify: `api/mcp_server.py`
- Modify: `api/mcp_wiki_server.py` (if wiki tools are there)
- Modify: `tests/api/test_mcp_registry.py` (extend)

- [x] **Step 1: Add `@mcp_tool` decorators to each handler method in `api/mcp_server.py`**

For each handler in the current `handlers` dict, add the decorator:

```python
from api.mcp_registry import mcp_tool, collect_tools

@mcp_tool("rag_query")
async def handle_rag_query(self, args: dict[str, Any]) -> dict[str, Any]:
    ...

@mcp_tool("wiki_export", min_role=Role.EDITOR)
async def handle_wiki_export(self, args: dict[str, Any]) -> dict[str, Any]:
    ...
```

Do the same for wiki tools in `MCPWikiServer` (or wherever they're defined).

- [x] **Step 2: Build tool registry in `__init__`**

In `MCPKnowledgeServer.__init__`, after `self._wiki` is created:

```python
self._tools = collect_tools(self)
self._tools.update(collect_tools(self._wiki))
```

- [x] **Step 3: Replace `handle_tool_call` dispatch**

Replace the `handlers = { ... }` dict and `MCP_TOOL_MIN_ROLE` lookups with:

```python
async def handle_tool_call(self, tool_name, arguments, *, token_info=None):
    entry = self._tools.get(tool_name)
    if not entry:
        return _mcp_error("unknown_tool", f"Unknown tool: {tool_name}")
    handler, min_role = entry

    if token_info is not None:
        if token_info.role < min_role:
            return _mcp_error("forbidden", f"This tool requires at least the {min_role.name.lower()} role.")
    elif get_settings().require_auth and min_role > Role.VIEWER:
        return _mcp_error("forbidden", f"Authentication required for tool '{tool_name}'.")

    try:
        return await handler(arguments)
    except Exception as exc:
        log.error("mcp_tool_error", tool=tool_name, error=str(exc))
        return _mcp_error("internal_error", "Tool execution failed unexpectedly")
```

- [x] **Step 4: Remove `MCP_TOOL_MIN_ROLE` dict and `TOOL_ROLES` alias**

Delete the `MCP_TOOL_MIN_ROLE` dict definition and `TOOL_ROLES` alias. Check if anything imports them; if so, provide a backward-compat function that reads from `_tools`.

- [x] **Step 5: Run MCP-related tests**

Run: `uv run pytest tests/api/ -x -v --timeout=30`
Expected: All pass

- [x] **Step 6: Run full tests**

Run: `uv run pytest tests/ -x --timeout=30 -q`
Expected: All pass

- [x] **Step 7: Commit**

```bash
git add api/mcp_server.py api/mcp_registry.py api/mcp_wiki_server.py
git commit -m "refactor: replace MCP dict dispatch with @mcp_tool decorators"
```

---

### Task 6: Narrow WikiService type annotations

**Files:**
- Modify: `wiki/service.py`
- Create: `wiki/protocols.py` (optional, if needed for cross-module types)

- [x] **Step 1: Read `wiki/service.py` `__init__` signature**

Identify all `Any`-typed parameters and determine correct types from usage.

- [x] **Step 2: Create `wiki/protocols.py` if needed**

If any parameter's concrete type would create circular imports, define a Protocol:

```python
from __future__ import annotations
from typing import Any, Protocol

class GraphStore(Protocol):
    async def execute_query(self, cypher: str, params: dict[str, Any]) -> Any: ...
    async def add_node(self, label: str, properties: dict[str, Any]) -> Any: ...
```

- [x] **Step 3: Update `WikiService.__init__` type annotations**

Replace `Any` with concrete types or Protocols. Keep backward compatibility (no runtime behavior change).

- [x] **Step 4: Run type checker (if available) and tests**

Run: `uv run pytest tests/wiki/ -x --timeout=30 -q`
Expected: All pass

- [x] **Step 5: Commit**

```bash
git add wiki/service.py wiki/protocols.py
git commit -m "refactor: narrow WikiService type annotations"
```

---

## Phase 3 — Frontend

### Task 7: Create shared `wikiPath.ts` utility

**Files:**
- Create: `dashboard/src/utils/wikiPath.ts`
- Modify: `dashboard/src/hooks/useWikiPage.ts`
- Modify: `dashboard/src/hooks/useWikiPageByPath.ts`
- Create: `dashboard/src/utils/__tests__/wikiPath.test.ts`

- [x] **Step 1: Write the failing test**

Create `dashboard/src/utils/__tests__/wikiPath.test.ts`:

```typescript
import { describe, it, expect } from "vitest";
import { encodeWikiPath } from "../wikiPath";

describe("encodeWikiPath", () => {
  it("encodes path segments", () => {
    expect(encodeWikiPath("foo/bar/baz")).toBe("foo/bar/baz");
  });

  it("encodes special characters", () => {
    expect(encodeWikiPath("src/my file.ts")).toBe("src/my%20file.ts");
  });

  it("strips leading and trailing slashes", () => {
    expect(encodeWikiPath("/foo/bar/")).toBe("foo/bar");
  });

  it("handles empty string", () => {
    expect(encodeWikiPath("")).toBe("");
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd dashboard && pnpm test --run src/utils/__tests__/wikiPath.test.ts`
Expected: FAIL (module not found)

- [x] **Step 3: Write implementation**

Create `dashboard/src/utils/wikiPath.ts`:

```typescript
export function encodeWikiPath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd dashboard && pnpm test --run src/utils/__tests__/wikiPath.test.ts`
Expected: PASS

- [x] **Step 5: Update `useWikiPage.ts`**

Remove the local `encodeWikiPath` function. Add import:

```typescript
import { encodeWikiPath } from "../utils/wikiPath";
```

- [x] **Step 6: Update `useWikiPageByPath.ts`**

Remove the local `encodeWikiPathSegments` function. Add import and rename usage:

```typescript
import { encodeWikiPath } from "../utils/wikiPath";
// Replace encodeWikiPathSegments(path) → encodeWikiPath(path)
```

Update the export if `encodeWikiPathSegments` was exported and used elsewhere.

- [x] **Step 7: Run all frontend tests**

Run: `cd dashboard && pnpm test --run`
Expected: All 298+ tests pass

- [x] **Step 8: Commit**

```bash
git add dashboard/src/utils/wikiPath.ts dashboard/src/utils/__tests__/wikiPath.test.ts \
  dashboard/src/hooks/useWikiPage.ts dashboard/src/hooks/useWikiPageByPath.ts
git commit -m "refactor: unify wiki path encoding utility"
```

---

### Task 8: Add page smoke tests

**Files:**
- Create: `dashboard/src/pages/__tests__/OverviewPage.test.tsx`
- Create: `dashboard/src/pages/__tests__/WikiPage.test.tsx`

- [x] **Step 1: Write smoke test for OverviewPage**

Create `dashboard/src/pages/__tests__/OverviewPage.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { Suspense } from "react";

vi.mock("../../api/hooks", () => ({
  useHealth: () => ({ data: { status: "ok" } }),
  useRepositories: () => ({ data: [], isLoading: false }),
}));

vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "test",
    businesses: [{ id: "test", name: "Test" }],
    isBound: true,
    setCurrentBusiness: vi.fn(),
  }),
}));

vi.mock("../../i18n/context", () => ({
  useI18n: () => ({ t: new Proxy({}, { get: () => new Proxy({}, { get: (_, k) => String(k) }) }) }),
}));

describe("OverviewPage", () => {
  it("mounts without crashing", async () => {
    const { default: OverviewPage } = await import("../Overview");
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <MemoryRouter>
          <Suspense fallback={<div>Loading</div>}>
            <OverviewPage />
          </Suspense>
        </MemoryRouter>
      </QueryClientProvider>,
    );
    // Should render without throwing
    expect(document.body).toBeTruthy();
  });
});
```

- [x] **Step 2: Write smoke test for WikiPage**

Create `dashboard/src/pages/__tests__/WikiPage.test.tsx` following the same pattern, mocking wiki-specific hooks.

- [x] **Step 3: Run tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass (298+ plus new ones)

- [x] **Step 4: Commit**

```bash
git add dashboard/src/pages/__tests__/
git commit -m "test: add page smoke tests for Overview and Wiki"
```

---

### Task 9: Mobile sidebar accessibility

**Files:**
- Modify: `dashboard/src/components/Layout.tsx`
- Create: `dashboard/src/components/__tests__/Layout.sidebar.test.tsx`

- [x] **Step 1: Write the failing test**

Create `dashboard/src/components/__tests__/Layout.sidebar.test.tsx`:

```typescript
import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

vi.mock("../../api/hooks", () => ({
  useHealth: () => ({ data: { status: "ok" } }),
}));
vi.mock("../../contexts/BusinessContext", () => ({
  useBusiness: () => ({
    currentBusiness: "test",
    businesses: [{ id: "test", name: "Test" }],
    isBound: true,
    setCurrentBusiness: vi.fn(),
  }),
}));
vi.mock("../../i18n/context", () => ({
  useI18n: () => ({ t: new Proxy({}, { get: () => new Proxy({}, { get: (_, k) => String(k) }) }) }),
}));

import Layout from "../Layout";

function renderLayout() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <Layout />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("Mobile sidebar accessibility", () => {
  it("overlay has role=dialog and aria-modal", () => {
    renderLayout();
    const menuBtn = screen.getByRole("button", { name: /menu/i });
    fireEvent.click(menuBtn);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
  });

  it("closes on Escape key", async () => {
    renderLayout();
    const menuBtn = screen.getByRole("button", { name: /menu/i });
    fireEvent.click(menuBtn);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd dashboard && pnpm test --run src/components/__tests__/Layout.sidebar.test.tsx`
Expected: FAIL (no role="dialog" found)

- [x] **Step 3: Update `Layout.tsx`**

In the mobile overlay `<div>`, add accessibility attributes and ESC handler:

```tsx
{sidebarOpen && (
  <div
    role="dialog"
    aria-modal="true"
    aria-label="Navigation"
    className="fixed inset-0 z-30 bg-black/30 dark:bg-black/50 lg:hidden"
    onClick={() => setSidebarOpen(false)}
    onKeyDown={(e) => {
      if (e.key === "Escape") setSidebarOpen(false);
    }}
    tabIndex={-1}
    ref={(el) => el?.focus()}
  />
)}
```

Also add `aria-label="Toggle menu"` to the hamburger button if not already present.

- [x] **Step 4: Run test to verify it passes**

Run: `cd dashboard && pnpm test --run src/components/__tests__/Layout.sidebar.test.tsx`
Expected: PASS

- [x] **Step 5: Run all frontend tests**

Run: `cd dashboard && pnpm test --run`
Expected: All pass

- [x] **Step 6: Commit**

```bash
git add dashboard/src/components/Layout.tsx dashboard/src/components/__tests__/Layout.sidebar.test.tsx
git commit -m "fix: add accessibility attrs to mobile sidebar overlay"
```

---

## Final Verification

- [x] **Run full backend test suite**

```bash
uv run pytest tests/ -x --timeout=30 -q
```
Expected: All pass

- [x] **Run full frontend test suite**

```bash
cd dashboard && pnpm test --run
```
Expected: All pass

- [x] **Verify no lint errors in changed files**

Check linter output for all modified files.

- [x] **Update analysis document**

Remove the 8 fixed items from `docs/superpowers/DEEP_ANALYSIS_20260502_101930_code_audit_and_competitor_gap.md` section 2 (剩余改进方向).
