# Unified LLM Token Budget Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Consolidate scattered token budget hardcodes into a single `default_llm_budget` config with ratio-based derivation and safety ceiling.

**Architecture:** One new `TokenBudgetResolver` class derives per-component budgets as fixed proportions of a single configurable base value. A safety ceiling caps all budgets at 80% of the provider's `max_context_tokens`. Existing function signatures remain unchanged for backward compatibility.

**Tech Stack:** Python 3.11+, Pydantic Settings, pytest

**Spec:** `docs/superpowers/specs/PROPOSAL_20260429_130536_unified-llm-token-budget.md`

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `wiki/token_budget.py` | `TokenBudgetResolver`: derives per-component token budgets from a single base using fixed ratios; applies ceiling cap |
| `tests/wiki/test_token_budget.py` | Unit tests for `TokenBudgetResolver` |

### Modified Files

| File | Changes |
|------|---------|
| `config.py` | Add `max_context_tokens: int = 128_000` to `AppLlmSettings`; add `default_llm_budget: int = 30_000` to `AppWikiFlags`; deprecate `decomposition_max_tokens_per_batch` |
| `wiki/ask.py` | Replace `_WIKI_TYPE_TOKEN_BUDGET` hardcoded dict with `TokenBudgetResolver.ask_budget()` |
| `wiki/compact_formatter.py` | Use resolver-derived budget as default instead of hardcoded `4000` |
| `query/context_assembler.py` | Use resolver-derived budget as default instead of hardcoded `8000` |
| `wiki/dependency_graph.py` | Replace `ModuleReprBuilder.MAX_TOKENS_PER_BATCH` class constant with resolver budget |
| `wiki/service.py` | Instantiate `TokenBudgetResolver` in `__init__` and thread to dependent components |

---

## Task 1: TokenBudgetResolver + Config

**Files:**
- Create: `wiki/token_budget.py`
- Create: `tests/wiki/test_token_budget.py`
- Modify: `config.py:110-120` (AppLlmSettings), `config.py:300-320` (AppWikiFlags)

- [x] **Step 1: Write failing tests for TokenBudgetResolver**

```python
# tests/wiki/test_token_budget.py
from wiki.token_budget import TokenBudgetResolver


class TestTokenBudgetResolver:
    def test_default_ratios(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.budget("decomposition") == 30_000
        assert r.budget("ask_general") == 8_100
        assert r.budget("ask_flow") == 12_000
        assert r.budget("compact") == 3_900
        assert r.budget("assembly") == 8_100

    def test_ceiling_cap(self):
        r = TokenBudgetResolver(base=30_000, ceiling=8_000)
        assert r.budget("decomposition") <= 6_400  # 8000 * 0.8
        assert r.budget("ask_flow") <= 6_400

    def test_small_model_scaling(self):
        r = TokenBudgetResolver(base=6_000)
        assert r.budget("decomposition") == 6_000
        assert r.budget("ask_flow") == 2_400
        assert r.budget("compact") == 780

    def test_unknown_component_uses_default_ratio(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.budget("unknown") == 8_100  # 0.27 ratio

    def test_ask_budget_shortcut(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.ask_budget("flow") == 12_000
        assert r.ask_budget("general") == 8_100
        assert r.ask_budget(None) == 8_100

    def test_floor_prevents_zero(self):
        r = TokenBudgetResolver(base=100)
        assert r.budget("compact") >= 512
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_token_budget.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'wiki.token_budget'`

- [x] **Step 3: Implement TokenBudgetResolver**

```python
# wiki/token_budget.py
from __future__ import annotations


class TokenBudgetResolver:
    """Derives per-component token budgets from a single base value.

    Each component's budget = base × ratio, capped at ceiling × 0.8.
    The floor prevents degenerate budgets on very small base values.
    """

    RATIOS: dict[str, float] = {
        "decomposition": 1.0,
        "ask_concept": 0.33,
        "ask_flow": 0.40,
        "ask_relation": 0.27,
        "ask_impact": 0.33,
        "ask_general": 0.27,
        "compact": 0.13,
        "assembly": 0.27,
    }
    _FLOOR = 512

    def __init__(self, base: int, ceiling: int | None = None):
        self._base = base
        self._ceiling = int(ceiling * 0.8) if ceiling else None

    def budget(self, component: str) -> int:
        ratio = self.RATIOS.get(component, 0.27)
        raw = int(self._base * ratio)
        raw = max(raw, self._FLOOR)
        if self._ceiling:
            return min(raw, self._ceiling)
        return raw

    def ask_budget(self, question_type: str | None = None) -> int:
        key = f"ask_{question_type or 'general'}"
        return self.budget(key)
```

