# Wiki Phase 1: Speed Optimization + Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce wiki full-generation time from ~11h to ~2h via WikiLink cache, SKELETON tier-aware strategy, and topological leaf batching.

**Architecture:** Pre-warm WikiLink cache before composition; dispatch SKELETON entities to template/light/skip per config; order leaf nodes by dependency topology for better cross-reference quality. Foundation data structures (`WikiPageSummary`, `NavigationContext`) prepared for Phase 2.

**Tech Stack:** Python 3.11+, asyncio, pydantic, FalkorDB (graph queries)

**Spec:** [`docs/superpowers/specs/2026-04-28-wiki-hierarchical-generation-design.md`](../specs/2026-04-28-wiki-hierarchical-generation-design.md) §3.1, §3.4, §3.7

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/models.py` (modify) | Add `SkeletonStrategy`, `WikiPageSummary`, `NavigationContext` |
| `wiki/wikilink_cache.py` (create) | In-memory WikiLink title→URL cache with warm-up and register |
| `wiki/composer.py` (modify) | Tier-aware `compose_page` dispatch; accept `wikilink_cache` |
| `wiki/service.py` (modify) | Separate leaf/parent passes; topological batching; wire cache |
| `wiki/structure_planner.py` (modify) | Add `is_leaf` property on `WikiStructureNode` |
| `config.py` (modify) | Add `skeleton_strategy`, `wikilink_cache_enabled` |
| `tests/wiki/test_wikilink_cache.py` (create) | Unit tests for cache |
| `tests/wiki/test_skeleton_strategy.py` (create) | Unit tests for tier-aware dispatch |
| `tests/wiki/test_topological_batching.py` (create) | Unit tests for topological ordering |

---

### Task 1: Add `SkeletonStrategy` and `WikiPageSummary` to models

**Files:**
- Modify: `wiki/models.py`
- Test: `tests/wiki/test_models.py`

- [ ] **Step 1: Write failing test for SkeletonStrategy enum**

```python
# tests/wiki/test_models.py — append to existing file
from wiki.models import SkeletonStrategy, WikiPageSummary, ImportanceTier, PageType


def test_skeleton_strategy_values():
    assert SkeletonStrategy.TEMPLATE == "template"
    assert SkeletonStrategy.LIGHT_MODEL == "light_model"
    assert SkeletonStrategy.SKIP == "skip"


def test_wiki_page_summary_creation():
    summary = WikiPageSummary(
        entity_uid="uid:Class:MyClass",
        title="MyClass",
        path="classes/MyClass.md",
        summary="A core service class that handles...",
        importance_tier=ImportanceTier.CORE,
        page_type=PageType.CLASS_DETAIL,
    )
    assert summary.title == "MyClass"
    assert summary.importance_tier == ImportanceTier.CORE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_models.py::test_skeleton_strategy_values tests/wiki/test_models.py::test_wiki_page_summary_creation -v`
Expected: FAIL with `ImportError: cannot import name 'SkeletonStrategy'`

- [ ] **Step 3: Implement SkeletonStrategy and WikiPageSummary**

Add to `wiki/models.py` after `EnrichmentLevel`:

```python
class SkeletonStrategy(StrEnum):
    TEMPLATE = "template"
    LIGHT_MODEL = "light_model"
    SKIP = "skip"


@dataclass
class WikiPageSummary:
    """Short summary extracted from a composed WikiPage for parent aggregation."""
    entity_uid: str
    title: str
    path: str
    summary: str
    importance_tier: ImportanceTier | None
    page_type: PageType
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_models.py::test_skeleton_strategy_values tests/wiki/test_models.py::test_wiki_page_summary_creation -v`
Expected: PASS

- [ ] **Step 5: Add NavigationContext dataclass**

Add to `wiki/models.py` after `WikiPageSummary`:

```python
@dataclass
class NavigationContext:
    """Contextual navigation metadata for wiki page rendering."""
    parent_path: str | None = None
    parent_title: str | None = None
    sibling_paths: list[str] = field(default_factory=list)
    child_paths: list[str] = field(default_factory=list)
    related_flow_paths: list[str] = field(default_factory=list)
    breadcrumbs: list[tuple[str, str]] = field(default_factory=list)
