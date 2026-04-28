# Wiki Phase 2: Hierarchical Composition + Business Flows + Navigation + Delegation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement bottom-up parent aggregation from child summaries, business flow aggregation pages from community detection, bidirectional backlinks, contextual navigation, cross-view links, and dynamic delegation for large modules.

**Architecture:** Phase 1 produces leaf pages with `WikiPageSummary`. Phase 2 uses these summaries to compose parent module pages (bottom-up), then aggregates communities into business flow pages. Backlinks are generated from graph edges. Navigation metadata is populated from the structure tree. Dynamic delegation splits oversized modules into sub-groups.

**Tech Stack:** Python 3.11+, asyncio, FalkorDB (graph queries for backlinks/community), pydantic

**Spec:** [`docs/superpowers/specs/2026-04-28-wiki-hierarchical-generation-design.md`](../specs/2026-04-28-wiki-hierarchical-generation-design.md) §3.2, §3.3, §3.5, §3.6, §3.7, §3.8

**Depends on:** Phase 1 completed (WikiPageSummary, WikiLinkCache, SkeletonStrategy, topological batching)

---

## File Structure

| File | Responsibility |
|------|---------------|
| `wiki/composer.py` (modify) | Add `compose_parent_page()` method |
| `wiki/service.py` (modify) | Refactor `_compose_all_pages` into leaf→parent→root→flow passes |
| `wiki/business_flow_composer.py` (create) | Business flow page composer from communities |
| `wiki/backlink_builder.py` (create) | Bidirectional backlink generation |
| `wiki/delegation.py` (create) | Dynamic delegation criteria + child grouping |
| `wiki/community_context.py` (modify) | Add structured community data access |
| `store/falkordb_store.py` (modify) | Add `find_referrers()` query |
| `config.py` (modify) | Add delegation_* and business_flow_* config |

---

### Task 1: Implement `compose_parent_page` in WikiComposer

**Files:**
- Modify: `wiki/composer.py`
- Create: `tests/wiki/test_compose_parent.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_compose_parent.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.composer import WikiComposer
from wiki.models import WikiConfig, PageType, WikiPageSummary, ImportanceTier
from wiki.data_collector import PageData
from store.schema import GraphNode, NodeLabel


@pytest.mark.asyncio
async def test_compose_parent_uses_child_summaries():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="Module overview based on children.")
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(llm, ctx)
    node = GraphNode(uid="test:Module:api", label=NodeLabel.MODULE, properties={"name": "api", "path": "src/api"})
    page_data = PageData(
        node=node, children=[], methods=[], edges=[],
        source_location=MagicMock(), code_snippets=[], related_chunks=[], method_locations=[],
    )
    config = WikiConfig(repository="test", mode="full")
    child_summaries = [
        WikiPageSummary("uid:Class:A", "ClassA", "classes/A.md", "Handles authentication", ImportanceTier.CORE, PageType.CLASS_DETAIL),
        WikiPageSummary("uid:Class:B", "ClassB", "classes/B.md", "Manages sessions", ImportanceTier.STANDARD, PageType.CLASS_DETAIL),
    ]

    page = await composer.compose_parent_page(page_data, PageType.MODULE_OVERVIEW, config, child_summaries)
    assert page is not None
    assert page.page_type == PageType.MODULE_OVERVIEW
    llm.generate.assert_called_once()
    prompt_arg = llm.generate.call_args[0][0]
    assert "ClassA" in prompt_arg
    assert "ClassB" in prompt_arg
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_compose_parent.py -v`
Expected: FAIL — `compose_parent_page` not defined

- [ ] **Step 3: Implement `compose_parent_page`**

Add to `wiki/composer.py`:

```python
_PARENT_SYSTEM_PROMPT = (
    "You are a senior engineer writing a module overview. "
    "Synthesize the provided child component summaries into a cohesive description. "
    "Focus on how components work together, the module's overall purpose, and key design patterns. "
    "Use clear section headings (##). Output Markdown."
)

async def compose_parent_page(
    self,
    page_data: PageData,
    page_type: PageType,
    config: WikiConfig,
    child_summaries: list["WikiPageSummary"],
) -> WikiPage:
    """Compose a parent module page using child summaries instead of raw code."""
    title = _primary_name(page_data.node)
    path = _wiki_path(page_data.node, page_type)
    eff_lang = _effective_wiki_language(config.language)

    if not self._llm or not child_summaries:
        description = self._tier3_structural(page_data, page_type, eff_lang)
        tier = 3
    else:
        children_context = "\n".join(
            f"- **{s.title}** ({s.importance_tier.value if s.importance_tier else 'unknown'}): {s.summary}"
            for s in child_summaries
        )
        lang_directive = "Generate documentation in English." if eff_lang == "en" else "请用中文生成文档。"
        prompt = (
            f"## Module: {title}\n\n"
            f"### Child Components ({len(child_summaries)} total):\n{children_context}\n\n"
            f"## Task\n{lang_directive}\n\n"
            "Write a module overview that:\n"
            "1. Describes the module's overall purpose and responsibility\n"
            "2. Explains how the child components work together\n"
            "3. Identifies key design patterns and architectural decisions\n"
            "4. Notes important entry points and external interfaces\n"
        )
        description = (await self._llm.generate(prompt, system=_PARENT_SYSTEM_PROMPT)).strip()
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
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_compose_parent.py tests/wiki/test_composer.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/composer.py tests/wiki/test_compose_parent.py
git commit -m "feat(wiki): add compose_parent_page for bottom-up module synthesis"
```

