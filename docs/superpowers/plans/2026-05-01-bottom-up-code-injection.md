# Bottom-up 递归生成与代码注入 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement leaf→parent→system bottom-up recursive wiki generation with code signature injection and ENTRY_POINT role recognition.

**Architecture:** Restructure the LangGraph wiki pipeline into 3 explicit phases (compose_leaf_pages → summarize_leaves → compose_parent_pages), add a code snippet selector that ranks method names by importance, and enhance entity role classification with ENTRY_POINT detection.

**Tech Stack:** Python 3.11+, LangGraph, asyncio, pytest, dataclasses

---

## File Structure

### New Files

| File | Responsibility |
|------|---------------|
| `wiki/snippet_selector.py` | Rank and select key method signatures from module metadata |
| `wiki/token_budget.py` | Calculate context-window-aware token budgets per component |
| `tests/wiki/test_snippet_selector.py` | Tests for snippet selection algorithm |
| `tests/wiki/test_token_budget.py` | Tests for token budget calculator |
| `tests/wiki/test_summarize_leaves.py` | Tests for leaf summary extraction |
| `tests/wiki/test_compose_parents.py` | Tests for parent domain page generation |
| `tests/wiki/test_entry_point_role.py` | Tests for ENTRY_POINT role detection |

### Modified Files

| File | Changes |
|------|---------|
| `wiki/entity_role_classifier.py` | Add `ENTRY_POINT` enum + detection rules |
| `wiki/models.py` | Add `LeafSummary` dataclass, `WikiPageMetadata.executive_summary` field |
| `wiki/pipeline_state.py` | Add `leaf_summaries` field to `WikiPipelineState` |
| `wiki/pipeline_nodes.py` | Rename `compose_pages_node` → `compose_leaf_pages_node`, add `summarize_leaves_node`, `compose_parent_pages_node` |
| `wiki/pipeline_graph.py` | Rename node, add new nodes/edges, add conditional routing |
| `wiki/topic_page_composer.py` | Add `executive_summary` to JSON output, add code snippets section to prompt |
| `wiki/prompts.py` | Add `SYSTEM_WIKI_PARENT_OVERVIEW` prompt constant |

---

## Task 1: ENTRY_POINT Role Enhancement

**Files:**
- Modify: `wiki/entity_role_classifier.py`
- Test: `tests/wiki/test_entry_point_role.py`

- [ ] **Step 1: Write failing tests for ENTRY_POINT detection**

Create `tests/wiki/test_entry_point_role.py`:

```python
import pytest
from wiki.entity_role_classifier import WikiEntityRole, EntityRoleClassifier


def test_entry_point_main_method():
    """Module with main method should be classified as ENTRY_POINT."""
    classifier = EntityRoleClassifier()
    props = {
        "name": "AppMain",
        "methods": ["main", "run"],
        "calls": [],
        "annotations": [],
        "methods_count": 2,
    }
    role = classifier.classify(props)
    assert role == WikiEntityRole.ENTRY_POINT


def test_entry_point_http_handler_annotation():
    """Module with HTTP handler annotations should be ENTRY_POINT."""
    classifier = EntityRoleClassifier()
    props = {
        "name": "UserController",
        "methods": ["getUser", "createUser"],
        "calls": ["UserService.findById"],
        "annotations": ["@RestController", "@RequestMapping"],
        "methods_count": 2,
    }
    role = classifier.classify(props)
    assert role == WikiEntityRole.ENTRY_POINT


def test_entry_point_flask_route():
    """Module with @app.route should be ENTRY_POINT."""
    classifier = EntityRoleClassifier()
    props = {
        "name": "views",
        "methods": ["index", "login"],
        "calls": [],
        "annotations": ["@app.route"],
        "methods_count": 2,
    }
    role = classifier.classify(props)
    assert role == WikiEntityRole.ENTRY_POINT


def test_entry_point_filename_controller():
    """Module with Controller in name should be ENTRY_POINT."""
    classifier = EntityRoleClassifier()
    props = {
        "name": "OrderController",
        "methods": ["listOrders"],
        "calls": ["OrderService.list"],
        "annotations": [],
        "methods_count": 1,
    }
    role = classifier.classify(props)
    assert role == WikiEntityRole.ENTRY_POINT


def test_entry_point_backward_compat_in_domain_filter():
    """ENTRY_POINT should pass has_business_logic filter for domain classification."""
    role = WikiEntityRole.ENTRY_POINT
    assert role in (WikiEntityRole.HAS_BUSINESS_LOGIC, WikiEntityRole.ENTRY_POINT)


def test_non_entry_point_normal_service():
    """Regular service class should NOT be ENTRY_POINT."""
    classifier = EntityRoleClassifier()
    props = {
        "name": "UserService",
        "methods": ["findById", "save"],
        "calls": ["UserRepository.find"],
        "annotations": ["@Service"],
        "methods_count": 2,
    }
    role = classifier.classify(props)
    assert role != WikiEntityRole.ENTRY_POINT
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_entry_point_role.py -v`
Expected: FAIL — `WikiEntityRole` has no `ENTRY_POINT` attribute