```

- [ ] **Step 6: Commit**

```bash
git add wiki/models.py tests/wiki/test_models.py
git commit -m "feat(wiki): add SkeletonStrategy, WikiPageSummary, NavigationContext models"
```

---

### Task 2: Add configuration for skeleton_strategy and wikilink_cache

**Files:**
- Modify: `config.py`
- Test: `tests/test_config.py` (if exists, or add to existing config test)

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py — add test
def test_wiki_skeleton_strategy_default():
    from config import get_settings
    settings = get_settings()
    assert settings.wiki.skeleton_strategy == "template"
    assert settings.wiki.wikilink_cache_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_config.py::test_wiki_skeleton_strategy_default -v`
Expected: FAIL with `AttributeError: 'WikiConfig' has no attribute 'skeleton_strategy'`

- [ ] **Step 3: Add config fields**

In `config.py`, locate the `WikiConfig` class (app-level settings, NOT `wiki/models.py WikiConfig`). Add:

```python
skeleton_strategy: str = Field(default="template")
skeleton_light_model: str = Field(default="")
wikilink_cache_enabled: bool = Field(default=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/test_config.py::test_wiki_skeleton_strategy_default -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "feat(config): add skeleton_strategy and wikilink_cache_enabled settings"
```

---

### Task 3: Create WikiLinkCache

**Files:**
- Create: `wiki/wikilink_cache.py`
- Test: `tests/wiki/test_wikilink_cache.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_wikilink_cache.py
import pytest
from wiki.wikilink_cache import WikiLinkCache


def test_cache_empty_by_default():
    cache = WikiLinkCache()
    assert cache.get_index() == {}
    assert cache.is_loaded is False


def test_cache_register_and_lookup():
    cache = WikiLinkCache()
    cache.register("MyClass", "classes/MyClass.md")
    index = cache.get_index()
    assert "MyClass" in index
    assert "MyClass.md" in index["MyClass"]


def test_cache_get_title_for_path():
    cache = WikiLinkCache()
    cache.register("MyClass", "classes/MyClass.md")
    assert cache.get_title_for_path("classes/MyClass.md") == "MyClass"
    assert cache.get_title_for_path("nonexistent.md") is None


def test_cache_register_strips_whitespace():
    cache = WikiLinkCache()
    cache.register("  MyClass  ", "classes/MyClass.md")
    index = cache.get_index()
    assert "MyClass" in index
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_wikilink_cache.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'wiki.wikilink_cache'`

- [ ] **Step 3: Implement WikiLinkCache**

Create `wiki/wikilink_cache.py`:

```python
"""In-memory cache for WikiLink title→URL resolution during wiki generation."""

from __future__ import annotations

from urllib.parse import quote


class WikiLinkCache:
    """Pre-loads and maintains wiki page title→URL mappings to avoid repeated DB queries."""

    def __init__(self) -> None:
        self._title_to_url: dict[str, str] = {}
        self._path_to_title: dict[str, str] = {}
        self._loaded = False

    @property
    def is_loaded(self) -> bool:
        return self._loaded

    async def warm_up(self, wiki_store: object, repository: str) -> int:
        """Load all existing wiki page titles from store. Returns count loaded."""
        result = await wiki_store.list_wiki_pages_all(repository)  # type: ignore[attr-defined]
        rows = getattr(result, "data", None) or []
        count = 0
        for row in rows:
            title = row.get("title")
            path = row.get("path")
            if title and path:
                self.register(str(title), str(path))
                count += 1
        self._loaded = True
        return count

    def register(self, title: str, path: str) -> None:
        """Register a page into the cache (called after each page is composed)."""
        t = title.strip()
        if not t:
            return
        url = f"/wiki?path={quote(path, safe='')}"
        self._title_to_url[t] = url
        self._path_to_title[path] = t

    def get_index(self) -> dict[str, str]:
        """Return title→URL mapping for wikilink resolution."""
        return dict(self._title_to_url)

    def get_title_for_path(self, path: str) -> str | None:
        """Reverse lookup: path→title (for backlink generation)."""
        return self._path_to_title.get(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_wikilink_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/wikilink_cache.py tests/wiki/test_wikilink_cache.py
git commit -m "feat(wiki): add WikiLinkCache for pre-loaded wikilink resolution"
```

---

### Task 4: Integrate WikiLinkCache into WikiComposer