---

### Task 2: Refactor _compose_all_pages into leaf→parent phases

**Files:**
- Modify: `wiki/service.py`
- Create: `tests/wiki/test_compose_phases.py`

This is the **core refactoring** of the entire architecture. The existing `_compose_all_pages` uses
recursive DFS traversal (`walk` → `walk_children_parallel`) which processes nodes in tree order
without distinguishing leaves from parents. We refactor into two distinct passes.

- [ ] **Step 1: Write failing test for extract_summary**

```python
# tests/wiki/test_compose_phases.py
import pytest
from wiki.service import _extract_summary
from wiki.models import WikiPage, WikiPageMetadata, PageType


def test_extract_summary_from_overview_section():
    page = WikiPage(
        path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL,
        content="# Foo\n\n## Overview\n\nFoo handles authentication and session management.\n\n## Methods\n...",
        diagrams=[], source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    summary = _extract_summary(page, entity_uid="uid:Class:Foo")
    assert summary.title == "Foo"
    assert summary.entity_uid == "uid:Class:Foo"
    assert "authentication" in summary.summary
    assert len(summary.summary) <= 200


def test_extract_summary_no_overview():
    page = WikiPage(
        path="fn/bar.md", title="bar", page_type=PageType.API_REFERENCE,
        content="# bar\n\nA utility function that processes input data.\n\nDetails...",
        diagrams=[], source_locations=[],
        metadata=WikiPageMetadata(0, 0),
    )
    summary = _extract_summary(page, entity_uid="uid:Fn:bar")
    assert "utility" in summary.summary
```

- [ ] **Step 2: Extract helper: `_extract_summary` from WikiPage**

Add as a module-level function in `wiki/service.py`:

```python
def _extract_summary(page: WikiPage, entity_uid: str = "") -> WikiPageSummary:
    """Extract a short summary from a composed WikiPage for parent aggregation."""
    content = page.content or ""
    overview_start = content.find("## Overview")
    if overview_start >= 0:
        after_heading = content[overview_start + len("## Overview"):].strip()
        next_heading = after_heading.find("\n## ")
        if next_heading > 0:
            summary_text = after_heading[:next_heading].strip()[:200]
        else:
            summary_text = after_heading[:200]
    else:
        lines = content.split("\n")
        non_heading = [l for l in lines if l.strip() and not l.startswith("#")]
        summary_text = " ".join(non_heading)[:200]
    summary_text = summary_text.replace("\n", " ").strip()
    return WikiPageSummary(
        entity_uid=entity_uid,
        title=page.title,
        path=page.path,
        summary=summary_text,
        importance_tier=getattr(page, '_importance_tier', None),
        page_type=page.page_type,
    )
```

- [ ] **Step 3: Implement `_collect_nodes_by_depth` helper**

This function partitions the structure tree into leaf and parent nodes,
and sorts parents by depth (deepest first = bottom-up order):

```python
def _collect_nodes_by_depth(
    root: WikiStructureNode,
) -> tuple[list[WikiStructureNode], list[tuple[int, WikiStructureNode]]]:
    """Partition tree into (leaves, [(depth, parent_node)]) with parents sorted deepest-first."""
    leaves: list[WikiStructureNode] = []
    parents: list[tuple[int, WikiStructureNode]] = []

    def _visit(node: WikiStructureNode, depth: int) -> None:
        if node.page_type == PageType.REPO_OVERVIEW:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)
            return
        if not node.children:
            leaves.append(node)
        else:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)

    _visit(root, 0)
    parents.sort(key=lambda x: -x[0])  # deepest first
    return leaves, parents
```

- [ ] **Step 4: Refactor `_compose_all_pages` into two-pass architecture**

Replace the existing `walk`/`walk_children_parallel` with:

```python
async def _compose_all_pages(self, repository, structure, config, composer,
                             importance_tiers=None, llm_provider=None, *,
                             community_markdown="", token_budget_multiplier=1.0):
    import time as _time
    pages: list[WikiPage] = []
    degraded = False
    tiers = importance_tiers or {}
    summary_index: dict[str, WikiPageSummary] = {}
    _t0 = _time.monotonic()
    _PAGE_TIMEOUT = 120

    # -- WikiLink cache warm-up (Phase 1) --
    wikilink_cache = WikiLinkCache()
    if getattr(self._wiki_cfg, 'wikilink_cache_enabled', True) and composer._wiki_store:
        await wikilink_cache.warm_up(composer._wiki_store, repository)
        composer._wikilink_cache = wikilink_cache

    # -- Partition tree --
    leaves, parents_by_depth = _collect_nodes_by_depth(structure.root)
    log.info("compose_phase_partition", repository=repository,
             leaves=len(leaves), parents=len(parents_by_depth))

    # -- PASS 1: Compose all leaf nodes (parallel, tier-aware) --
    sem = asyncio.Semaphore(max(1, int(getattr(self._wiki_cfg, "compose_concurrency", 3))))

    async def compose_leaf(node: WikiStructureNode) -> WikiPage | None:
        async with sem:
            try:
                graph_node = await asyncio.wait_for(
                    self._resolve_structure_node(repository, node), timeout=30)
            except (TimeoutError, Exception):
                log.warning("resolve_leaf_error", path=node.path, exc_info=True)
                return None
            tier = tiers.get(graph_node.uid)
            code_budget = self._budget_for_tier(tier, multiplier=token_budget_multiplier)
            try:
                page_data = await asyncio.wait_for(
                    self._collector.collect(repository, graph_node, code_budget=code_budget),
                    timeout=60)
            except TimeoutError:
                return None
            skeleton_strat = self._resolve_skeleton_strategy(tier)
            try:
                page = await asyncio.wait_for(
                    composer.compose_page(page_data, node.page_type, config,
                                          importance_tier=tier,
                                          skeleton_strategy=skeleton_strat),
                    timeout=_PAGE_TIMEOUT)
            except TimeoutError:
                return None
            if page is None:
                return None
            page._source_entity_uid = graph_node.uid
            wikilink_cache.register(page.title, page.path)
            return page

    log.info("compose_phase_start", repository=repository, phase="leaf_compose",
             count=len(leaves))
    leaf_results = await asyncio.gather(*(compose_leaf(n) for n in leaves))
    for page in leaf_results:
        if page is not None:
            pages.append(page)
            uid = getattr(page, '_source_entity_uid', '')
            summary_index[page.path] = _extract_summary(page, entity_uid=uid)
    log.info("compose_phase_complete", repository=repository, phase="leaf_compose",
             pages=len(pages), elapsed_s=round(_time.monotonic() - _t0, 1))

    # -- PASS 2: Compose parent nodes bottom-up (deepest first) --
    log.info("compose_phase_start", repository=repository, phase="parent_aggregate",
             count=len(parents_by_depth))
    for depth, parent_node in parents_by_depth:
        if parent_node.page_type == PageType.REPO_OVERVIEW:
            page = self._make_repo_overview_page(
                repository, structure, config, community_markdown=community_markdown)
            page.metadata.enrichment_level = EnrichmentLevel.BASE
            pages.append(page)
            continue
        try:
            graph_node = await asyncio.wait_for(
                self._resolve_structure_node(repository, parent_node), timeout=30)
        except (TimeoutError, Exception):
            continue
        tier = tiers.get(graph_node.uid)
        code_budget = self._budget_for_tier(tier, multiplier=token_budget_multiplier)
        page_data = await self._collector.collect(repository, graph_node, code_budget=code_budget)
        child_summaries = [
            summary_index[ch.path] for ch in parent_node.children
            if ch.path in summary_index
        ]
        if child_summaries:
            page = await asyncio.wait_for(
                composer.compose_parent_page(page_data, parent_node.page_type, config,
                                              child_summaries),
                timeout=_PAGE_TIMEOUT)
        else:
            page = await asyncio.wait_for(
                composer.compose_page(page_data, parent_node.page_type, config,
                                       importance_tier=tier),
                timeout=_PAGE_TIMEOUT)
        if page is not None:
            page._source_entity_uid = graph_node.uid
            pages.append(page)
            uid = graph_node.uid
            summary_index[page.path] = _extract_summary(page, entity_uid=uid)
            wikilink_cache.register(page.title, page.path)
    log.info("compose_phase_complete", repository=repository, phase="parent_aggregate",
             pages=len(pages), elapsed_s=round(_time.monotonic() - _t0, 1))

    # -- Sort and enrich --
    path_order = {p: i for i, p in enumerate(_expected_wiki_page_paths_dfs(structure.root))}
    pages.sort(key=lambda pg: path_order.get(pg.path, 1 << 30))
    await self._enrich_pages_after_compose(pages, {}, config, llm_provider)
    return pages, degraded
```

- [ ] **Step 5: Add `_resolve_skeleton_strategy` helper**

```python
def _resolve_skeleton_strategy(self, tier: ImportanceTier | None) -> SkeletonStrategy | None:
    if tier != ImportanceTier.SKELETON:
        return None
    raw = getattr(self._wiki_cfg, 'skeleton_strategy', 'template')
    try:
        return SkeletonStrategy(raw)
    except ValueError:
        return SkeletonStrategy.TEMPLATE
```

