# Phase 1 — Engineering Hardening (Implementation Plan)

> **Spec**: [`docs/superpowers/specs/2026-04-26-llm-wiki-v2-upgrade-design.md`](../specs/2026-04-26-llm-wiki-v2-upgrade-design.md) (§2)  
> **Date**: 2026-04-26  
> **Tooling**: Python via **`uv`** (never `pip`); dashboard via **`pnpm`** (never `npm`).

---

## 1. Header

### Goal

Harden the LLM Wiki stack before Phase 2: split oversized backend/frontend modules, centralize wiki bootstrap, unify MCP error shapes with the HTTP `error_handler` contract, and add **measured** test coverage (backend + dashboard).

### Architecture (Target)

- **Backend**: `api/routes/wiki_routes.py` becomes a **thin router aggregator**; domain endpoints live in five sibling modules. Shared Pydantic bodies live in `api/models/wiki_models.py`. In-process wiki generation tasks live in `wiki/task_registry.py`. Cross-cutting route helpers and `Depends` factories live in **`api/routes/wiki_shared.py`** (required so the five modules stay small; not one of the “domain” five, but not optional).
- **Bootstrap**: `main.py` lifespan calls `wiki/bootstrap.py` for wiki-specific `app.state` wiring; teardown closes resources owned by bootstrap (today: primarily mirrors current `wire_wiki_app_state` + conversation store close patterns).
- **MCP**: `MCPWikiServer.handle_tool_call` maps **all** exceptions through the same public-safe mapping as HTTP (`_public_error_for_exception`).

### Tech Stack

- **Backend**: FastAPI, Pydantic v2, pytest + pytest-asyncio, **pytest-cov** (to add).  
- **Dashboard**: React 19, Vite, Vitest, **@vitest/coverage-v8** (to add), Testing Library.  
- **Monorepo paths**: service root = `knowledge-base-service/`.

### Conventions for This Plan

- Every **TDD** subsection follows: **failing test → run & confirm red → implement → run & green → `git add -p` + commit** (one logical commit per subsection unless noted).
- **All paths** below are **repo-root–relative** from `knowledge-base-service/`.

---

## 2. File structure mapping

### 2.1 Backend — from monolith to modules

| Current | Becomes / Notes |
|--------|-----------------|
| `api/routes/wiki_routes.py` (1640+ lines) | `api/routes/wiki_routes.py` (~30–50 lines): `wiki_router` + `include_router` of children; re-export public symbols used by tests (`WikiTaskRegistry`, `get_wiki_service_dep`, …) from the new modules to avoid a flag day of test diffs, then optionally narrow imports in a follow-up. |
| — | `api/routes/wiki_shared.py`: `get_*_dep`, `_maybe_call`, `_indexed_repository_names`, `_wiki_page_from_export_dict`, `_search_response_to_json`, `_page_type_to_scope`, `_wiki_structure_from_pages`, `_invalid_scope_detail`, `wiki_router` dependency helpers, `_GLOBAL_*` search constants, etc. |
| — | `api/routes/wiki_page_routes.py`: page/tree/search/structure/business/quality/impact/… (see §2.3) |
| — | `api/routes/wiki_task_routes.py`: async generation + quick + task status + long-poll /events |
| — | `api/routes/wiki_ask_routes.py`: `/ask`, `/research`, `GET .../pages/{uid}/questions` |
| — | `api/routes/wiki_feedback_routes.py`: feedback, ingest, changelog, QA record, chunk index, lint, repo export preview/execute (see §2.3) |
| — | `api/routes/wiki_mcp_routes.py`: `mcp_wiki_http_router` and MCP HTTP handlers only |
| `api/routes/wiki_routes.py` (Pydantic bodies) | `api/models/wiki_models.py` + `api/models/__init__.py` |
| `wiki_routes.WikiTaskRegistry` | `wiki/task_registry.py` |
| `main.wire_wiki_app_state` | `wiki/bootstrap.py` (`bootstrap_wiki`, `teardown_wiki`); `main` imports and calls in `lifespan` |
| `api/mcp_wiki_server.py` | `handle_tool_call` uses structured errors (§SP1 T3) |

**Setuptools / packaging note**: `pyproject.toml` uses explicit `[tool.setuptools] packages = [...]`. After adding `api/models/`, run `uv run python -c "import api.models.wiki_models"`. If import fails in CI, add `api.models` to the packages list or switch to `find`/`find_namespace_packages` for `api` (only if required).