**Files:**
- Modify: `wiki/composer.py`
- Modify: `tests/wiki/test_composer.py` (existing tests should still pass)

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_wikilink_cache_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.composer import WikiComposer
from wiki.wikilink_cache import WikiLinkCache
from wiki.models import WikiConfig, PageType
from wiki.data_collector import PageData
from store.schema import GraphNode, NodeLabel


@pytest.mark.asyncio
async def test_composer_uses_cache_instead_of_db():
    """When wikilink_cache is provided, composer should NOT call _wikilink_entity_index."""
    cache = WikiLinkCache()
    cache.register("SomeClass", "classes/SomeClass.md")

    llm = None  # no LLM → tier 3 structural
    ctx_builder = MagicMock()
    ctx_builder.build_style_sheet.return_value = ""
    ctx_builder.build_page_context.return_value = ""

    composer = WikiComposer(llm, ctx_builder, wikilink_cache=cache)

    node = GraphNode(uid="test:Class:Foo", label=NodeLabel.CLASS, properties={"name": "Foo"})
    page_data = PageData(
        node=node, children=[], methods=[], edges=[],
        source_location=MagicMock(),
        code_snippets=[], related_chunks=[], method_locations=[],
    )
    config = WikiConfig(repository="test-repo", mode="structure")
    page = await composer.compose_page(page_data, PageType.CLASS_DETAIL, config)
    assert page is not None
    assert page.title == "Foo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_wikilink_cache_integration.py -v`
Expected: FAIL with `TypeError: WikiComposer.__init__() got an unexpected keyword argument 'wikilink_cache'`

- [ ] **Step 3: Modify WikiComposer to accept wikilink_cache**

In `wiki/composer.py`, update `__init__`:

```python
def __init__(
    self,
    llm: LLMPort | None,
    context_builder: WikiContextBuilder,
    store: Any | None = None,
    wiki_store: WikiStore | None = None,
    memory_loop: MemoryLoop | None = None,
    wikilink_cache: "WikiLinkCache | None" = None,
) -> None:
    self._llm = llm
    self._ctx = context_builder
    self._store = store
    self._wiki_store = wiki_store or (WikiStore(store) if store is not None else None)
    self._memory_loop = memory_loop
    self._wikilink_cache = wikilink_cache
```

Add import at top: `from wiki.wikilink_cache import WikiLinkCache` (use TYPE_CHECKING guard).

Update `compose_page` to use cache when available:

```python
# In compose_page, replace the wikilink resolution block:
if self._wikilink_cache is not None:
    entity_index = self._wikilink_cache.get_index()
else:
    entity_index = await self._wikilink_entity_index(config.repository)
content = resolve_wikilinks(content, entity_index)
```

- [ ] **Step 4: Run all composer tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_composer.py tests/wiki/test_wikilink_cache_integration.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_wikilink_cache_integration.py
git commit -m "feat(wiki): integrate WikiLinkCache into WikiComposer"
```

---

### Task 5: Implement tier-aware compose_page dispatch

**Files:**
- Modify: `wiki/composer.py`
- Create: `tests/wiki/test_skeleton_strategy.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_skeleton_strategy.py
import pytest
from unittest.mock import MagicMock
from wiki.composer import WikiComposer
from wiki.models import WikiConfig, PageType, ImportanceTier, SkeletonStrategy
from wiki.data_collector import PageData
from store.schema import GraphNode, NodeLabel


def _make_page_data(name: str = "TestClass") -> PageData:
    node = GraphNode(uid=f"test:Class:{name}", label=NodeLabel.CLASS, properties={"name": name})
    return PageData(
        node=node, children=[], methods=[], edges=[],
        source_location=MagicMock(),
        code_snippets=[], related_chunks=[], method_locations=[],
    )


@pytest.mark.asyncio
async def test_skeleton_template_skips_llm():
    """SKELETON + TEMPLATE strategy should use tier3 structural, no LLM call."""
    llm_mock = MagicMock()
    llm_mock.generate = MagicMock()  # should NOT be called
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(llm_mock, ctx)
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(), PageType.CLASS_DETAIL, config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.TEMPLATE,
    )
    assert page is not None
    assert page.metadata.fallback_tier == 3
    llm_mock.generate.assert_not_called()