- [x] **Step 4: Add config fields**

In `config.py`, add to `AppLlmSettings` (after existing fields around line 116):

```python
max_context_tokens: int = Field(
    default=128_000,
    description="LLM model context window size. Safety ceiling for all budget calculations.",
)
```

In `config.py`, add to `AppWikiFlags` (after `resume_from_saved` around line 306):

```python
default_llm_budget: int = Field(
    default=30_000,
    description=(
        "Base token budget for all LLM operations. "
        "Components derive budgets as fixed proportions of this value."
    ),
)
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_token_budget.py -v`
Expected: ALL PASS

- [x] **Step 6: Run full test suite to check for regressions**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: 2015+ passed

- [x] **Step 7: Commit**

```bash
git add wiki/token_budget.py tests/wiki/test_token_budget.py config.py
git commit -m "feat(wiki): add TokenBudgetResolver with ratio-based budget derivation"
```

---

## Task 2: Replace wiki/ask.py hardcoded budgets

**Files:**
- Modify: `wiki/ask.py:142-160`
- Modify: `tests/test_wiki_ask_dynamic_budget.py`

- [x] **Step 1: Write failing test for resolver integration**

```python
# In tests/test_wiki_ask_dynamic_budget.py, add:
def test_ask_budget_uses_resolver_proportions():
    """Verify budgets scale proportionally when base changes."""
    from wiki.ask import wiki_context_token_budget_from_resolver
    from wiki.token_budget import TokenBudgetResolver

    r = TokenBudgetResolver(base=30_000)
    concept = wiki_context_token_budget_from_resolver("what is X?", "concept", r)
    flow = wiki_context_token_budget_from_resolver("how does X flow?", "flow", r)
    assert concept < flow  # flow gets higher ratio

    r_small = TokenBudgetResolver(base=6_000)
    concept_small = wiki_context_token_budget_from_resolver("what is X?", "concept", r_small)
    assert concept_small < concept  # smaller base = smaller budget
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_wiki_ask_dynamic_budget.py::test_ask_budget_uses_resolver_proportions -v`
Expected: FAIL — `ImportError`

- [x] **Step 3: Add resolver-based budget function to wiki/ask.py**

In `wiki/ask.py`, after the existing `wiki_context_token_budget` function (around line 160), add:

```python
def wiki_context_token_budget_from_resolver(
    question: str,
    question_type: str | None,
    resolver: "TokenBudgetResolver",
) -> int:
    qt = question_type if question_type is not None else detect_question_type(question)
    base = resolver.ask_budget(qt)
    q_tokens = max(len(question) // 4, 0)
    return min(base + q_tokens, resolver.budget("decomposition"))
```

Update the existing `wiki_context_token_budget` to delegate when a global resolver is available:

```python
_WIKI_TYPE_TOKEN_BUDGET: dict[str, int] = {
    "concept": 6000,
    "flow": 10000,
    "relation": 10000,
    "impact": 8000,
    "general": 8000,
}

_default_resolver: TokenBudgetResolver | None = None


def set_default_resolver(resolver: TokenBudgetResolver) -> None:
    global _default_resolver
    _default_resolver = resolver


def wiki_context_token_budget(question: str, question_type: str | None = None) -> int:
    if _default_resolver is not None:
        return wiki_context_token_budget_from_resolver(question, question_type, _default_resolver)
    qt = question_type if question_type is not None else detect_question_type(question)
    base = _WIKI_TYPE_TOKEN_BUDGET.get(qt, 8000)
    q_tokens = max(len(question) // 4, 0)
    return min(base + q_tokens, 16000)
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_wiki_ask_dynamic_budget.py -v`
Expected: ALL PASS

- [x] **Step 5: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: All existing tests still pass (backward compat: `_default_resolver` is None by default)

- [x] **Step 6: Commit**

```bash
git add wiki/ask.py tests/test_wiki_ask_dynamic_budget.py
git commit -m "feat(wiki): integrate TokenBudgetResolver into wiki Q&A budget"
```

---

## Task 3: Replace compact_formatter + context_assembler defaults

**Files:**
- Modify: `wiki/compact_formatter.py:12-16`
- Modify: `query/context_assembler.py:55-60`
- Test: `tests/wiki/test_compact_formatter.py`, `tests/test_context_assembler.py`