- [ ] **Step 6: Run regression tests**

Run: `uv run pytest tests/wiki/ -v -x`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/service.py tests/wiki/test_compose_phases.py
git commit -m "refactor(wiki): split _compose_all_pages into leaf→parent bottom-up phases"
```

---

### Task 3: Create BusinessFlowPageComposer

**Files:**
- Create: `wiki/business_flow_composer.py`
- Create: `tests/wiki/test_business_flow_composer.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_business_flow_composer.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.business_flow_composer import BusinessFlowPageComposer
from wiki.models import WikiConfig, WikiPageSummary, ImportanceTier, PageType


@pytest.fixture
def mock_community_service():
    svc = AsyncMock()
    svc.get_cached.return_value = {
        "communities": [
            {
                "id": 0,
                "members": ["uid:Class:AuthService", "uid:Class:SessionManager", "uid:Class:TokenValidator"],
                "size": 3,
            },
            {
                "id": 1,
                "members": ["uid:Fn:helper"],
                "size": 1,  # below min threshold
            },
        ]
    }
    return svc


@pytest.fixture
def summary_index():
    return {
        "classes/AuthService.md": WikiPageSummary(
            "uid:Class:AuthService", "AuthService", "classes/AuthService.md",
            "Handles user authentication and login.", ImportanceTier.CORE, PageType.CLASS_DETAIL,
        ),
        "classes/SessionManager.md": WikiPageSummary(
            "uid:Class:SessionManager", "SessionManager", "classes/SessionManager.md",
            "Manages user sessions and cookies.", ImportanceTier.STANDARD, PageType.CLASS_DETAIL,
        ),
        "classes/TokenValidator.md": WikiPageSummary(
            "uid:Class:TokenValidator", "TokenValidator", "classes/TokenValidator.md",
            "Validates JWT tokens.", ImportanceTier.STANDARD, PageType.CLASS_DETAIL,
        ),
    }


@pytest.mark.asyncio
async def test_compose_flows_generates_page_for_large_community(
    mock_community_service, summary_index
):
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Authentication Flow\n\nThis flow handles user login...")

    composer = BusinessFlowPageComposer(llm, mock_community_service)
    config = WikiConfig(repository="test", mode="full")
    config.business_flow_min_community_size = 2

    # Map uid → page path for lookup
    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}

    pages = await composer.compose_flows("test", summary_index, uid_to_path, config)
    assert len(pages) == 1  # only community 0 meets threshold
    assert pages[0].page_type == PageType.BUSINESS_FLOW
    llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_compose_flows_skips_small_community(mock_community_service, summary_index):
    llm = AsyncMock()
    composer = BusinessFlowPageComposer(llm, mock_community_service)
    config = WikiConfig(repository="test", mode="full")
    config.business_flow_min_community_size = 5  # threshold too high

    uid_to_path = {s.entity_uid: s.path for s in summary_index.values()}
    pages = await composer.compose_flows("test", summary_index, uid_to_path, config)
    assert len(pages) == 0
    llm.generate.assert_not_called()
```

- [ ] **Step 2: Implement BusinessFlowPageComposer**

```python
# wiki/business_flow_composer.py
"""Generates business flow overview pages from community clusters."""
from __future__ import annotations

import logging
from typing import Any

from wiki.models import (
    WikiConfig, WikiPage, WikiPageMetadata, WikiPageSummary,
    PageType,
)

log = logging.getLogger(__name__)

_FLOW_SYSTEM_PROMPT = (
    "You are writing a business flow overview for a software project. "
    "Given a cluster of related code components, explain what business purpose they serve, "
    "how they interact, and create a Mermaid sequence or flowchart diagram showing the flow. "
    "Output Markdown with sections: ## Business Purpose, ## Component Interactions, ## Flow Diagram."
)