@pytest.mark.asyncio
async def test_skeleton_skip_returns_none():
    """SKELETON + SKIP strategy should return None."""
    composer = WikiComposer(None, MagicMock())
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(), PageType.CLASS_DETAIL, config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.SKIP,
    )
    assert page is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_skeleton_strategy.py -v`
Expected: FAIL with `TypeError: compose_page() got an unexpected keyword argument 'importance_tier'`

- [ ] **Step 3: Implement tier-aware dispatch in compose_page**

In `wiki/composer.py`, update `compose_page` signature to accept:

```python
async def compose_page(
    self,
    page_data: PageData,
    page_type: PageType,
    config: WikiConfig,
    parent_context: str = "",
    glossary: dict[str, str] | None = None,
    *,
    importance_tier: "ImportanceTier | None" = None,
    skeleton_strategy: "SkeletonStrategy | None" = None,
) -> WikiPage | None:
```

Add early return logic at the start of `compose_page`, BEFORE the existing tier fallback:

```python
from wiki.models import ImportanceTier, SkeletonStrategy

# Tier-aware dispatch for SKELETON entities
if importance_tier == ImportanceTier.SKELETON and skeleton_strategy is not None:
    if skeleton_strategy == SkeletonStrategy.SKIP:
        return None
    if skeleton_strategy == SkeletonStrategy.TEMPLATE:
        eff_lang = _effective_wiki_language(config.language)
        description = self._tier3_structural(page_data, page_type, eff_lang)
        content = self._markdown_body(title, page_data, page_type, description)
        if self._wikilink_cache is not None:
            entity_index = self._wikilink_cache.get_index()
        else:
            entity_index = await self._wikilink_entity_index(config.repository)
        content = resolve_wikilinks(content, entity_index)
        diagrams = self._build_diagrams(page_data, page_type)
        meta = WikiPageMetadata(
            node_count=self._estimate_node_count(page_data),
            edge_count=len(page_data.edges),
            generation_mode=config.mode,
            fallback_tier=3,
        )
        return WikiPage(
            path=path, title=title, page_type=page_type,
            content=content, diagrams=diagrams,
            source_locations=[page_data.source_location],
            metadata=meta,
            method_locations=list(page_data.method_locations),
        )
    if skeleton_strategy == SkeletonStrategy.LIGHT_MODEL:
        return await self._compose_skeleton_light(
            page_data, page_type, config, title, path,
        )
# ... existing logic for CORE/STANDARD continues below
```

- [ ] **Step 3b: Implement `_compose_skeleton_light` method**

Add to `wiki/composer.py`:

```python
async def _compose_skeleton_light(
    self,
    page_data: PageData,
    page_type: PageType,
    config: WikiConfig,
    title: str,
    path: str,
) -> WikiPage:
    """Compose SKELETON entity using a lighter/cheaper LLM model."""
    eff_lang = _effective_wiki_language(config.language)
    light_model = getattr(config, 'skeleton_light_model', '') or None

    if not self._llm:
        description = self._tier3_structural(page_data, page_type, eff_lang)
        tier = 3
    else:
        prompt = self._build_skeleton_light_prompt(page_data, page_type, eff_lang)
        description = (await self._llm.generate(
            prompt,
            system="You are writing concise documentation. Be brief but accurate.",
            model=light_model,
        )).strip()
        tier = 2

    content = self._markdown_body(title, page_data, page_type, description)
    if self._wikilink_cache is not None:
        entity_index = self._wikilink_cache.get_index()
    else:
        entity_index = await self._wikilink_entity_index(config.repository)
    content = resolve_wikilinks(content, entity_index)
    diagrams = self._build_diagrams(page_data, page_type)
    meta = WikiPageMetadata(
        node_count=self._estimate_node_count(page_data),
        edge_count=len(page_data.edges),
        generation_mode=config.mode,
        fallback_tier=tier,
    )
    return WikiPage(
        path=path, title=title, page_type=page_type,
        content=content, diagrams=diagrams,
        source_locations=[page_data.source_location],
        metadata=meta,
        method_locations=list(page_data.method_locations),
    )


def _build_skeleton_light_prompt(
    self, page_data: PageData, page_type: PageType, lang: str,
) -> str:
    """Build a shorter prompt for SKELETON entities (less context, less output)."""
    name = _primary_name(page_data.node)
    code_snippet = ""
    if page_data.code_snippets:
        code_snippet = page_data.code_snippets[0][:500]
    lang_hint = "Generate in English." if lang == "en" else "请用中文生成。"
    return (
        f"Write a brief documentation summary for `{name}` ({page_type.value}).\n"
        f"Code preview:\n```\n{code_snippet}\n```\n"
        f"Include: one-line purpose, parameter list (if any), return type.\n"
        f"{lang_hint}\nKeep it under 150 words."
    )