- [ ] **Step 3: Implement ENTRY_POINT role**

In `wiki/entity_role_classifier.py`, add the enum value and detection logic:

```python
class WikiEntityRole(StrEnum):
    ENTRY_POINT = "entry_point"
    HAS_BUSINESS_LOGIC = "has_business_logic"
    SUPPORTING = "supporting"
    DATA_MODEL = "data_model"
    FRAMEWORK_NOISE = "framework_noise"
```

Add entry point detection in the Phase 1 short-circuit section of `EntityRoleClassifier.classify`, **before** the existing `DATA_MODEL` / `FRAMEWORK_NOISE` checks:

```python
_ENTRY_POINT_ANNOTATIONS = frozenset({
    "@RestController", "@Controller", "@RequestMapping",
    "@GetMapping", "@PostMapping", "@PutMapping", "@DeleteMapping", "@PatchMapping",
    "@app.route", "@router.get", "@router.post", "@router.put", "@router.delete",
    "@click.command", "@click.group",
})

_ENTRY_POINT_NAME_PATTERNS = ("Controller", "Handler", "Endpoint", "Router")

def _is_entry_point(self, props: dict) -> bool:
    methods = props.get("methods", []) or []
    if isinstance(methods, list) and "main" in methods:
        return True
    annotations = props.get("annotations", []) or []
    if isinstance(annotations, list):
        for ann in annotations:
            ann_str = str(ann)
            if any(ep in ann_str for ep in self._ENTRY_POINT_ANNOTATIONS):
                return True
    name = props.get("name", "")
    if any(pat in name for pat in self._ENTRY_POINT_NAME_PATTERNS):
        return True
    return False
```

Call `_is_entry_point` at the start of `classify`:
```python
if self._is_entry_point(props):
    return WikiEntityRole.ENTRY_POINT
```

- [ ] **Step 4: Update classify_domains_node module filter for ENTRY_POINT compatibility**

In `wiki/pipeline_nodes.py`, find where modules are filtered by role for domain classification. Update the filter:

```python
# Before:
if role == "has_business_logic":
# After:
if role in ("has_business_logic", "entry_point"):
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_entry_point_role.py -v`
Expected: All 6 tests PASS

- [ ] **Step 6: Run existing tests to check no regression**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -x -q --timeout=60`
Expected: All existing tests still pass

- [ ] **Step 7: Commit**

```bash
git add wiki/entity_role_classifier.py wiki/pipeline_nodes.py tests/wiki/test_entry_point_role.py
git commit -m "feat(wiki): add ENTRY_POINT entity role with deterministic detection"
```

---

## Task 2: TokenBudgetCalculator

**Files:**
- Create: `wiki/token_budget.py`
- Test: `tests/wiki/test_token_budget.py`

- [ ] **Step 1: Write failing tests**

Create `tests/wiki/test_token_budget.py`:

```python
from wiki.token_budget import TokenBudgetCalculator


def test_available_input_default():
    calc = TokenBudgetCalculator()
    assert calc.available_input == 128_000 - 4_096 - 2_000


def test_available_input_custom_window():
    calc = TokenBudgetCalculator(context_window=32_000)
    assert calc.available_input == 32_000 - 4_096 - 2_000


def test_budget_for_snippets_small_domain():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(3) == 500 + 3 * 100  # 800


def test_budget_for_snippets_large_domain_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(100) == 3000  # capped


def test_budget_for_parent_summaries():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_parent_summaries(3) == 900


def test_budget_for_parent_summaries_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_parent_summaries(20) == 5000


def test_budget_for_system_overview():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_system_overview(10) == 2000