class BusinessFlowPageComposer:
    def __init__(self, llm: Any, community_service: Any) -> None:
        self._llm = llm
        self._community_service = community_service

    async def compose_flows(
        self,
        repository: str,
        summary_index: dict[str, "WikiPageSummary"],
        uid_to_path: dict[str, str],
        config: "WikiConfig",
    ) -> list[WikiPage]:
        community_data = await self._community_service.get_cached(repository)
        communities = community_data.get("communities", [])
        min_size = getattr(config, 'business_flow_min_community_size', 3)

        pages: list[WikiPage] = []
        for community in communities:
            if community.get("size", 0) < min_size:
                continue
            member_uids = community.get("members", [])
            member_summaries = [
                summary_index[uid_to_path[uid]]
                for uid in member_uids
                if uid in uid_to_path and uid_to_path[uid] in summary_index
            ]
            if not member_summaries:
                continue
            page = await self._compose_single_flow(
                community, member_summaries, config, len(pages),
            )
            pages.append(page)
        log.info("business_flows_composed", repository=repository, count=len(pages))
        return pages

    async def _compose_single_flow(
        self,
        community: dict[str, Any],
        member_summaries: list[WikiPageSummary],
        config: WikiConfig,
        flow_index: int,
    ) -> WikiPage:
        members_ctx = "\n".join(
            f"- **{s.title}** ({s.importance_tier.value if s.importance_tier else 'unknown'}): {s.summary}"
            for s in member_summaries
        )
        prompt = (
            f"## Community #{community.get('id', flow_index)} ({len(member_summaries)} components)\n\n"
            f"### Members:\n{members_ctx}\n\n"
            "Analyze these components and generate a business flow overview."
        )
        if self._llm:
            description = (await self._llm.generate(prompt, system=_FLOW_SYSTEM_PROMPT)).strip()
        else:
            description = f"Business flow containing: {', '.join(s.title for s in member_summaries)}"

        path = f"flows/business-flow-{flow_index}.md"
        title = f"Business Flow: {member_summaries[0].title} and related" if member_summaries else f"Business Flow #{flow_index}"

        return WikiPage(
            path=path,
            title=title,
            page_type=PageType.BUSINESS_FLOW,
            content=f"# {title}\n\n{description}",
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(
                node_count=len(member_summaries),
                edge_count=0,
                generation_mode=config.mode,
            ),
        )
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/wiki/test_business_flow_composer.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/business_flow_composer.py tests/wiki/test_business_flow_composer.py
git commit -m "feat(wiki): add BusinessFlowPageComposer for community-based aggregation"
```

---

### Task 4: Create BacklinkBuilder

**Files:**
- Create: `wiki/backlink_builder.py`
- Create: `tests/wiki/test_backlink_builder.py`
- Modify: `store/falkordb_store.py` — add `find_all_referrers_batch()`

- [ ] **Step 1: Add batch referrer query to falkordb_store**

> **Performance optimization:** Instead of querying per-page (1344 queries), load all referrer
> relationships in one batch query and build an in-memory index.

```python
# store/falkordb_store.py
async def find_all_referrers_batch(self, repository: str) -> dict[str, list[str]]:
    """Batch-load all CALLS/IMPORTS relationships for backlink building.
    Returns {target_uid: [source_uid, ...]}."""
    q = (
        "MATCH (src)-[:CALLS|IMPORTS]->(tgt) "
        "WHERE src.repository = $repo AND tgt.repository = $repo "
        "RETURN tgt.uid, src.uid"
    )
    result = await self.execute_query(q, {"repo": repository})
    referrers: dict[str, list[str]] = {}
    for row in (getattr(result, 'data', None) or []):
        if row[0] and row[1]:
            referrers.setdefault(row[0], []).append(row[1])
    return referrers
```

- [ ] **Step 2: Write failing test**

```python
# tests/wiki/test_backlink_builder.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.backlink_builder import BacklinkBuilder
from wiki.wikilink_cache import WikiLinkCache
from wiki.models import WikiPage, WikiPageMetadata, PageType


@pytest.fixture
def sample_pages():
    def _make_page(path, title, uid):
        page = WikiPage(
            path=path, title=title, page_type=PageType.CLASS_DETAIL,
            content=f"# {title}\n\nSome content.", diagrams=[], source_locations=[],
            metadata=WikiPageMetadata(1, 1),
        )
        page._source_entity_uid = uid
        return page
    return [
        _make_page("classes/Foo.md", "Foo", "uid:Class:Foo"),
        _make_page("classes/Bar.md", "Bar", "uid:Class:Bar"),
    ]


@pytest.fixture
def cache_with_pages(sample_pages):
    cache = WikiLinkCache()
    for p in sample_pages:
        cache.register(p.title, p.path)
    return cache


@pytest.mark.asyncio
async def test_build_backlinks_appends_section(sample_pages, cache_with_pages):
    graph = AsyncMock()
    # Bar calls Foo
    graph.find_all_referrers_batch.return_value = {
        "uid:Class:Foo": ["uid:Class:Bar"],
    }
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    foo_page = sample_pages[0]
    assert "## Referenced by" in foo_page.content
    assert "Bar" in foo_page.content


@pytest.mark.asyncio
async def test_build_backlinks_no_referrers(sample_pages, cache_with_pages):
    graph = AsyncMock()
    graph.find_all_referrers_batch.return_value = {}
    builder = BacklinkBuilder()
    await builder.build_backlinks(sample_pages, graph, cache_with_pages, "test-repo")
    for page in sample_pages:
        assert "## Referenced by" not in page.content
```

- [ ] **Step 3: Implement BacklinkBuilder**

```python
# wiki/backlink_builder.py
"""Generates bidirectional backlinks using batch-loaded graph relationships."""
from __future__ import annotations

import logging
from typing import Any

from wiki.models import WikiPage
from wiki.wikilink_cache import WikiLinkCache

log = logging.getLogger(__name__)


