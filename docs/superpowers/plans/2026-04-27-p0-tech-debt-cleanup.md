# P0 — Tech Debt Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve three technical debts: wire token multiplier, unify MCP naming, remove dead code.

**Architecture:** Minimal targeted fixes. Token multiplier threads through `WikiService.generate()` → `_budget_for_tier()`. MCP rename adds backward-compat alias. Dead code deletion verified by grep + test.

**Tech Stack:** Python 3.12, FastAPI, pytest, pnpm (dashboard), vitest

---

### Task 1: Wire Token Budget Multiplier

**Files:**
- Modify: `wiki/service.py` (generate, generate_stream_events, generate_incremental, _budget_for_tier, _compose_all_pages)
- Modify: `wiki/bootstrap.py` (_run_feedback_wiki_regen)
- Modify: `config.py` (docstring fix)
- Modify: `wiki/feedback_loop.py` (docstring fix)
- Test: `tests/wiki/test_token_multiplier.py` (create)

- [ ] **Step 1: Write failing test for `_budget_for_tier` with multiplier**

```python
# tests/wiki/test_token_multiplier.py
import pytest
from unittest.mock import MagicMock
from wiki.service import WikiService


def _make_service(core=20000, standard=8000, skeleton=1000):
    """Build a WikiService with minimal stubs for budget testing."""
    wiki_cfg = MagicMock()
    wiki_cfg.core_code_budget = core
    wiki_cfg.standard_code_budget = standard
    wiki_cfg.skeleton_code_budget = skeleton
    svc = WikiService.__new__(WikiService)
    svc._wiki_cfg = wiki_cfg
    return svc


def test_budget_for_tier_default_multiplier():
    from wiki.models import ImportanceTier
    svc = _make_service()
    assert svc._budget_for_tier(ImportanceTier.CORE) == 20000
    assert svc._budget_for_tier(ImportanceTier.STANDARD) == 8000
    assert svc._budget_for_tier(ImportanceTier.SKELETON) == 1000


def test_budget_for_tier_with_multiplier():
    from wiki.models import ImportanceTier
    svc = _make_service()
    assert svc._budget_for_tier(ImportanceTier.CORE, multiplier=1.5) == 30000
    assert svc._budget_for_tier(ImportanceTier.STANDARD, multiplier=2.0) == 16000
    assert svc._budget_for_tier(ImportanceTier.SKELETON, multiplier=0.5) == 500
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_token_multiplier.py -v --no-cov`
Expected: FAIL — `_budget_for_tier` does not accept `multiplier` parameter

- [ ] **Step 3: Add `multiplier` param to `_budget_for_tier`**

In `wiki/service.py`, modify:

```python
def _budget_for_tier(self, tier: ImportanceTier | None, *, multiplier: float = 1.0) -> int:
    """Return the token budget for a given importance tier from app config."""
    app_cfg = self._wiki_cfg
    if tier == ImportanceTier.CORE:
        base = app_cfg.core_code_budget
    elif tier == ImportanceTier.STANDARD:
        base = app_cfg.standard_code_budget
    elif tier == ImportanceTier.SKELETON:
        base = app_cfg.skeleton_code_budget
    else:
        base = app_cfg.standard_code_budget
    return int(base * multiplier)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_token_multiplier.py -v --no-cov`
Expected: PASS

- [ ] **Step 5: Add `token_budget_multiplier` param to `generate()` and thread to `_compose_all_pages`**

In `wiki/service.py`:

1. Add `token_budget_multiplier: float = 1.0` to `generate()`, `generate_stream_events()`, `generate_incremental()` signatures
2. Pass `token_budget_multiplier` through to `_compose_all_pages` call
3. In `_compose_all_pages`, accept `token_budget_multiplier: float = 1.0` and pass to `_budget_for_tier(..., multiplier=token_budget_multiplier)`

- [ ] **Step 6: Wire `token_multiplier` in `bootstrap.py`**

In `wiki/bootstrap.py`, modify `_run_feedback_wiki_regen` to pass `token_budget_multiplier=token_multiplier` to `service.generate(...)`:

```python
await service.generate(
    repository,
    scope,
    "structure",
    "json",
    language="en",
    token_budget_multiplier=token_multiplier,
)
```

Remove the TODO comment.