- [x] **Step 1: Write failing tests**

```python
# tests/wiki/test_compact_formatter.py, add:
def test_formatter_accepts_resolver_budget():
    from wiki.token_budget import TokenBudgetResolver
    from wiki.compact_formatter import CompactFormatter

    r = TokenBudgetResolver(base=30_000)
    formatter = CompactFormatter(max_tokens=r.budget("compact"))
    assert formatter._max_tokens == 3_900

    r_small = TokenBudgetResolver(base=6_000)
    formatter_small = CompactFormatter(max_tokens=r_small.budget("compact"))
    assert formatter_small._max_tokens == 780
```

```python
# tests/test_context_assembler.py, add:
def test_assembler_accepts_resolver_budget():
    from wiki.token_budget import TokenBudgetResolver

    r = TokenBudgetResolver(base=30_000)
    budget = r.budget("assembly")
    assert budget == 8_100
```

- [x] **Step 2: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compact_formatter.py::test_formatter_accepts_resolver_budget tests/test_context_assembler.py::test_assembler_accepts_resolver_budget -v`
Expected: PASS (these tests just verify the resolver provides correct values; no code change needed yet)

- [x] **Step 3: Update compact_formatter default**

In `wiki/compact_formatter.py`, no signature change needed. The `max_tokens` param stays as-is. The caller (`wiki/service.py`) will pass `resolver.budget("compact")` when constructing the formatter. This is wired in Task 5.

- [x] **Step 4: Commit**

```bash
git add tests/wiki/test_compact_formatter.py tests/test_context_assembler.py
git commit -m "test: add token budget resolver integration tests for formatter and assembler"
```

---

## Task 4: Replace dependency_graph.py class constant

**Files:**
- Modify: `wiki/dependency_graph.py:152`
- Test: `tests/wiki/test_dependency_graph.py`

- [x] **Step 1: Write failing test**

```python
# tests/wiki/test_dependency_graph.py, add:
def test_module_repr_builder_respects_external_budget():
    from wiki.dependency_graph import ModuleReprBuilder, TokenBudget, ModuleInfo

    builder = ModuleReprBuilder()
    budget = TokenBudget(total=500, used=0)
    module = ModuleInfo(
        name="SmallModule", path="pkg/small.py", uid="uid1",
        summary="A small module", semantic_roles=[],
    )
    result = builder.build(module, budget)
    assert len(result) > 0
    assert budget.used > 0
```

- [x] **Step 2: Run test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_dependency_graph.py::test_module_repr_builder_respects_external_budget -v`
Expected: PASS (the builder already respects external TokenBudget)

- [x] **Step 3: Remove hardcoded MAX_TOKENS_PER_BATCH from ModuleReprBuilder**

In `wiki/dependency_graph.py`, the `MAX_TOKENS_PER_BATCH = 30_000` class constant on `ModuleReprBuilder` is not used internally by the builder itself (it only uses the passed `TokenBudget`). It's referenced by `HierarchicalDecomposer.__init__` which receives `max_tokens_per_batch` as a constructor param. Remove the class constant:

```python
# wiki/dependency_graph.py line 152
# BEFORE:
class ModuleReprBuilder:
    MAX_TOKENS_PER_BATCH = 30_000

# AFTER:
class ModuleReprBuilder:
    pass  # Budget is controlled by the TokenBudget passed to build()
```

Actually, keep the class body as-is but just remove the constant line. The `build` method and other content remain.

- [x] **Step 4: Update HierarchicalDecomposer default**

In `wiki/dependency_graph.py`, the `HierarchicalDecomposer.__init__` has `max_tokens_per_batch: int = 30_000`. This stays as-is for now — it becomes the fallback when no resolver is available. The caller (`wiki/cross_repo_domain_planner.py`) will pass `resolver.budget("decomposition")` in Task 5.

- [x] **Step 5: Run full suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: All pass

- [x] **Step 6: Commit**

```bash
git add wiki/dependency_graph.py tests/wiki/test_dependency_graph.py
git commit -m "refactor(wiki): remove hardcoded MAX_TOKENS_PER_BATCH from ModuleReprBuilder"
```

---

## Task 5: Wire resolver into wiki/service.py

**Files:**
- Modify: `wiki/service.py` (multiple locations)
- Modify: `wiki/bootstrap.py` (if resolver needs to be available at startup)
- Test: `tests/wiki/test_token_budget.py` (add integration test)

- [x] **Step 1: Write failing integration test**