class BacklinkBuilder:
    async def build_backlinks(
        self,
        pages: list[WikiPage],
        graph: Any,
        wikilink_cache: WikiLinkCache,
        repository: str,
    ) -> None:
        """Append 'Referenced by' sections to each page in-place using batch query."""
        referrer_index = await graph.find_all_referrers_batch(repository)
        uid_to_path: dict[str, str] = {}
        for page in pages:
            uid = getattr(page, '_source_entity_uid', '')
            if uid:
                uid_to_path[uid] = page.path

        modified_count = 0
        for page in pages:
            uid = getattr(page, '_source_entity_uid', '')
            if not uid:
                continue
            referrer_uids = referrer_index.get(uid, [])
            backlinks = []
            for ref_uid in referrer_uids:
                ref_path = uid_to_path.get(ref_uid)
                if ref_path:
                    ref_title = wikilink_cache.get_title_for_path(ref_path)
                    if ref_title:
                        backlinks.append(f"- [[{ref_title}]]")
            if backlinks:
                page.content += "\n\n## Referenced by\n\n" + "\n".join(sorted(set(backlinks)))
                modified_count += 1

        log.info("backlinks_built", repository=repository, pages_modified=modified_count)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_backlink_builder.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/backlink_builder.py tests/wiki/test_backlink_builder.py store/falkordb_store.py
git commit -m "feat(wiki): add BacklinkBuilder with batch referrer query"
```

---

### Task 5: Create Dynamic Delegation module

**Files:**
- Create: `wiki/delegation.py`
- Create: `tests/wiki/test_delegation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_delegation.py
import pytest
from wiki.delegation import DelegationDecision, evaluate_delegation, group_children_by_graph
from wiki.models import WikiStructureNode, PageType


def _make_children(count: int) -> list[WikiStructureNode]:
    return [
        WikiStructureNode(path=f"classes/C{i}.md", title=f"C{i}", page_type=PageType.CLASS_DETAIL)
        for i in range(count)
    ]


def test_no_delegation_under_threshold():
    children = _make_children(10)
    decision = evaluate_delegation(
        children_count=len(children), total_code_lines=1000,
        max_children=30, max_code_lines=5000,
    )
    assert not decision.should_delegate


def test_delegation_triggered_by_children_count():
    children = _make_children(50)
    decision = evaluate_delegation(
        children_count=len(children), total_code_lines=1000,
        max_children=30, max_code_lines=5000,
    )
    assert decision.should_delegate
    assert decision.reason == "too_many_children"


def test_delegation_triggered_by_code_lines():
    decision = evaluate_delegation(
        children_count=10, total_code_lines=8000,
        max_children=30, max_code_lines=5000,
    )
    assert decision.should_delegate
    assert decision.reason == "too_much_code"


def test_group_children_by_graph_connected_components():
    children = _make_children(6)
    # Edges: C0-C1-C2 form one group, C3-C4 form another, C5 is isolated
    edges = [
        (children[0].path, children[1].path),
        (children[1].path, children[2].path),
        (children[3].path, children[4].path),
    ]
    groups = group_children_by_graph(children, edges)
    assert len(groups) == 3  # {C0,C1,C2}, {C3,C4}, {C5}
    group_sizes = sorted(len(g) for g in groups)
    assert group_sizes == [1, 2, 3]


def test_group_children_chunk_fallback():
    """When no edges available, fall back to chunk-based grouping."""
    children = _make_children(10)
    groups = group_children_by_graph(children, edges=[], max_group_size=4)
    assert len(groups) == 3  # ceil(10/4)
    assert all(len(g) <= 4 for g in groups)
```

- [ ] **Step 2: Implement delegation module**

```python
# wiki/delegation.py
"""Dynamic delegation for complex modules: split oversized child sets into sub-groups."""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from wiki.models import WikiStructureNode


@dataclass
class DelegationDecision:
    should_delegate: bool
    reason: str = ""


def evaluate_delegation(
    children_count: int,
    total_code_lines: int,
    max_children: int = 30,
    max_code_lines: int = 5000,
) -> DelegationDecision:
    if children_count > max_children:
        return DelegationDecision(True, reason="too_many_children")
    if total_code_lines > max_code_lines:
        return DelegationDecision(True, reason="too_much_code")
    return DelegationDecision(False)


def group_children_by_graph(
    children: list[WikiStructureNode],
    edges: list[tuple[str, str]],
    max_group_size: int = 30,
) -> list[list[WikiStructureNode]]:
    """Group children into connected components using graph edges.
    Falls back to chunk-based grouping if no edges produce useful clusters."""
    if not edges:
        return _chunk_group(children, max_group_size)

    path_to_node = {c.path: c for c in children}
    adj: dict[str, set[str]] = defaultdict(set)
    for a, b in edges:
        if a in path_to_node and b in path_to_node:
            adj[a].add(b)
            adj[b].add(a)

    visited: set[str] = set()
    groups: list[list[WikiStructureNode]] = []

    for child in children:
        if child.path in visited:
            continue
        component: list[WikiStructureNode] = []
        stack = [child.path]
        while stack:
            path = stack.pop()
            if path in visited:
                continue
            visited.add(path)
            if path in path_to_node:
                component.append(path_to_node[path])
            for neighbor in adj.get(path, set()):
                if neighbor not in visited:
                    stack.append(neighbor)
        groups.append(component)

    return groups