### 2.2 Route ownership (authoritative for split)

**`api/routes/wiki_page_routes.py`**

- `POST /search`, `POST /search/global`
- `GET /pages/by-path`, `GET /flows`, `GET /tree`
- `POST /business/generate`, `POST /export`
- `GET /pages/{page_uid:path}/references`
- `GET /coverage-report`, `GET /quality-score`, `GET /references`, `GET /qa`
- `GET /merge-candidates`
- `POST /{repository}/analyze-impact`, `GET /{repository}/enrichment-status`, `POST /{repository}/enrich`
- `GET /{repository}/pages`, `GET /{repository}/pages/{wiki_page_path:path}`

**`api/routes/wiki_task_routes.py`**

- `POST /generate`, `POST /quick`, `GET /tasks/{task_id}`, `GET /events`
- module-private: `_run_wiki_task`, `_run_wiki_quick_task` (import `WikiTaskRegistry` from `wiki.task_registry`)

**`api/routes/wiki_ask_routes.py`**

- `POST /ask`, `POST /research`
- `GET /pages/{page_uid:path}/questions`

**`api/routes/wiki_feedback_routes.py`**

- `POST /pages/{page_uid:path}/feedback`, `GET /pages/{page_uid:path}/feedback/summary`
- `POST /chunks/index`, `POST /ingest`, `GET /changelog`
- `POST /{repository}/lint`
- `POST /qa/record`
- `POST /{repository}/export/preview`, `POST /{repository}/export/execute`

**`api/routes/wiki_mcp_routes.py`**

- `mcp_wiki_http_router` — `POST /tools/call`, `GET /tools/list` (unchanged URL surface)

### 2.3 Dashboard — from large components to modules

| Current | New / moved |
|--------|-------------|
| `dashboard/src/components/wiki/WikiShell.tsx` | Stays; imports `WikiToolTabStrip`, `WikiToolPanel` (new). |
| — | `dashboard/src/components/wiki/WikiToolTabStrip.tsx` — tab list UI + `setToolTab` integration (props-driven). |
| — | `dashboard/src/components/wiki/WikiToolPanel.tsx` — one component mapping `toolTab` → lazy panel; wraps each area in `Suspense` + (optional) inner `ErrorBoundary` if you want per-panel isolation (outer `ErrorBoundary` in `WikiShell` can remain). |
| `dashboard/src/components/wiki/WikiContent.tsx` | Stays as composer (~250 lines). |
| — | `dashboard/src/components/wiki/WikiVersionPicker.tsx` — move **exported** `WikiVersionPicker` (lines 57–121 in current file) verbatim into this file; re-export from `WikiContent.tsx` for backward compatibility **or** update imports (prefer single export site). |
| `dashboard/src/components/wiki/SourceLocRow.tsx` | Superseded by `WikiSourceLocRow.tsx` (wrap/rename: default export `WikiSourceLocRow` = current `SourceLocRow` content + any section chrome moved from `WikiContent` for “source locations” block). |
| `dashboard/src/components/wiki/CallChainSection.tsx` | Rename to `dashboard/src/components/wiki/WikiCallChainSection.tsx` (default export), update all imports. |

**Tests to relocate/add**: any test importing `WikiVersionPicker` from `WikiContent` should import from `WikiVersionPicker.tsx` after extraction.

### 2.4 Coverage config files

- `knowledge-base-service/pyproject.toml` — add `[tool.coverage.*]` and pytest `--cov` / `--cov-fail-under=60` in `[tool.pytest.ini_options] addopts`
- `knowledge-base-service/dashboard/vitest.config.ts` — `test.coverage` with `provider: "v8"`, `thresholds.lines: 50`
- `knowledge-base-service/dashboard/package.json` — script e.g. `"test:coverage": "vitest run --coverage"` (optional but recommended)

---

## 3. SP1 — Backend module split (3 tasks)

### SP1 — Task 1: Split `wiki_routes.py` (5 sub-modules + `api/models/wiki_models.py` + `wiki/task_registry.py`)

#### Step 1.1 — `wiki/task_registry.py` (TDD)

**Failing test** — new file `tests/wiki/test_task_registry.py`:

```python
from __future__ import annotations

import time

import pytest

from wiki.task_registry import WIKI_TASK_TTL_SEC, WikiTaskRegistry


def test_wiki_task_registry_put_get_roundtrip() -> None:
    reg = WikiTaskRegistry()
    reg.put_task("t1", {"status": "pending"})
    rec = reg.get_task("t1")
    assert rec is not None
    assert rec["status"] == "pending"


def test_wiki_task_registry_prunes_expired_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    # Deterministic "time"
    t0 = 1000.0
    monkeypatch.setattr(time, "monotonic", lambda: t0)

    reg = WikiTaskRegistry()
    reg.put_task("exp", {"x": 1})
    reg.put_task("keep", {"x": 2})
    # Force first task to be old
    reg._created["exp"] = t0 - WIKI_TASK_TTL_SEC - 1  # type: ignore[attr-defined]

    monkeypatch.setattr(time, "monotonic", lambda: t0 + 1.0)
    reg.get_task("keep")  # triggers prune
    assert reg.get_task("exp") is None
    assert reg.get_task("keep") is not None
```

**Run (expect fail)**: `cd knowledge-base-service && uv run pytest tests/wiki/test_task_registry.py -q`

**Implement** — new file `wiki/task_registry.py` (move logic verbatim from `api/routes/wiki_routes.py` lines 55–82):

```python
from __future__ import annotations

import time
from typing import Any

WIKI_TASK_TTL_SEC = 30 * 60


class WikiTaskRegistry:
    """In-memory wiki generation tasks. Entries expire after WIKI_TASK_TTL_SEC for bounded memory use."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self._created: dict[str, float] = {}

    def _prune(self) -> None:
        now = time.monotonic()
        removed = [tid for tid, ts in self._created.items() if now - ts > WIKI_TASK_TTL_SEC]
        for tid in removed:
            self.tasks.pop(tid, None)
            self._created.pop(tid, None)

    def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        self._prune()
        self.tasks[task_id] = record
        self._created[task_id] = time.monotonic()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        self._prune()
        return self.tasks.get(task_id)
```

**Migrate tests**: In `tests/api/test_wiki_task_registry.py` change:

```python
from api.routes.wiki_routes import WIKI_TASK_TTL_SEC, WikiTaskRegistry
```

to

```python
from wiki.task_registry import WIKI_TASK_TTL_SEC, WikiTaskRegistry
```

**Pass**: `uv run pytest tests/wiki/test_task_registry.py tests/api/test_wiki_task_registry.py -q`  
**Commit**: `refactor(wiki): extract WikiTaskRegistry to wiki/task_registry`

#### Step 1.2 — `api/models/wiki_models.py` (TDD + compile check)

**Failing “test”** (fast import contract): new `tests/api/test_wiki_models_import.py`:

```python
from __future__ import annotations

import importlib


def test_wiki_models_module_imports() -> None:
    m = importlib.import_module("api.models.wiki_models")
    assert hasattr(m, "WikiGenerateBody")
    assert hasattr(m, "IngestRequest")
```

**Implement**

- `api/models/__init__.py` (can be empty or re-export)
- `api/models/wiki_models.py` — move **all** `class X(BaseModel):` and related-only constants from `wiki_routes.py` (lines 85–197) unchanged, with imports:

```python
from __future__ import annotations

from pydantic import BaseModel, Field
```

- Update `api/routes/wiki_routes.py` (intermediate state) to `from api.models.wiki_models import *`  # narrow to explicit imports in final polish

**Pass**: `uv run pytest tests/api/test_wiki_models_import.py -q`  
**Commit**: `refactor(api): add api.models.wiki_models for wiki route bodies`

#### Step 1.3 — `api/routes/wiki_shared.py`

Extract **all** dependency getters and private helpers (from line ~216 through `_run_wiki_quick_task`, excluding route handlers). Export names must match what tests patch (e.g. `tests/wiki/test_r_phase2_perf.py` uses `GraphQueryRepository` via `api.routes.wiki_routes` — keep compatibility by re-exporting from `wiki_routes.py` or patch `api.routes.wiki_shared` in a follow-up; minimum bar: re-export in `wiki_routes.py` so `patch("api.routes.wiki_routes.GraphQueryRepository")` still works for helpers that import `GraphQueryRepository` in `wiki_shared`).

**Failing test** (smoke): `tests/api/test_wiki_shared_dep.py`