- [ ] **Step 7: Clean up docstrings**

- `config.py`: Remove "logged but not yet applied" from `feedback_regen_token_multiplier` and `feedback_regen_batch_token_multiplier` docstrings
- `wiki/feedback_loop.py`: Remove module-level docstring note about multipliers not being applied

- [ ] **Step 8: Run full test suite**

Run: `uv run pytest -q --no-cov`
Expected: All tests pass (1762+)

- [ ] **Step 9: Commit**

```bash
git add wiki/service.py wiki/bootstrap.py config.py wiki/feedback_loop.py tests/wiki/test_token_multiplier.py
git commit -m "feat(wiki): wire token_budget_multiplier through generate pipeline (P0 Task 1)"
```

---

### Task 2: MCP Surface Naming Unification

**Files:**
- Modify: `wiki/mcp_tools.py` (rename search_wiki → wiki_search, add alias)
- Modify: `api/mcp_server.py` (update dispatch, add alias)
- Modify: `docs/MCP-INTEGRATION.md` (add positioning section)
- Test: `tests/wiki/mcp/test_mcp_tools_manifest.py` (verify name)

- [ ] **Step 1: Write test for new tool name**

```python
# tests/wiki/mcp/test_mcp_rename.py
from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST


def test_wiki_search_tool_name():
    names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
    assert "wiki_search" in names, f"Expected 'wiki_search' in {names}"
    # backward compat: search_wiki should still resolve
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/mcp/test_mcp_rename.py -v --no-cov`
Expected: FAIL — manifest has `search_wiki` not `wiki_search`

- [ ] **Step 3: Rename in manifest**

In `wiki/mcp_tools.py`, change `"name": "search_wiki"` to `"name": "wiki_search"` in `WIKI_MCP_TOOLS_MANIFEST`.

Update handler method name: `handle_search_wiki` → `handle_wiki_search` (keep `handle_search_wiki` as alias).

- [ ] **Step 4: Update `api/mcp_server.py` dispatch**

In `KnowledgeBaseMCPHandler`, update the dispatch dict to map both `wiki_search` and `search_wiki` (alias) to the same handler.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/mcp/ -v --no-cov`
Expected: All pass

- [ ] **Step 6: Update `docs/MCP-INTEGRATION.md`**

Add a "两套 MCP 表面定位" section explaining:
- Main MCP (20 tools): stdio/full-context Agent
- Wiki HTTP MCP (6 tools): lightweight HTTP Agent
- `search_wiki` is now `wiki_search` (old name accepted as alias)

- [ ] **Step 7: Run full test suite**

Run: `uv run pytest -q --no-cov`
Expected: All tests pass

- [ ] **Step 8: Commit**

```bash
git add wiki/mcp_tools.py api/mcp_server.py docs/MCP-INTEGRATION.md tests/wiki/mcp/test_mcp_rename.py
git commit -m "refactor(mcp): rename search_wiki → wiki_search with backward-compat alias (P0 Task 2)"
```

---

### Task 3: Dead Code Cleanup

**Files:**
- Delete: `dashboard/src/components/wiki/WikiSidebar.tsx`
- Possibly delete: other unused exports found by grep

- [ ] **Step 1: Verify WikiSidebar.tsx is unreferenced**

Run: `cd dashboard && rg "WikiSidebar" src/ --type ts --type tsx`
Expected: Only the file's own definition, no imports from other files.

- [ ] **Step 2: Delete WikiSidebar.tsx**

```bash
rm dashboard/src/components/wiki/WikiSidebar.tsx
```

- [ ] **Step 3: Scan for other unused wiki component exports**

Run: `rg "from.*wiki/(WikiSidebar|WikiGlobalSearchBar)" dashboard/src/ --type-add 'tsx:*.tsx' --type tsx`

Check if any other components in `components/wiki/` are imported nowhere. Only delete if clearly dead (not lazy-loaded or dynamically imported).

- [ ] **Step 4: Run frontend tests**

Run: `cd dashboard && pnpm test --run`
Expected: All tests pass, no broken imports

- [ ] **Step 5: Run backend tests (sanity)**

Run: `uv run pytest -q --no-cov`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: remove dead WikiSidebar.tsx and unused exports (P0 Task 3)"
```