def _chunk_group(
    children: list[WikiStructureNode], chunk_size: int,
) -> list[list[WikiStructureNode]]:
    return [
        children[i:i + chunk_size]
        for i in range(0, len(children), chunk_size)
    ]
```

- [ ] **Step 3: Wire into Phase 2 parent composition in service.py**

In `_compose_all_pages` Pass 2, before composing a parent node:

```python
from wiki.delegation import evaluate_delegation, group_children_by_graph

# Check if delegation needed
decision = evaluate_delegation(
    children_count=len(parent_node.children),
    total_code_lines=sum(getattr(ch, '_code_lines', 0) for ch in parent_node.children),
    max_children=getattr(self._wiki_cfg, 'delegation_max_children', 30),
    max_code_lines=getattr(self._wiki_cfg, 'delegation_max_code_lines', 5000),
)
if decision.should_delegate:
    # Group children → compose virtual sub-modules → use group summaries for parent
    groups = group_children_by_graph(parent_node.children, leaf_edges)
    group_summaries = []
    for group in groups:
        group_child_summaries = [summary_index[ch.path] for ch in group if ch.path in summary_index]
        group_page = await composer.compose_parent_page(
            page_data, PageType.MODULE_OVERVIEW, config, group_child_summaries)
        group_summaries.append(_extract_summary(group_page, entity_uid=f"virtual:{parent_node.path}"))
    child_summaries = group_summaries  # replace individual summaries with group summaries
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_delegation.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/delegation.py tests/wiki/test_delegation.py
git commit -m "feat(wiki): add dynamic delegation for complex modules"
```

---

### Task 6: Wire navigation context and cross-view links

**Files:**
- Modify: `wiki/service.py` — populate NavigationContext for each page
- Modify: `wiki/composer.py` — render breadcrumbs and navigation sections in page content

- [ ] **Step 1: Write failing tests**

```python
# tests/wiki/test_navigation_context.py
import pytest
from wiki.service import _populate_navigation_context
from wiki.models import (
    WikiPage, WikiPageMetadata, WikiStructureNode, NavigationContext,
    PageType,
)


def _make_structure():
    """Build: root > module_a > [class_foo, class_bar]"""
    foo = WikiStructureNode(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL)
    bar = WikiStructureNode(path="classes/Bar.md", title="Bar", page_type=PageType.CLASS_DETAIL)
    mod_a = WikiStructureNode(path="modules/api", title="api", page_type=PageType.MODULE_OVERVIEW, children=[foo, bar])
    root = WikiStructureNode(path="README.md", title="repo", page_type=PageType.REPO_OVERVIEW, children=[mod_a])
    return root


def test_populate_navigation_breadcrumbs():
    root = _make_structure()
    pages = {
        "classes/Foo.md": WikiPage(path="classes/Foo.md", title="Foo", page_type=PageType.CLASS_DETAIL,
                                    content="# Foo", diagrams=[], source_locations=[],
                                    metadata=WikiPageMetadata(1, 1)),
    }
    _populate_navigation_context(root, pages)
    foo_page = pages["classes/Foo.md"]
    nav = foo_page.navigation
    assert nav is not None
    assert nav.parent_path == "modules/api"
    assert nav.parent_title == "api"
    assert len(nav.breadcrumbs) >= 2  # repo > api > Foo
    assert "classes/Bar.md" in nav.sibling_paths


def test_populate_navigation_root_has_no_parent():
    root = _make_structure()
    pages = {
        "README.md": WikiPage(path="README.md", title="repo", page_type=PageType.REPO_OVERVIEW,
                               content="# repo", diagrams=[], source_locations=[],
                               metadata=WikiPageMetadata(0, 0)),
    }
    _populate_navigation_context(root, pages)
    assert pages["README.md"].navigation.parent_path is None
```

- [ ] **Step 2: Implement `_populate_navigation_context` in service.py**

```python
def _populate_navigation_context(
    root: WikiStructureNode,
    pages: dict[str, WikiPage],
) -> None:
    """Walk structure tree and populate NavigationContext for each page."""
    def _walk(node: WikiStructureNode, parent: WikiStructureNode | None, breadcrumbs: list[tuple[str, str]]):
        current_crumbs = breadcrumbs + [(node.title, node.path)]
        if node.path in pages:
            page = pages[node.path]
            nav = NavigationContext(
                parent_path=parent.path if parent else None,
                parent_title=parent.title if parent else None,
                sibling_paths=[
                    ch.path for ch in (parent.children if parent else [])
                    if ch.path != node.path
                ],
                child_paths=[ch.path for ch in node.children],
                breadcrumbs=current_crumbs,
            )
            page.navigation = nav
        for child in node.children:
            _walk(child, node, current_crumbs)

    _walk(root, None, [])
