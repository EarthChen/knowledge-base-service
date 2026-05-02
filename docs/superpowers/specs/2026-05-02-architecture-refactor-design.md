# Architecture Refactor — DI Container + Auto-Registration

**Date**: 2026-05-02
**Status**: Draft
**Scope**: 8 remaining architecture improvements from code audit

---

## 1. Goals

Eliminate global mutable singletons, decompose the monolithic lifespan, replace MCP's dict dispatch with auto-registration, deduplicate FQN parsing logic, and clean up frontend code duplication — while keeping all external APIs stable.

## 2. Non-Goals

- Changing HTTP API contracts or MCP tool schemas
- Adding new features
- Changing test frameworks

---

## 3. Architecture: Service Container

### 3.1 `core/container.py` — Application Service Container

A plain Python class holding all service instances. No framework, no magic — just explicit construction and typed access.

```python
@dataclass
class AppContainer:
    """Owns every long-lived service; passed to subsystems that need them."""
    settings: Settings
    registry: ServiceRegistry
    task_manager: IndexTaskManager
    repo_registry: RepoRegistry
    scheduler: SyncScheduler
    settings_store: SettingsStore
    reindex_sem: asyncio.Semaphore
    index_sem: asyncio.Semaphore

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
```

### 3.2 Lifespan Decomposition

Split `main.py:lifespan` into focused initialization functions. All `_init_*` functions receive the container as primary argument:

```
lifespan(app)
  ├── container = AppContainer(settings=settings, ...)
  ├── app.state.container = container
  ├── _init_security(container.settings)       # pure checks, no state
  ├── _init_core_services(container)           # → registry, task_manager, repo_registry, scheduler
  ├── _init_wiki(container, app)               # → delegates to bootstrap_wiki
  ├── _init_lint_scheduler(container)          # → lint scheduler
  └── yield
  └── _shutdown_all(container)                 # reverse-order teardown
```

The lifespan itself becomes ~30 lines.

### 3.3 Removing `api/kb_state.py`

The module-level globals (`registry`, `task_manager`, `repo_registry`, `scheduler`, `reindex_sem`, `index_sem`) move into `AppContainer`. All import sites change from:

```python
import api.kb_state as kb_state
kb_state.registry.get_service(...)
```

to:

```python
from api.dependencies import get_container
container = get_container(request)
container.registry.get_service(...)
```

Where `get_container` reads from `request.app.state.container`.

**Background tasks**: Background tasks (scheduler, indexing) don't have request context. During transition, `kb_state.py` holds a module-level reference to the container:

```python
# api/kb_state.py (transition shim)
_container: AppContainer | None = None

@property  # accessed as kb_state.registry etc.
def registry():
    return _container.registry if _container else None
```

Both `request.app.state.container` and `kb_state._container` point to the same instance. The shim is removed once all background task call sites are migrated to receive the container explicitly.

---

## 4. MCP Tool Auto-Registration

### 4.1 Decorator-Based Registration

Replace the `handlers = { ... }` dict in `handle_tool_call` with a class-level decorator. Since tools are instance methods across two classes (`MCPKnowledgeServer` and `MCPWikiServer`), use an instance-level registry built at `__init__` time:

```python
# api/mcp_registry.py
from auth import Role

def mcp_tool(name: str, *, min_role: Role = Role.VIEWER):
    """Mark a method as an MCP tool handler."""
    def decorator(fn):
        fn._mcp_tool_name = name
        fn._mcp_tool_min_role = min_role
        return fn
    return decorator

def collect_tools(instance: object) -> dict[str, tuple[Callable, Role]]:
    """Scan instance for @mcp_tool-decorated methods, return {name: (bound_method, role)}."""
    tools = {}
    for attr_name in dir(instance):
        method = getattr(instance, attr_name, None)
        if callable(method) and hasattr(method, "_mcp_tool_name"):
            tools[method._mcp_tool_name] = (method, method._mcp_tool_min_role)
    return tools
```

`MCPKnowledgeServer.__init__` merges tools from `self` and `self._wiki`:

```python
def __init__(self, ...):
    ...
    self._tools = collect_tools(self)
    self._tools.update(collect_tools(self._wiki))
```

`handle_tool_call` becomes:

```python
async def handle_tool_call(self, tool_name, arguments, *, token_info=None):
    entry = self._tools.get(tool_name)
    if not entry:
        return _mcp_error("unknown_tool", f"Unknown tool: {tool_name}")
    handler, min_role = entry
    # auth check using min_role ...
    return await handler(arguments)
```