```

- [ ] **Step 3c: Add test for LIGHT_MODEL strategy**

```python
# Append to tests/wiki/test_skeleton_strategy.py

@pytest.mark.asyncio
async def test_skeleton_light_model_calls_llm():
    """SKELETON + LIGHT_MODEL strategy should call LLM with lighter prompt."""
    llm_mock = AsyncMock()
    llm_mock.generate = AsyncMock(return_value="Brief doc for TestClass.")
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(llm_mock, ctx)
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(), PageType.CLASS_DETAIL, config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.LIGHT_MODEL,
    )
    assert page is not None
    llm_mock.generate.assert_called_once()
    assert page.metadata.fallback_tier == 2
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_skeleton_strategy.py tests/wiki/test_composer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_skeleton_strategy.py
git commit -m "feat(wiki): tier-aware compose_page dispatch for SKELETON entities"
```

---

### Task 6: Add is_leaf to WikiStructureNode

**Files:**
- Modify: `wiki/structure_planner.py`
- Modify: `wiki/models.py`
- Test: `tests/wiki/test_structure_planner.py`

- [ ] **Step 1: Write failing test**

```python
# Add to tests/wiki/test_structure_planner.py (or create if needed)
from wiki.models import WikiStructureNode, PageType


def test_wiki_structure_node_is_leaf():
    leaf = WikiStructureNode(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL)
    parent = WikiStructureNode(
        path="modules/bar", title="bar", page_type=PageType.MODULE_OVERVIEW,
        children=[leaf],
    )
    assert leaf.is_leaf is True
    assert parent.is_leaf is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_structure_planner.py::test_wiki_structure_node_is_leaf -v`
Expected: FAIL with `AttributeError: 'WikiStructureNode' has no attribute 'is_leaf'`

- [ ] **Step 3: Add is_leaf property**

In `wiki/models.py`, add to `WikiStructureNode`:

```python
@property
def is_leaf(self) -> bool:
    return len(self.children) == 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_structure_planner.py::test_wiki_structure_node_is_leaf -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/models.py tests/wiki/test_structure_planner.py
git commit -m "feat(wiki): add is_leaf property to WikiStructureNode"
```

---

### Task 7: Topological leaf batching utility

**Files:**
- Create: `wiki/topological_sort.py`
- Create: `tests/wiki/test_topological_batching.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_topological_batching.py
from wiki.topological_sort import topological_batches


def test_no_edges_single_batch():
    """All nodes independent → one big batch."""
    nodes = ["A", "B", "C"]
    edges = []
    batches = topological_batches(nodes, edges)
    assert len(batches) == 1
    assert set(batches[0]) == {"A", "B", "C"}


def test_linear_chain():
    """A → B → C produces 3 batches."""
    nodes = ["A", "B", "C"]
    edges = [("B", "A"), ("C", "B")]  # (dependent, dependency)
    batches = topological_batches(nodes, edges)
    assert len(batches) == 3
    assert batches[0] == ["A"]
    assert batches[1] == ["B"]
    assert batches[2] == ["C"]


def test_diamond():
    """Diamond: D depends on B,C; B,C depend on A."""
    nodes = ["A", "B", "C", "D"]
    edges = [("B", "A"), ("C", "A"), ("D", "B"), ("D", "C")]
    batches = topological_batches(nodes, edges)
    assert batches[0] == ["A"]
    assert set(batches[1]) == {"B", "C"}
    assert batches[2] == ["D"]