```python
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, Request

from api.routes.wiki_shared import get_task_registry_dep
from wiki.task_registry import WikiTaskRegistry


def test_get_task_registry_dep_uses_state_or_creates() -> None:
    app = FastAPI()
    req = Request({"type": "http", "path": "/x", "headers": []}, app=app)  # minimal
    # Starlette request needs scope — use a simpler pattern: mock request
    req = MagicMock()
    req.app = app
    reg1 = get_task_registry_dep(req)  # type: ignore[arg-type]
    reg2 = get_task_registry_dep(req)
    assert isinstance(reg1, WikiTaskRegistry)
    assert reg1 is reg2
    assert app.state.wiki_tasks is reg1
```

(Adjust to your project’s `Request` construction if this minimal mock fails; alternative: `TestClient` with dependency override is unnecessary here — the goal is `wiki_tasks` singleton behavior.)

**Pass + commit** when `get_task_registry_dep` and friends live in `wiki_shared.py` and `wiki_routes` still exposes them.

#### Step 1.4–1.8 — Move route handlers in **five files**

For **each** of `wiki_page_routes`, `wiki_task_routes`, `wiki_ask_routes`, `wiki_feedback_routes`, `wiki_mcp_routes`:

1. Create module with `router = APIRouter()` (dependencies inherited from `wiki_routes` aggregator — if role deps were on the parent, keep the same by attaching routes to the **included** router; the parent `wiki_router` in `api/routes/wiki_routes.py` already has `dependencies=[Depends(require_role(Role.VIEWER))]`, so child routers per FastAPI can be included **without** re-stating the global dependency if they are `include_router(sub, ...)` under the same parent — **verify** in OpenAPI; if not, set `dependencies=` on the sub-router or per-route.
2. Move handlers **wholesale**; fix imports to pull models from `api.models.wiki_models`, `WikiTaskRegistry` from `wiki.task_registry`, helpers from `api.routes.wiki_shared`.
3. **After each file** moved: `uv run pytest` (full or targeted `tests/wiki/ tests/api/`).

**Aggregator** — `api/routes/wiki_routes.py` final form:

```python
from __future__ import annotations

from fastapi import APIRouter

from auth import Role, require_role
from fastapi import Depends
from api.routes.wiki_ask_routes import router as wiki_ask_router
from api.routes.wiki_feedback_routes import router as wiki_feedback_router
from api.routes.wiki_mcp_routes import router as wiki_mcp_router
from api.routes.wiki_page_routes import router as wiki_page_router
from api.routes.wiki_task_routes import router as wiki_task_router
from api.routes import wiki_shared  # re-export

wiki_router = APIRouter(
    prefix="/api/v1/wiki",
    tags=["wiki"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
wiki_router.include_router(wiki_page_router)
wiki_router.include_router(wiki_task_router)
wiki_router.include_router(wiki_ask_router)
wiki_router.include_router(wiki_feedback_router)

mcp_wiki_http_router = APIRouter(
    prefix="/api/v1/mcp",
    tags=["mcp", "wiki"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)
mcp_wiki_http_router.include_router(wiki_mcp_router)
```

(If `mcp` routes are defined on the same `router` object in `wiki_mcp_routes.py` as the child routes, you may instead `mcp_wiki_http_router = wiki_mcp_wiki_subrouter` — match one style project-wide.)

**Re-exports** for test compatibility (bottom of `wiki_routes.py`):

```python
from wiki.task_registry import WIKI_TASK_TTL_SEC, WikiTaskRegistry
from api.models.wiki_models import (
    IngestRequest,
    WikiGenerateBody,
    # ... all symbols tests import
)
from api.routes.wiki_shared import (
    get_task_registry_dep,
    get_wiki_ask_dep,
    get_wiki_cache_dep,
    get_wiki_service_dep,
    get_wiki_store_dep,
    # ... as needed
)
```

**Pass**: `uv run pytest`  
**Commit**: `refactor(api): split wiki_routes into page/task/ask/feedback/mcp modules`

---

### SP1 — Task 2: Extract `wire_wiki_app_state` → `wiki/bootstrap.py`

#### TDD

**Failing test** — replace imports in `tests/test_wiki_app_state.py` to call the new entry points while keeping function names. Initial failing step: add `from wiki.bootstrap import bootstrap_wiki, teardown_wiki` and a test that `bootstrap_wiki` **exists** and `wire_wiki_app_state` re-exports it (or delete `wire_wiki_app_state` and update all imports).

**Preferred contract** (from spec) — new `wiki/bootstrap.py`:

```python
from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi import FastAPI

from config import get_settings
from service_registry import ServiceRegistry

if TYPE_CHECKING:
    from config import Settings


async def bootstrap_wiki(app: FastAPI, registry: ServiceRegistry) -> None:
    """Initialize all wiki services and attach to app.state (HTTP wiki + MCP)."""
    # Move the body of main.wire_wiki_app_state here verbatim, including
    # conversation_store, wiki_store, feedback store, service factory, search, ask, deep_research, graph_query, mcp, etc.
    _ = get_settings  # if unused after move, wire settings explicitly
    raise NotImplementedError  # only in the first red commit


async def teardown_wiki(app: FastAPI) -> None:
    """Release wiki resources owned by bootstrap_wiki (MCP is stateless; focus on app.state)."""
    # No-op is acceptable if main already closes conversation_store in lifespan; OR move conv_store close here from main
    return None
```

**Test** (update existing):

```python
import pytest
from fastapi import FastAPI
from unittest.mock import AsyncMock, MagicMock

from wiki.bootstrap import bootstrap_wiki
from wiki.service import WikiService


@pytest.mark.asyncio
async def test_bootstrap_wiki_sets_factory_and_services() -> None:
    app = FastAPI()
    mock_store = MagicMock()
    mock_semantic = MagicMock()
    mock_llm = MagicMock()
    mock_graph_query = MagicMock()

    kb = MagicMock()
    kb.store = mock_store
    kb.semantic_query = mock_semantic
    kb._embedding = MagicMock()
    kb.llm_provider = mock_llm
    kb.graph_query = mock_graph_query

    registry = MagicMock()
    registry.get_service = AsyncMock(return_value=kb)

    await bootstrap_wiki(app, registry)
    # ... same assertions as current test_wire_wiki_app_state_sets_factory_and_services
```

**`main.py` lifespan** (relevant hunk — **full code** as target):

```python
from wiki.bootstrap import bootstrap_wiki, teardown_wiki
from service_registry import ServiceRegistry
# ... inside lifespan, after app.state assignments that must occur before wiki:
    await bootstrap_wiki(app, kb_state.registry)
    log.info("kb_service_started")
    yield
    log.info("kb_service_stopping")
    await teardown_wiki(app)
    conv_store = getattr(app.state, "conversation_store", None)
    if conv_store is not None:
        await conv_store.close()
    # OR: only teardown_wiki closes conv_store; pick one place to avoid double-close
```

**Rule**: do **not** double-close `SqliteConversationStore` — if `teardown_wiki` closes it, remove the close from `main.lifespan` (or the inverse).

**Pass**: `uv run pytest tests/test_wiki_app_state.py -q`  
**Commit**: `refactor(wiki): add bootstrap_wiki and teardown_wiki; thin main wire_wiki_app_state`

---

### SP1 — Task 3: Unify MCP error contract

**Goal**: `MCPWikiServer.handle_tool_call` returns a **JSON-serializable** object whose error shape aligns with public HTTP errors: `{ "error": { "code", "message", "http_status" } }` (or nest under `error` to mirror `ErrorResponse` — keep **one** shape and document in code comment).

**Failing test** — new `tests/api/test_mcp_wiki_errors.py`:

```python
from __future__ import annotations

import pytest
from api.exceptions import KbNotFound
from api.mcp_wiki_server import MCPWikiServer


@pytest.mark.asyncio
async def test_mcp_handle_tool_call_maps_kb_error_with_public_code() -> None:
    class ErrAsk:
        async def ask_stream(self, **kwargs):
            raise KbNotFound("nope")
            if False:  # pragma: no cover
                yield {}

    mcp = MCPWikiServer(ask_service=ErrAsk(), search_service=None, wiki_store=None, change_detector=None)
    out = await mcp.handle_tool_call("wiki_qa", {"question": "q", "repository": "r", "business_id": "b"})
    assert "error" in out
    err = out["error"]
    assert err["code"] == "kb_not_found"
    assert err["message"] == "nope"
    assert err["http_status"] == 404
```

(Adjust field names to match the implementation, but the test should lock the behavior.)

**Implementation** — append to **`api/error_handler.py`** (same module as `_public_error_for_exception`; no self-import). At file top, ensure `from typing import Any` exists (already used elsewhere in that module).

```python
def public_error_dict(exc: BaseException) -> dict[str, Any]:
    status, code, message = _public_error_for_exception(exc)
    return {"code": code, "message": message, "http_status": status}
```

**`api/mcp_wiki_server.py` — `handle_tool_call`** (full method body target):

```python
from api.error_handler import public_error_dict
from api.exceptions import KbError  # if still used

async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    handler = getattr(self, f"_handle_{tool_name}", None)
    if handler is None:
        from api.error_handler import _public_error_for_exception
        status, code, message = _public_error_for_exception(ValueError("unknown tool"))
        return {"error": {"code": code, "message": f"Unknown tool: {tool_name}", "http_status": status}}
    try:
        return await handler(arguments)
    except Exception as exc:  # noqa: BLE001 — uniform mapping
        return {"error": public_error_dict(exc)}
```

**Refinement**: `unknown tool` path should not leak internal mapping inconsistency; prefer dedicated code `mcp_unknown_tool` with 400. Lock with a second test.

**Pass**: `uv run pytest tests/api/test_mcp_wiki_errors.py tests/api/test_exceptions.py -q`  
**Commit**: `fix(mcp): align MCP tool errors with public error handler mapping`

---

## 4. SP2 — Frontend split + coverage (3 tasks)

### SP2 — Task 1: Split `WikiShell.tsx`

#### Step F1.1 — `WikiToolTabStrip.tsx` (TDD with RTL)

**Failing test** `dashboard/src/components/wiki/WikiToolTabStrip.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { I18nProvider } from "../../i18n/context";
import WikiToolTabStrip from "./WikiToolTabStrip";

describe("WikiToolTabStrip", () => {
  it("selects a tab and calls onChange", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <I18nProvider>
        <WikiToolTabStrip toolTab="page" onToolTabChange={onChange} />
      </I18nProvider>
    );
    const btn = await screen.findByRole("tab", { name: /page/i });
    await user.click(btn);
    expect(onChange).toHaveBeenCalledWith("page");
  });
});
```

(Adjust to match your i18n provider name from `src/i18n/context`.)

**Implementation** `dashboard/src/components/wiki/WikiToolTabStrip.tsx` — move the `tabBtn` callback, `tabBtn(...)` list, the `div role="tablist"`, and props: `toolTab`, `onToolTabChange`, `t` labels are internal via `useI18n` inside the component.

**Run**: `cd knowledge-base-service/dashboard && pnpm exec vitest run src/components/wiki/WikiToolTabStrip.test.tsx`  
**Commit**

#### Step F1.2 — `WikiToolPanel.tsx`

**Props sketch** (real code in implementation):

```tsx
import { lazy, Suspense, type ReactNode } from "react";
import type { QueryClient, UseQueryResult } from "@tanstack/react-query";
import type { WikiPageDetail } from "../../hooks/wikiTypes";
// ... all lazy panel imports

export type WikiToolTab = "page" | "coverage" | "export" | "health" | "insights" | "refgraph" | "research" | "flows";

type Props = {
  toolTab: WikiToolTab;
  businessId: string;
  viewType: "business_domain" | "code_structure" | (string & {});
  pagePath: string;
  pageQuery: UseQueryResult<WikiPageDetail | null>;
  // ... callbacks and wikiLinkParams as needed
};

export default function WikiToolPanel(props: Props) { /* switch(toolTab) with Suspense */ }
```

**Failing test**: render `WikiToolPanel` with `toolTab="coverage"` and assert `WikiCoverageCard`’s business id is passed (msw or shallow mock via vi.mock of child).

**`WikiShell.tsx`** then wires URL state (`setToolTab`, `searchParams`, `useWikiPageByPath`, etc.) and renders `<WikiToolTabStrip />` + `<WikiToolPanel ... />` + `WikiReferencesPanel` as today.

**Pass**: `pnpm test`  
**Commit**: `refactor(dashboard): extract Wiki tool strip and tool panel from WikiShell`

---

### SP2 — Task 2: Split `WikiContent.tsx`

#### F2.1 — `WikiVersionPicker.tsx`

Move lines 57–121 from `WikiContent.tsx` into `dashboard/src/components/wiki/WikiVersionPicker.tsx` (copy **verbatim** including imports: `useEffect`, `useRef`, `useState`, `FocusTrap`, `WikiVersionBadge`, `WikiVersionHistory`, `WikiDiffViewer`, `useI18n`).

**Failing test** `WikiVersionPicker.test.tsx` — render with minimal props, assert the badge opens the popover on click (or snapshot `versionHistoryTitle`).

**`WikiContent.tsx`**: `import { WikiVersionPicker } from "./WikiVersionPicker";` and delete inline component.

**Commit**

#### F2.2 — `WikiSourceLocRow.tsx`

- Create `dashboard/src/components/wiki/WikiSourceLocRow.tsx` that **contains** the section header + `<ul>` previously in `WikiContent` (import `FolderOpen` from `lucide-react`, `useI18n` for `t.wiki.sourceLocations`), and uses either **moved** `SourceLocRow` (rename file to `WikiSourceLocRow` default export) or re-export: simplest plan is to **rename** `SourceLocRow.tsx` → `WikiSourceLocRow.tsx` and change default export name to `WikiSourceLocRow`, then in `WikiContent` render `<WikiSourceLocRow ... />` for the block.

**Test**: unit test for `WikiSourceLocRow` rendering one row with `file_path` / `start_line` from a fixture `WikiSourceLocation`.

#### F2.3 — `WikiCallChainSection.tsx`

- `git mv dashboard/src/components/wiki/CallChainSection.tsx dashboard/src/components/wiki/WikiCallChainSection.tsx`
- Change `export default function` name to `WikiCallChainSection`
- Grep: update imports across `dashboard/src`

**Failing test** (optional if time): `WikiCallChainSection` renders CTA with `t.wiki.callChainTitle` when `source_locations` non-empty (mirror existing behavior).

**Commit**: `refactor(dashboard): split WikiContent into VersionPicker, SourceLoc, CallChain`

---

### SP2 — Task 3: Test coverage (pytest-cov + @vitest/coverage-v8)

#### Backend

**Commands (run by implementer):**

```bash
cd knowledge-base-service
uv add --dev pytest-cov
```

**`pyproject.toml` additions (exact snippets):**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=6.0",
    "ruff>=0.8.0",
]
```

**`[tool.pytest.ini_options]` extend:**

```toml
addopts = "--cov=. --cov-report=term-missing --cov-fail-under=60"
```

(If `addopts` already exists, **merge** instead of duplicating the key. If full-package `--cov=.` is too slow, narrow to `["wiki", "api", "store", "main.py"]` but then update `fail-under` with team agreement — this plan uses the **spec** verbatim.)

**Failing / passing gate**: `uv run pytest` must print coverage; first run on main may **fail** `fail-under` — treat as a baseline step: either (a) temporarily set `--cov-fail-under=0` to land infra, then raise in a second commit, or (b) add minimal tests until 60% — **the plan requires the threshold to match the spec**; choose (a) only if the team approves a follow-up ticket.

**Commit**: `chore: add pytest-cov with term-missing and fail-under 60`

#### Frontend

**Commands:**

```bash
cd knowledge-base-service/dashboard
pnpm add -D @vitest/coverage-v8
```

**`dashboard/vitest.config.ts` full file target** (merge with existing `plugins` / `include` — preserve your project’s settings):

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
      thresholds: {
        lines: 50,
      },
    },
  },
});
```

**`package.json` script:**

```json
"test:coverage": "vitest run --coverage"
```

**Failing / passing**: `pnpm test:coverage` — first run may fail if line coverage &lt; 50% — use same policy as backend.

**Commit**: `chore(dashboard): add vitest v8 coverage thresholds`

---

## 5. Final verification (Phase 1 exit criteria)

1. `uv run ruff check .` and `uv run pytest` (with coverage) pass at repo `knowledge-base-service/`.
2. `pnpm -C knowledge-base-service/dashboard lint` and `pnpm -C knowledge-base-service/dashboard test:coverage` pass.
3. Grep: no remaining `from main import wire_wiki_app_state` in tests (unless kept as a one-line re-export in `main.py` for BC).
4. OpenAPI: spot-check `GET /api/v1/wiki/tree` and `POST /api/v1/mcp/tools/call` paths unchanged.
5. **Status**: report **STATUS: DONE** to the requester when this plan is committed.

---

## 6. Git — commit the plan (this file)

```bash
cd knowledge-base-service
git add docs/superpowers/plans/2026-04-26-phase1-engineering-hardening.md
git commit -m "docs: add Phase 1 engineering hardening implementation plan"
```

---

*End of plan.*