def test_budget_for_system_overview_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_system_overview(50) == 8000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_token_budget.py -v`
Expected: FAIL — module `wiki.token_budget` not found

- [ ] **Step 3: Implement TokenBudgetCalculator**

Create `wiki/token_budget.py`:

```python
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TokenBudgetCalculator:
    context_window: int = 128_000
    reserved_output: int = 4_096
    reserved_system: int = 2_000

    @property
    def available_input(self) -> int:
        return self.context_window - self.reserved_output - self.reserved_system

    def budget_for_snippets(self, module_count: int) -> int:
        return min(500 + module_count * 100, 3000)

    def budget_for_parent_summaries(self, child_count: int) -> int:
        return min(child_count * 300, 5000)

    def budget_for_system_overview(self, domain_count: int) -> int:
        return min(domain_count * 200, 8000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_token_budget.py -v`
Expected: All 8 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/token_budget.py tests/wiki/test_token_budget.py
git commit -m "feat(wiki): add TokenBudgetCalculator for context-window-aware budgeting"
```

---

## Task 3: Snippet Selector

**Files:**
- Create: `wiki/snippet_selector.py`
- Test: `tests/wiki/test_snippet_selector.py`

**Context:** Pipeline state `modules` have `properties.methods` as `list[str]` (method names only), `properties.calls` as `list[str]`, and `properties.docstring` as optional string. Function nodes in the graph have full signatures but are NOT loaded into pipeline state. This v1 works with available module-level data.

- [ ] **Step 1: Write failing tests**

Create `tests/wiki/test_snippet_selector.py`:

```python
import pytest
from wiki.snippet_selector import select_key_snippets, MethodSnippet


def _make_module(name: str, methods: list[str], calls: list[str] | None = None,
                 docstring: str = "", uid: str = "") -> dict:
    return {
        "uid": uid or f"Module::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "methods": methods,
            "calls": calls or [],
            "docstring": docstring,
        },
    }


def test_select_empty_modules():
    result = select_key_snippets([], {})
    assert result == []


def test_select_basic_ranking():
    modules = [
        _make_module("OrderService", ["processOrder", "cancelOrder", "getStatus"],
                     calls=["PaymentService.charge", "InventoryService.reserve"]),
    ]
    entity_roles = {"Module::OrderService:0": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    assert len(result) > 0
    assert all(isinstance(s, MethodSnippet) for s in result)


def test_entry_point_methods_ranked_higher():
    modules = [
        _make_module("UserController", ["getUser", "createUser"], uid="m1"),
        _make_module("UserService", ["findById", "save"], uid="m2"),
    ]
    entity_roles = {"m1": "entry_point", "m2": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    entry_methods = [s for s in result if s.module_name == "UserController"]
    other_methods = [s for s in result if s.module_name == "UserService"]
    if entry_methods and other_methods:
        assert entry_methods[0].score > other_methods[0].score


def test_per_module_limit():
    modules = [
        _make_module("BigService", [f"method_{i}" for i in range(20)]),
    ]
    result = select_key_snippets(modules, {}, max_per_module=3)
    assert len(result) <= 3


def test_budget_token_limit():
    modules = [
        _make_module(f"Service{i}", [f"m{j}" for j in range(5)])
        for i in range(10)
    ]
    result = select_key_snippets(modules, {}, budget_tokens=500)
    total_chars = sum(len(s.format_for_prompt()) for s in result)
    assert total_chars <= 500 * 4  # rough char-to-token ratio


def test_called_methods_ranked_higher():
    modules = [
        _make_module("A", ["doWork"], calls=[]),
        _make_module("B", ["helper"], calls=["A.doWork", "A.doWork", "A.doWork"]),
    ]
    entity_roles = {"Module::A:0": "has_business_logic", "Module::B:0": "has_business_logic"}
    result = select_key_snippets(modules, entity_roles)
    a_methods = [s for s in result if s.module_name == "A"]
    assert len(a_methods) > 0


def test_format_for_prompt():
    modules = [
        _make_module("OrderService", ["processOrder"],
                     docstring="Handles order processing workflow"),
    ]
    result = select_key_snippets(modules, {})
    assert len(result) == 1
    prompt_text = result[0].format_for_prompt()
    assert "OrderService" in prompt_text
    assert "processOrder" in prompt_text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_snippet_selector.py -v`
Expected: FAIL — module `wiki.snippet_selector` not found

- [ ] **Step 3: Implement snippet_selector**

Create `wiki/snippet_selector.py`:

```python
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class MethodSnippet:
    module_name: str
    method_name: str
    score: float
    module_docstring: str = ""
    file_path: str = ""

    def format_for_prompt(self) -> str:
        line = f"  - {self.module_name}.{self.method_name}()"
        if self.module_docstring:
            short_doc = self.module_docstring[:120].split("\n")[0]
            line = f"{line}  # {short_doc}"
        return line


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def _count_in_degree(method_name: str, module_name: str,
                     all_modules: list[dict]) -> int:
    target_patterns = (
        f"{module_name}.{method_name}",
        method_name,
    )
    count = 0
    for mod in all_modules:
        calls = mod.get("properties", {}).get("calls", []) or []
        if not isinstance(calls, list):
            continue
        for call in calls:
            call_str = str(call)
            if any(pat in call_str for pat in target_patterns):
                count += 1
    return count


def select_key_snippets(
    modules: list[dict],
    entity_roles: dict[str, str],
    budget_tokens: int = 2000,
    max_per_module: int = 3,
) -> list[MethodSnippet]:
    if not modules:
        return []

    candidates: list[MethodSnippet] = []

    for mod in modules:
        props = mod.get("properties", {})
        mod_name = props.get("name", "")
        mod_uid = mod.get("uid", "")
        role = entity_roles.get(mod_uid, "supporting")
        methods = props.get("methods", []) or []
        docstring = str(props.get("docstring", "") or "")
        file_path = str(props.get("path", "") or props.get("file", "") or "")

        if not isinstance(methods, list):
            continue

        module_candidates: list[MethodSnippet] = []
        for method_name in methods:
            method_str = str(method_name)
            if not method_str or method_str.startswith("_"):
                score_public = 0
            else:
                score_public = 1

            score = score_public

            if role == "entry_point":
                score += 10

            in_degree = _count_in_degree(method_str, mod_name, modules)
            score += in_degree * 3

            if docstring:
                score += 2

            module_candidates.append(MethodSnippet(
                module_name=mod_name,
                method_name=method_str,
                score=score,
                module_docstring=docstring,
                file_path=file_path,
            ))

        module_candidates.sort(key=lambda s: s.score, reverse=True)
        candidates.extend(module_candidates[:max_per_module])

    candidates.sort(key=lambda s: s.score, reverse=True)

    result: list[MethodSnippet] = []
    used_tokens = 0
    for snippet in candidates:
        tokens = _estimate_tokens(snippet.format_for_prompt())
        if used_tokens + tokens > budget_tokens:
            break
        result.append(snippet)
        used_tokens += tokens

    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_snippet_selector.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/snippet_selector.py tests/wiki/test_snippet_selector.py
git commit -m "feat(wiki): add snippet_selector for ranking key method signatures"
```

---

## Task 4: Model Changes (LeafSummary + executive_summary)

**Files:**
- Modify: `wiki/models.py`
- Modify: `wiki/pipeline_state.py`

- [ ] **Step 1: Add LeafSummary and executive_summary to models**

In `wiki/models.py`, add `LeafSummary` dataclass:

```python
@dataclass
class LeafSummary:
    domain_name: str
    summary_text: str
    module_count: int
    key_entities: list[str] = field(default_factory=list)
    source: str = "rule_extracted"  # "llm" | "rule_extracted"
```

In `WikiPageMetadata`, add:
```python
    executive_summary: str | None = None
```

- [ ] **Step 2: Update WikiPipelineState**

In `wiki/pipeline_state.py`, add to `WikiPipelineState`:
```python
    leaf_summaries: dict[str, Any]
```

With a default empty dict annotation or NotRequired if using TypedDict.

- [ ] **Step 3: Run existing tests to check no regression**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -x -q --timeout=60`
Expected: All existing tests pass

- [ ] **Step 4: Commit**

```bash
git add wiki/models.py wiki/pipeline_state.py
git commit -m "feat(wiki): add LeafSummary model and executive_summary metadata field"
```

---

## Task 5: Rename compose_pages_node → compose_leaf_pages_node

**Files:**
- Modify: `wiki/pipeline_nodes.py` (function rename)
- Modify: `wiki/pipeline_graph.py` (node name)
- Modify: any test files referencing `compose_pages_node`

- [ ] **Step 1: Rename the function in pipeline_nodes.py**

Find `async def compose_pages_node` and rename to `async def compose_leaf_pages_node`. Keep all internal logic unchanged.

- [ ] **Step 2: Update pipeline_graph.py**

Find `graph.add_node("compose_pages", compose_pages_node)` and change to:
```python
graph.add_node("compose_leaf_pages", compose_leaf_pages_node)
```

Update all edges that reference `"compose_pages"` to `"compose_leaf_pages"`.

Update the import to use `compose_leaf_pages_node`.

- [ ] **Step 3: Update test references**

Search all test files for `compose_pages_node` and update to `compose_leaf_pages_node`.

- [ ] **Step 4: Run all tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -x -q --timeout=60`
Expected: All tests pass (pure rename, no logic change)

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/
git commit -m "refactor(wiki): rename compose_pages_node to compose_leaf_pages_node"
```

---

## Task 6: TopicPageComposer — executive_summary + Code Snippets

**Files:**
- Modify: `wiki/topic_page_composer.py`
- Modify: `wiki/pipeline_nodes.py` (_compose_single_leaf_domain)
- Modify: `wiki/prompts.py`

- [ ] **Step 1: Add SYSTEM_WIKI_PARENT_OVERVIEW to prompts.py**

In `wiki/prompts.py`, add:

```python
SYSTEM_WIKI_PARENT_OVERVIEW = (
    "You are a senior technical writer creating a domain overview page that "
    "synthesizes information from its sub-domains. Write like a technical blog post "
    "— explain HOW sub-domains relate and WHY they exist together. "
    "Output valid JSON only."
)
```

- [ ] **Step 2: Modify TopicPageComposer prompts to request executive_summary**

In `wiki/topic_page_composer.py`, find the JSON output format instructions in `_build_single_page_prompt` (and `_build_overview_prompt`, `_build_sub_page_prompt`). Add to the JSON schema description:

```
Include an "executive_summary" field (string, 150-300 chars) that captures the domain's core purpose in 1-2 sentences.
```

- [ ] **Step 3: Update JSON parsing to extract executive_summary**

In the response parsing logic (where `WikiPage.from_dict` or manual dict construction happens), extract `executive_summary` from the LLM JSON response and store it in `metadata`:

```python
executive_summary = page_dict.get("executive_summary", "")
# Store in metadata
metadata.executive_summary = executive_summary if executive_summary else None
```

- [ ] **Step 4: Add code snippet injection to _compose_single_leaf_domain**

In `wiki/pipeline_nodes.py`, in `_compose_single_leaf_domain`, after building `biz_entities` and `data_models`, add snippet selection:

```python
from wiki.snippet_selector import select_key_snippets
from wiki.token_budget import TokenBudgetCalculator

budget_calc = TokenBudgetCalculator()
domain_modules = [module_index[m] for m in domain.get("modules", []) if m in module_index]
snippets = select_key_snippets(domain_modules, entity_roles,
                                budget_tokens=budget_calc.budget_for_snippets(len(domain_modules)))

snippet_section = ""
if snippets:
    lines = [s.format_for_prompt() for s in snippets]
    snippet_section = "\n## Key Code Interfaces\n" + "\n".join(lines) + "\n"
```

Pass `snippet_section` into the compose prompt (append to `domain_input` or directly to the prompt string).

- [ ] **Step 5: Run tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -x -q --timeout=60`
Expected: All tests pass

- [ ] **Step 6: Commit**

```bash
git add wiki/topic_page_composer.py wiki/pipeline_nodes.py wiki/prompts.py
git commit -m "feat(wiki): add executive_summary output and code snippet injection to compose"
```

---

## Task 7: summarize_leaves_node

**Files:**
- Modify: `wiki/pipeline_nodes.py` (add function)
- Test: `tests/wiki/test_summarize_leaves.py`

- [ ] **Step 1: Write failing tests**

Create `tests/wiki/test_summarize_leaves.py`:

```python
import pytest
from wiki.pipeline_nodes import summarize_leaves_node


def _make_page(path: str, content: str, page_type: str = "topic",
               executive_summary: str | None = None) -> dict:
    metadata = {}
    if executive_summary:
        metadata["executive_summary"] = executive_summary
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": page_type,
        "metadata": metadata,
    }


@pytest.mark.asyncio
async def test_summarize_from_executive_summary():
    state = {
        "pages": {
            "wiki/orders": _make_page(
                "wiki/orders", "Long content...",
                executive_summary="Order domain handles e-commerce order lifecycle."
            ),
        },
        "domain_tree": [{"name": "orders", "modules": ["OrderService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert "orders" in summaries
    assert summaries["orders"]["summary_text"] == "Order domain handles e-commerce order lifecycle."
    assert summaries["orders"]["source"] == "llm"


@pytest.mark.asyncio
async def test_summarize_fallback_first_paragraph():
    content = "# Order Domain\n\nThis domain manages the complete order lifecycle.\n\n## Details\n\nMore text here."
    state = {
        "pages": {
            "wiki/orders": _make_page("wiki/orders", content),
        },
        "domain_tree": [{"name": "orders", "modules": ["OrderService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert "orders" in summaries
    assert "order lifecycle" in summaries["orders"]["summary_text"].lower()
    assert summaries["orders"]["source"] == "rule_extracted"


@pytest.mark.asyncio
async def test_summarize_fallback_truncate():
    content = "A" * 500
    state = {
        "pages": {
            "wiki/big": _make_page("wiki/big", content),
        },
        "domain_tree": [{"name": "big", "modules": ["BigService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert len(summaries["big"]["summary_text"]) <= 300


@pytest.mark.asyncio
async def test_summarize_no_pages():
    state = {
        "pages": {},
        "domain_tree": [{"name": "empty", "modules": [], "children": []}],
    }
    result = await summarize_leaves_node(state)
    assert result["leaf_summaries"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_summarize_leaves.py -v`
Expected: FAIL — `summarize_leaves_node` not found

- [ ] **Step 3: Implement summarize_leaves_node**

In `wiki/pipeline_nodes.py`, add:

```python
import re

def _extract_summary_from_content(content: str) -> str:
    """Rule-based summary extraction from wiki page content."""
    if not content:
        return ""
    for heading in ("## 业务概述", "## Overview", "## Summary", "## 概述"):
        pattern = re.escape(heading) + r"\s*\n+(.*?)(?=\n##|\Z)"
        match = re.search(pattern, content, re.DOTALL)
        if match:
            text = match.group(1).strip()
            if text:
                return text[:300]
    heading_match = re.search(r"^#[^#].*\n\n(.+?)(?:\n\n|\Z)", content, re.MULTILINE | re.DOTALL)
    if heading_match:
        paragraph = heading_match.group(1).strip()
        if paragraph:
            return paragraph[:300]
    return content[:300].strip()


async def summarize_leaves_node(state: dict) -> dict:
    pages = state.get("pages", {})
    domain_tree = state.get("domain_tree", []) or []
    leaf_domains = _collect_leaf_domains(domain_tree)

    leaf_summaries: dict[str, dict] = {}
    for leaf in leaf_domains:
        domain_name = leaf.get("name", "")
        if not domain_name:
            continue
        matching_page = None
        for path, page in pages.items():
            if domain_name.lower().replace(" ", "_") in path.lower():
                matching_page = page
                break
        if not matching_page:
            continue
        metadata = matching_page.get("metadata", {}) or {}
        exec_summary = metadata.get("executive_summary")
        if exec_summary:
            summary_text = str(exec_summary)[:300]
            source = "llm"
        else:
            content = matching_page.get("content", "")
            summary_text = _extract_summary_from_content(content)
            source = "rule_extracted"

        modules = leaf.get("modules", []) or []
        leaf_summaries[domain_name] = {
            "domain_name": domain_name,
            "summary_text": summary_text,
            "module_count": len(modules),
            "key_entities": [str(m) for m in modules[:5]],
            "source": source,
        }

    return {"leaf_summaries": leaf_summaries}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_summarize_leaves.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_summarize_leaves.py
git commit -m "feat(wiki): add summarize_leaves_node for rule-based leaf summary extraction"
```

---

## Task 8: compose_parent_pages_node

**Files:**
- Modify: `wiki/pipeline_nodes.py` (add function)
- Test: `tests/wiki/test_compose_parents.py`

- [ ] **Step 1: Write failing tests**

Create `tests/wiki/test_compose_parents.py`:

```python
import pytest
from unittest.mock import AsyncMock
from wiki.pipeline_nodes import compose_parent_pages_node, has_parent_domains


def test_has_parent_domains_true():
    state = {
        "domain_tree": [
            {"name": "root", "modules": [], "children": [
                {"name": "child1", "modules": ["A"], "children": []},
            ]},
        ],
    }
    assert has_parent_domains(state) is True


def test_has_parent_domains_false_flat():
    state = {
        "domain_tree": [
            {"name": "domain1", "modules": ["A"], "children": []},
            {"name": "domain2", "modules": ["B"], "children": []},
        ],
    }
    assert has_parent_domains(state) is False


def test_has_parent_domains_empty():
    state = {"domain_tree": []}
    assert has_parent_domains(state) is False


@pytest.mark.asyncio
async def test_compose_parent_pages_flat_tree():
    """Flat tree should return empty pages."""
    state = {
        "domain_tree": [
            {"name": "domain1", "modules": ["A"], "children": []},
        ],
        "leaf_summaries": {"domain1": {"summary_text": "test", "module_count": 1}},
        "modules": {},
        "entity_roles": {},
    }
    result = await compose_parent_pages_node(state)
    assert result.get("pages", []) == []


@pytest.mark.asyncio
async def test_compose_parent_pages_nested(monkeypatch):
    """Nested tree should generate parent page via LLM."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"title": "Parent Overview", "content": "Overview of parent domain.", "executive_summary": "Parent summary.", "page_type": "domain_overview"}'

    state = {
        "domain_tree": [
            {"name": "parent_domain", "modules": [], "children": [
                {"name": "child1", "modules": ["ServiceA"], "children": []},
                {"name": "child2", "modules": ["ServiceB"], "children": []},
            ]},
        ],
        "leaf_summaries": {
            "child1": {"domain_name": "child1", "summary_text": "Service A handles X.", "module_count": 1, "key_entities": ["ServiceA"], "source": "llm"},
            "child2": {"domain_name": "child2", "summary_text": "Service B handles Y.", "module_count": 1, "key_entities": ["ServiceB"], "source": "llm"},
        },
        "modules": {},
        "entity_roles": {},
    }

    # This test will need the LLM to be injected via config
    # Implementation will handle this via LangGraph config["configurable"]["llm"]
    config = {"configurable": {"llm": mock_llm}}
    result = await compose_parent_pages_node(state, config)
    pages = result.get("pages", [])
    assert len(pages) >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_compose_parents.py -v`
Expected: FAIL — `compose_parent_pages_node` or `has_parent_domains` not found

- [ ] **Step 3: Implement has_parent_domains and compose_parent_pages_node**

In `wiki/pipeline_nodes.py`, add:

```python
def has_parent_domains(state: dict) -> bool:
    domain_tree = state.get("domain_tree", []) or []
    for domain in domain_tree:
        children = domain.get("children", []) or []
        if children:
            return True
    return False


def _collect_parent_domains_by_level(domain_tree: list[dict]) -> list[list[dict]]:
    """Collect parent domains grouped by tree depth, deepest first."""
    levels: list[list[dict]] = []

    def _traverse(nodes: list[dict], depth: int) -> None:
        while len(levels) <= depth:
            levels.append([])
        for node in nodes:
            children = node.get("children", []) or []
            if children:
                levels[depth].append(node)
                _traverse(children, depth + 1)

    _traverse(domain_tree, 0)
    levels.reverse()
    return [lvl for lvl in levels if lvl]


async def compose_parent_pages_node(state: dict, config: dict | None = None) -> dict:
    domain_tree = state.get("domain_tree", []) or []
    leaf_summaries = state.get("leaf_summaries", {}) or {}
    modules = state.get("modules", {}) or {}
    entity_roles = state.get("entity_roles", {}) or {}

    if not has_parent_domains({"domain_tree": domain_tree}):
        return {"pages": []}

    llm = None
    if config:
        configurable = config.get("configurable", {})
        llm = configurable.get("llm")

    if not llm:
        logger.warning("compose_parent_pages_node: no LLM available, skipping")
        return {"pages": []}

    parent_levels = _collect_parent_domains_by_level(domain_tree)
    all_parent_pages: list[dict] = []

    for level_parents in parent_levels:
        for parent_domain in level_parents:
            parent_name = parent_domain.get("name", "")
            children = parent_domain.get("children", []) or []
            child_names = [c.get("name", "") for c in children]

            child_summary_lines = []
            for cn in child_names:
                summary = leaf_summaries.get(cn, {})
                text = summary.get("summary_text", f"{cn} domain")
                child_summary_lines.append(f"- **{cn}**: {text}")

            child_summaries_text = "\n".join(child_summary_lines)

            from wiki.snippet_selector import select_key_snippets
            from wiki.token_budget import TokenBudgetCalculator

            all_child_modules = []
            for child in children:
                for mod_name in child.get("modules", []):
                    for _repo, mod_list in modules.items():
                        for m in mod_list:
                            if m.get("properties", {}).get("name") == mod_name:
                                all_child_modules.append(m)

            budget_calc = TokenBudgetCalculator()
            snippets = select_key_snippets(
                all_child_modules, entity_roles,
                budget_tokens=budget_calc.budget_for_snippets(len(all_child_modules))
            )
            snippet_lines = [s.format_for_prompt() for s in snippets]
            snippet_text = "\n".join(snippet_lines) if snippet_lines else "No code signatures available."

            from wiki.prompts import SYSTEM_WIKI_PARENT_OVERVIEW

            prompt = f"""Create a domain overview page for "{parent_name}" that synthesizes its sub-domains.

## Sub-domain Summaries
{child_summaries_text}

## Key Code Interfaces
{snippet_text}

Write a comprehensive overview as JSON with keys: "title", "content", "executive_summary", "page_type".
The content should explain how sub-domains relate, describe data flow, and reference key interfaces naturally.
executive_summary should be 150-300 chars capturing the domain's core purpose."""

            try:
                response = await llm.generate(prompt, system=SYSTEM_WIKI_PARENT_OVERVIEW)
                import json
                page_data = json.loads(response)
                page_dict = {
                    "path": f"wiki/{parent_name.lower().replace(' ', '_')}",
                    "title": page_data.get("title", parent_name),
                    "content": page_data.get("content", ""),
                    "page_type": "domain_overview",
                    "metadata": {
                        "executive_summary": page_data.get("executive_summary"),
                    },
                }
                all_parent_pages.append(page_dict)

                leaf_summaries[parent_name] = {
                    "domain_name": parent_name,
                    "summary_text": page_data.get("executive_summary", "")[:300],
                    "module_count": sum(len(c.get("modules", [])) for c in children),
                    "key_entities": child_names,
                    "source": "llm",
                }
            except Exception:
                logger.exception("Failed to compose parent page for %s", parent_name)

    return {"pages": all_parent_pages}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_compose_parents.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py tests/wiki/test_compose_parents.py
git commit -m "feat(wiki): add compose_parent_pages_node for hierarchical domain synthesis"
```

---

## Task 9: Pipeline Graph Update

**Files:**
- Modify: `wiki/pipeline_graph.py`

- [ ] **Step 1: Read current pipeline_graph.py to understand exact structure**

Read the file and identify all node additions and edge definitions.

- [ ] **Step 2: Add new nodes and edges**

Update `wiki/pipeline_graph.py`:

1. Import new node functions:
```python
from wiki.pipeline_nodes import (
    compose_leaf_pages_node,  # renamed
    summarize_leaves_node,     # new
    compose_parent_pages_node, # new
    has_parent_domains,        # new condition
)
```

2. Add new nodes:
```python
graph.add_node("summarize_leaves", summarize_leaves_node)
graph.add_node("compose_parent_pages", compose_parent_pages_node)
```

3. Update edges: After quality_gate's "no heal" path, route to `summarize_leaves` instead of `synthesize_overviews`. Add conditional edge from `summarize_leaves` to either `compose_parent_pages` or `synthesize_overviews`.

```python
# After summarize_leaves, check if parent domains exist
graph.add_conditional_edges(
    "summarize_leaves",
    lambda state: "compose_parent_pages" if has_parent_domains(state) else "synthesize_overviews",
)
graph.add_edge("compose_parent_pages", "synthesize_overviews")
```

- [ ] **Step 3: Update synthesize_overviews to use leaf_summaries**

In `wiki/pipeline_nodes.py`, modify `synthesize_overviews_node` to prefer `state["leaf_summaries"]` over the current `_summarize_domain_for_system_overview` approach when available.

- [ ] **Step 4: Run all tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/ -x -q --timeout=120`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_graph.py wiki/pipeline_nodes.py
git commit -m "feat(wiki): wire bottom-up nodes into pipeline graph with conditional routing"
```

---

## Task 10: Integration Tests

**Files:**
- Modify: `tests/wiki/test_pipeline_e2e.py` or create new integration test file

- [ ] **Step 1: Write integration test for flat tree (no parent compose)**

```python
@pytest.mark.asyncio
async def test_pipeline_flat_tree_skips_parent_compose():
    """Flat domain tree should skip compose_parent_pages and go directly to synthesize_overviews."""
    # Setup: flat domain tree with 2 leaf domains
    # Run pipeline
    # Assert: no domain_overview pages generated (only topic + system_overview)
    # Assert: leaf_summaries populated
    pass  # Actual implementation depends on existing test infrastructure
```

- [ ] **Step 2: Write integration test for nested tree**

```python
@pytest.mark.asyncio
async def test_pipeline_nested_tree_generates_parent_pages():
    """Nested domain tree should generate parent domain overview pages."""
    # Setup: nested domain tree with parent + 2 children
    # Run pipeline with mock LLM
    # Assert: domain_overview page generated for parent
    # Assert: system_overview uses leaf_summaries
    pass
```

- [ ] **Step 3: Write integration test for code snippet injection**

```python
@pytest.mark.asyncio
async def test_pipeline_code_snippets_in_prompt():
    """Verify code snippets are included in compose prompts."""
    # Setup: modules with methods and calls
    # Run pipeline with LLM spy
    # Assert: LLM prompt contains "Key Code Interfaces"
    pass
```

- [ ] **Step 4: Run all integration tests**

Run: `cd knowledge-base-service && python -m pytest tests/wiki/test_pipeline_e2e.py -v --timeout=120`
Expected: All tests pass

- [ ] **Step 5: Commit**

```bash
git add tests/wiki/
git commit -m "test(wiki): add integration tests for bottom-up generation pipeline"
```