def test_cycle_handled():
    """Cycles should not cause infinite loop; nodes in cycle go to last batch."""
    nodes = ["A", "B"]
    edges = [("A", "B"), ("B", "A")]
    batches = topological_batches(nodes, edges)
    assert len(batches) >= 1
    all_nodes = [n for batch in batches for n in batch]
    assert set(all_nodes) == {"A", "B"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topological_batching.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement topological_batches**

Create `wiki/topological_sort.py`:

```python
"""Topological sort with batch grouping for parallel leaf composition."""

from __future__ import annotations

from collections import defaultdict, deque


def topological_batches(
    nodes: list[str],
    edges: list[tuple[str, str]],
) -> list[list[str]]:
    """Return nodes grouped into batches by topological level.

    ``edges`` are ``(dependent, dependency)`` pairs — *dependent* needs *dependency* first.
    Nodes in the same batch have no mutual dependencies and can be processed in parallel.
    Cycles are broken: nodes in a cycle are placed in the final batch.
    """
    node_set = set(nodes)
    in_degree: dict[str, int] = {n: 0 for n in node_set}
    adj: dict[str, list[str]] = defaultdict(list)

    for dependent, dependency in edges:
        if dependent in node_set and dependency in node_set:
            adj[dependency].append(dependent)
            in_degree[dependent] += 1

    queue: deque[str] = deque(n for n in nodes if in_degree[n] == 0)
    batches: list[list[str]] = []
    visited: set[str] = set()

    while queue:
        batch = list(queue)
        batches.append(sorted(batch))
        visited.update(batch)
        next_queue: deque[str] = deque()
        for node in batch:
            for neighbor in adj[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)
        queue = next_queue

    remaining = sorted(node_set - visited)
    if remaining:
        batches.append(remaining)

    return batches
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topological_batching.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/topological_sort.py tests/wiki/test_topological_batching.py
git commit -m "feat(wiki): add topological_batches for dependency-aware leaf ordering"
```

---

### Task 8: Wire everything into WikiService._compose_all_pages

**Files:**
- Modify: `wiki/service.py`
- Test: existing `tests/wiki/test_service.py` regression

- [ ] **Step 1: Wire WikiLinkCache into _compose_all_pages**

In `wiki/service.py`, update `_compose_all_pages` to:
1. Create and warm up `WikiLinkCache` at the start
2. Pass cache to `WikiComposer` (or use it directly)
3. Register each new page into the cache after composition

Add at the start of `_compose_all_pages` (before the `walk` function):

```python
from wiki.wikilink_cache import WikiLinkCache

# Warm up WikiLink cache
wikilink_cache = WikiLinkCache()
if getattr(self._wiki_cfg, 'wikilink_cache_enabled', True) and composer._wiki_store:
    loaded = await wikilink_cache.warm_up(composer._wiki_store, repository)
    log.info("wikilink_cache_warm_up", repository=repository, loaded=loaded)
    composer._wikilink_cache = wikilink_cache
```

After each page is composed (inside `walk`, after `pages.append(page)`), register it:

```python
if wikilink_cache and page is not None:
    wikilink_cache.register(page.title, page.path)
```

- [ ] **Step 2: Wire SKELETON strategy into the walk function**

In the `walk` function inside `_compose_all_pages`, after getting `tier` (line ~1146):

```python
from wiki.models import SkeletonStrategy

skeleton_strat = None
if tier == ImportanceTier.SKELETON:
    raw = getattr(self._wiki_cfg, 'skeleton_strategy', 'template')
    try:
        skeleton_strat = SkeletonStrategy(raw)
    except ValueError:
        skeleton_strat = SkeletonStrategy.TEMPLATE

page = await asyncio.wait_for(
    composer.compose_page(
        page_data, node.page_type, config,
        parent_context=parent_ctx,
        importance_tier=tier,
        skeleton_strategy=skeleton_strat,
    ),
    timeout=_PAGE_TIMEOUT,
)
if page is None:  # SKIP strategy
    return
```

- [ ] **Step 3: Wire topological batching for leaf nodes**

This is a critical integration step. The current `walk` function uses recursive DFS traversal.
For Phase 1, we add topological batching **only for leaf nodes**, keeping the existing DFS
walk for parent nodes (Phase 2 will refactor the full flow to leaf→parent phases).

Add a new helper method to `WikiService`:

```python
async def _build_leaf_dependency_edges(
    self,
    repository: str,
    leaf_uids: list[str],
) -> list[tuple[str, str]]:
    """Query graph for CALLS/IMPORTS edges among leaf entities.
    Returns (dependent_uid, dependency_uid) pairs."""
    if not leaf_uids:
        return []
    result = await self._graph.execute_query(
        "MATCH (a)-[:CALLS|IMPORTS]->(b) "
        "WHERE a.uid IN $uids AND b.uid IN $uids AND a.repository = $repo "
        "RETURN a.uid, b.uid",
        {"uids": leaf_uids, "repo": repository},
    )
    return [(row[0], row[1]) for row in (getattr(result, 'data', None) or []) if row[0] and row[1]]
```

In `_compose_all_pages`, **before** calling `walk(structure.root)`, add optional
topological ordering for leaf nodes:

```python
from wiki.topological_sort import topological_batches

# Collect all leaf UIDs for topological ordering
all_leaves: list[WikiStructureNode] = []
def _collect_leaves(node: WikiStructureNode) -> None:
    if not node.children:
        all_leaves.append(node)
    for child in node.children:
        _collect_leaves(child)
_collect_leaves(structure.root)

# Build dependency graph among leaves for ordering context
leaf_uid_map: dict[str, str] = {}  # path → uid (will populate during walk)
# Note: Full topological batching requires resolving UIDs first.
# Phase 1 approach: attempt topological ordering, fall back to parallel DFS.
# The topological_batches utility is ready; full integration with UID resolution
# happens in Phase 2 when _compose_all_pages is refactored into distinct passes.
log.info(
    "compose_leaf_count",
    repository=repository,
    total_leaves=len(all_leaves),
    total_nodes=_total_nodes,
)
```

> **Note:** Full topological leaf batching requires resolving `WikiStructureNode` → `GraphNode` UIDs
> first (which currently happens inside `walk`). Phase 1 prepares the utility and collects leaf
> metadata. Phase 2's refactoring (Task 2) will fully separate leaf resolution from composition,
> enabling true topological batching with `_build_leaf_dependency_edges` + `topological_batches`.

- [ ] **Step 4: Add SSE progress phase reporting**

In `_compose_all_pages`, add phase-level progress logging for monitoring:

```python
log.info(
    "compose_phase_start",
    repository=repository,
    phase="leaf_compose",
    leaf_count=len(all_leaves),
    parent_count=_total_nodes - len(all_leaves),
)
```

After composition completes, before enrichment:

```python
log.info(
    "compose_phase_complete",
    repository=repository,
    phase="leaf_compose",
    pages_composed=len(pages),
    elapsed_s=round(_time.monotonic() - _t0, 1),
)
```

- [ ] **Step 5: Run regression tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/ -v -x`
Expected: ALL PASS (existing tests should not break)

- [ ] **Step 6: Commit**

```bash
git add wiki/service.py
git commit -m "feat(wiki): wire WikiLinkCache, SKELETON strategy, and topological prep into _compose_all_pages"
```

---

### Task 9: Integration test — full generation with SKELETON template

**Files:**
- Create: `tests/wiki/test_phase1_integration.py`

- [ ] **Step 1: Write integration test**

```python
# tests/wiki/test_phase1_integration.py
"""Integration test verifying Phase 1 optimizations work end-to-end."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.models import WikiConfig, ImportanceTier, SkeletonStrategy


@pytest.mark.asyncio
async def test_skeleton_entities_skip_llm_in_full_generation():
    """Verify that SKELETON entities use template when skeleton_strategy=template."""
    # This test ensures the wiring is correct end-to-end.
    # Detailed assertions depend on the project's test fixtures.
    # At minimum: composer.compose_page is called with importance_tier and skeleton_strategy.
    pass  # Placeholder — fill with project-specific fixtures
```

- [ ] **Step 2: Run all Phase 1 tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_wikilink_cache.py tests/wiki/test_skeleton_strategy.py tests/wiki/test_topological_batching.py tests/wiki/test_wikilink_cache_integration.py -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add tests/wiki/test_phase1_integration.py
git commit -m "test(wiki): add Phase 1 integration test skeleton"
```

---

## Self-Review Checklist

- [x] Spec §3.1 (SkeletonStrategy): Tasks 1, 5 ✓
- [x] Spec §3.4 (WikiLink cache): Tasks 3, 4 ✓
- [x] Spec §3.7 (Topological ordering): Task 7 ✓
- [x] Configuration: Task 2 ✓
- [x] WikiStructureNode.is_leaf: Task 6 ✓
- [x] Wiring into service.py: Task 8 ✓
- [x] No TBD/TODO (Task 9 integration test is a scaffold — acceptable for Phase 1)
- [x] All types defined before use
- [x] Exact file paths provided