```

- [ ] **Step 3: Add `navigation` attribute to WikiPage model**

In `wiki/models.py`, add to `WikiPage`:
```python
navigation: NavigationContext | None = None
```

- [ ] **Step 4: Render navigation into page content**

Add to `wiki/composer.py` a helper that appends navigation sections to content:

```python
def render_navigation_section(page: WikiPage) -> str:
    """Render breadcrumbs and navigation links as Markdown."""
    if not page.navigation:
        return ""
    nav = page.navigation
    sections = []
    if nav.breadcrumbs:
        crumb_links = " > ".join(f"[[{title}]]" for title, path in nav.breadcrumbs)
        sections.append(f"> {crumb_links}")
    if nav.child_paths:
        sections.append("### Sub-components\n")
        for path in nav.child_paths:
            sections.append(f"- [{path}]({path})")
    if nav.sibling_paths:
        sections.append("### Related (same parent)\n")
        for path in nav.sibling_paths:
            sections.append(f"- [{path}]({path})")
    return "\n".join(sections)
```

- [ ] **Step 5: Append cross-view links (entity ↔ business flow) to page content**

After business flow pages are composed, map entity uid → flow page path:

```python
entity_to_flows: dict[str, list[str]] = {}  # uid → [flow_page_path, ...]
for flow_page in flow_pages:
    for member_uid in flow_page._member_uids:
        entity_to_flows.setdefault(member_uid, []).append(flow_page.path)

for page in pages:
    uid = getattr(page, '_source_entity_uid', '')
    flow_paths = entity_to_flows.get(uid, [])
    if flow_paths:
        links = "\n".join(f"- [{p}]({p})" for p in flow_paths)
        page.content += f"\n\n## Participates in Business Flows\n\n{links}"
```

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/wiki/test_navigation_context.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/service.py wiki/models.py wiki/composer.py tests/wiki/test_navigation_context.py
git commit -m "feat(wiki): add navigation context, breadcrumbs, and cross-view links"
```

---

### Task 7: Add configuration, SSE progress, monitoring, and integration test

**Files:**
- Modify: `config.py` — add delegation_* and business_flow_* config
- Modify: `wiki/service.py` — add Hubble alerting for quality degradation
- Create: `tests/wiki/test_phase2_integration.py`

- [ ] **Step 1: Add config fields**

```python
# config.py WikiConfig additions
business_flow_aggregation_enabled: bool = Field(default=True)
business_flow_min_community_size: int = Field(default=3)
delegation_enabled: bool = Field(default=True)
delegation_max_children: int = Field(default=30)
delegation_max_code_lines: int = Field(default=5000)
delegation_grouping_strategy: str = Field(default="graph")
```

- [ ] **Step 2: Add SSE progress for multi-phase generation**

In `_compose_all_pages`, use `progress_callback` (if available from caller) to send
phase-level progress events:

```python
if progress_callback:
    await progress_callback({
        "phase": "leaf_compose",
        "status": "started",
        "total_leaves": len(leaves),
    })
# ... after leaf pass ...
if progress_callback:
    await progress_callback({
        "phase": "leaf_compose",
        "status": "completed",
        "pages_composed": len(pages),
    })
if progress_callback:
    await progress_callback({
        "phase": "parent_aggregate",
        "status": "started",
        "total_parents": len(parents_by_depth),
    })
```

- [ ] **Step 3: Write integration test**

```python
# tests/wiki/test_phase2_integration.py
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from wiki.models import WikiConfig, ImportanceTier, PageType


@pytest.mark.asyncio
async def test_bottom_up_parent_uses_child_summaries():
    """End-to-end: verify parent page references child content."""
    # Placeholder — fill with project-specific fixtures after Phase 2 implementation
    pass


@pytest.mark.asyncio
async def test_business_flow_pages_created_for_communities():
    """End-to-end: verify business flow pages are generated from community detection."""
    pass


@pytest.mark.asyncio
async def test_navigation_context_populated():
    """End-to-end: verify breadcrumbs and sibling links are present in page content."""
    pass
```

- [ ] **Step 4: Commit**

```bash
git add config.py wiki/service.py tests/wiki/test_phase2_integration.py
git commit -m "feat(wiki): add Phase 2 configuration, SSE progress, and integration test scaffold"
```

---

## Self-Review Checklist

- [x] Spec §3.2 (Parent aggregation): Tasks 1, 2
- [x] Spec §3.3 (Business flow): Task 3
- [x] Spec §3.5 (Backlinks + navigation): Tasks 4, 6
- [x] Spec §3.6 (Dual-view): Task 6
- [x] Spec §3.8 (Delegation): Task 5
- [x] Configuration: Task 7