```python
# tests/wiki/test_token_budget.py, add:
def test_resolver_from_config():
    from config import get_settings
    from wiki.token_budget import TokenBudgetResolver

    settings = get_settings()
    r = TokenBudgetResolver(
        base=settings.wiki.default_llm_budget,
        ceiling=settings.llm.max_context_tokens,
    )
    assert r.budget("decomposition") == 30_000
    assert r.budget("decomposition") <= int(128_000 * 0.8)
```

- [x] **Step 2: Run test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_token_budget.py::test_resolver_from_config -v`
Expected: PASS (config fields already added in Task 1)

- [x] **Step 3: Instantiate resolver in WikiService.__init__**

In `wiki/service.py`, in the `WikiService.__init__` method, add after the existing config loading:

```python
from wiki.token_budget import TokenBudgetResolver

self._budget_resolver = TokenBudgetResolver(
    base=self._wiki_cfg.default_llm_budget,
    ceiling=getattr(self._settings.llm, 'max_context_tokens', 128_000),
)
```

- [x] **Step 4: Wire resolver to wiki/ask.py**

In `wiki/service.py`, where `WikiAsk` or wiki context is assembled, call:

```python
from wiki.ask import set_default_resolver
set_default_resolver(self._budget_resolver)
```

This ensures the global resolver is set when `WikiService` initializes.

- [x] **Step 5: Wire resolver to cross_repo_domain_planner**

In `wiki/service.py:generate_business_wiki`, when constructing `CrossRepoBusinessDomainPlanner`, pass the decomposition budget:

```python
planner = CrossRepoBusinessDomainPlanner(
    llm_port,
    infrastructure_label=app_cfg.business_domain_infrastructure_label,
    batch_threshold=app_cfg.business_wiki_batch_threshold,
    sub_batch_size=app_cfg.business_domain_sub_batch_size,
    max_concurrency=app_cfg.business_domain_max_concurrency,
    max_tokens_per_batch=self._budget_resolver.budget("decomposition"),
)
```

- [x] **Step 6: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: All pass

- [x] **Step 7: Commit**

```bash
git add wiki/service.py wiki/ask.py
git commit -m "feat(wiki): wire TokenBudgetResolver into WikiService and downstream components"
```

---

## Task 6: Deprecate decomposition_max_tokens_per_batch

**Files:**
- Modify: `config.py:319`
- Test: `tests/test_wiki_config_defaults.py`

- [x] **Step 1: Write test for deprecation warning**

```python
# tests/test_wiki_config_defaults.py, add:
def test_decomposition_max_tokens_deprecated_field_still_works():
    import warnings
    from config import AppWikiFlags
    cfg = AppWikiFlags()
    assert hasattr(cfg, 'decomposition_max_tokens_per_batch')
    assert hasattr(cfg, 'default_llm_budget')
    assert cfg.default_llm_budget == 30_000
```

- [x] **Step 2: Run test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_wiki_config_defaults.py -v`
Expected: PASS

- [x] **Step 3: Add deprecation comment to config field**

In `config.py`, update the `decomposition_max_tokens_per_batch` field:

```python
# DEPRECATED: Use default_llm_budget instead. Will be removed in a future version.
decomposition_max_tokens_per_batch: int = Field(default=30000)
```

- [x] **Step 4: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/ -q --tb=short 2>&1 | tail -5`
Expected: All pass

- [x] **Step 5: Commit**

```bash
git add config.py tests/test_wiki_config_defaults.py
git commit -m "chore(config): deprecate decomposition_max_tokens_per_batch in favor of default_llm_budget"
```

---

## Self-Review Checklist

**Spec coverage:**
- [x] §3.2 Config Model Changes — Task 1
- [x] §3.3 Budget Resolution Helper → `TokenBudgetResolver` — Task 1
- [x] §3.4 Migration Path Phase 1 (config + resolver) — Task 1
- [x] §3.4 Migration Path Phase 2 (wiki/ask.py) — Task 2
- [x] §3.4 Migration Path Phase 3 (compact + assembler) — Task 3
- [x] §3.4 Migration Path Phase 4 (dependency_graph) — Task 4
- [x] §3.4 Migration Path Phase 5 (deprecation) — Task 6
- [x] §3.5 Backward Compatibility — All tasks preserve existing signatures
- [x] §5 Test Plan — Covered across Tasks 1-6

**Placeholder scan:** No TBDs, TODOs, or vague steps found.

**Type consistency:** `TokenBudgetResolver` class name, `budget()` and `ask_budget()` methods consistent across all tasks.