### 4.2 `MCP_TOOL_MIN_ROLE` Consolidation

The separate `MCP_TOOL_MIN_ROLE` dict is eliminated — role info lives on the decorator metadata. This removes the maintenance burden of keeping two dicts in sync.

---

## 5. FQN Parsing Deduplication

### 5.1 `store/fqn_utils.py`

Extract the shared FQN regex and parsing logic:

```python
# store/fqn_utils.py
import re

FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)

def is_fqn(text: str) -> bool:
    return bool(FQN_RE.fullmatch(text.strip()))

def parse_fqn(raw: str) -> tuple[str, str | None]:
    """Return (fqn_or_name, simple_name_or_None)."""
    text = raw.strip()
    if not FQN_RE.fullmatch(text):
        return text, None
    if "#" in text:
        return text, text.rsplit("#", 1)[1]
    return text, text.rsplit(".", 1)[-1]

def extract_fqns(text: str) -> list[str]:
    return [m.split("(")[0].strip() for m in FQN_RE.findall(text)]
```

Both `store/traversal_store.py` and `query/hybrid_query.py` import from `store/fqn_utils.py` instead of maintaining their own `_FQN_RE`.

---

## 6. Frontend: Wiki Path Encoding Unification

### 6.1 `dashboard/src/utils/wikiPath.ts`

```typescript
export function encodeWikiPath(path: string): string {
  return path
    .split("/")
    .filter(Boolean)
    .map((seg) => encodeURIComponent(seg))
    .join("/");
}
```

Both `useWikiPage.ts` and `useWikiPageByPath.ts` import from this shared utility. The local `encodeWikiPath` in `useWikiPage.ts` and `encodeWikiPathSegments` in `useWikiPageByPath.ts` are removed.

---

## 7. Frontend: Pages Tests

Add basic smoke tests for the 3 most complex pages. These are shallow render tests ensuring the component mounts without crashing and renders key UI elements.

Target pages:
- `OverviewPage`
- `GraphExplorerPage`
- `WikiPage`

Test pattern: Mock API responses via manual query client mocking (follow existing test patterns in the project), render the page component, assert key elements are present.

**Note**: `GraphExplorerPage` depends on `@xyflow/react` which requires DOM layout APIs. Mock the xyflow components at the module level to avoid JSDOM limitations.

---

## 8. Frontend: Mobile Sidebar Accessibility

Add `role="dialog"`, `aria-modal="true"`, and ESC key handling to the mobile sidebar overlay in `Layout.tsx`, consistent with how `CommandPalette.tsx` handles its modal behavior.

---

## 9. WikiService Type Annotations

Narrow the `__init__` parameter types from `Any` to concrete types or Protocol definitions. This improves IDE support and catches integration errors at type-check time.

Approach: Use `Protocol` for cross-module dependencies (e.g., `GraphStore` protocol instead of importing `FalkorDBStore` directly), and concrete types for intra-module deps. This avoids import cycles between `wiki/` and `store/`.

---

## 10. Implementation Order

```
Phase 1 — Foundation (no behavior change):
  1. Create store/fqn_utils.py, update import sites
  2. Create api/mcp_registry.py with decorator
  3. Create core/container.py with AppContainer

Phase 2 — Backend refactor:
  4. Decompose lifespan into _init_* functions
  5. Migrate kb_state.py consumers to AppContainer
  6. Apply @mcp_tool decorators, remove dict dispatch
  7. Narrow WikiService type annotations

Phase 3 — Frontend:
  8. Create dashboard/src/utils/wikiPath.ts
  9. Add page smoke tests
  10. Mobile sidebar accessibility
```

Each phase is independently testable. Phase 1 is pure additive (no breakage risk). Phase 2 is the core refactor. Phase 3 is independent of backend changes.

---

## 11. Testing Strategy

- **Phase 1**: Existing tests must continue passing (no behavior change)
- **Phase 2**: `test_wiki_app_state.py` and all integration tests updated to use container; `api/kb_state.py` backward-compat shim ensures gradual migration
- **Phase 3**: New frontend tests added; existing 298 tests must pass

---

## 12. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Breaking existing imports of `kb_state` | Keep `kb_state.py` as a thin re-export shim initially |
| MCP tool registration order | Decorators execute at import time; import order is already deterministic |
| Container lifecycle in tests | Provide `create_test_container()` factory with mocked deps |
| Large diff | Each phase is a separate commit/PR |
| Testing with container | Provide `AppContainer.create_test(...)` factory that accepts keyword overrides for mocked deps |
