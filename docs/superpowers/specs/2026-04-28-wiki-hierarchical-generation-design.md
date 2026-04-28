# Wiki Hierarchical Generation Architecture Design

> Inspired by CodeWiki's recursive decomposition, adapted with entity-level drill-down,
> configurable tiered strategy, and graph-driven incremental updates.

**Created**: 2026-04-28
**Status**: Draft
**Scope**: 5 phases covering speed optimization, hierarchical composition + business flows + delegation, incremental updates, quality evaluation, and frontend integration.
**References**: [CodeWiki (ACL 2026)](https://arxiv.org/abs/2510.24428), [DocAgent (Meta AI)](https://arxiv.org/abs/2504.08725), [DeepWiki](https://deepwiki.com), [RepoAgent](https://github.com/openbmb/repoagent), existing [wiki-generation-architecture.md](../../wiki-generation-architecture.md)

---

## 1. Background & Motivation

### 1.1 Current State

The wiki generation pipeline processes entities (Module/Class/Function) independently:
- Each entity → `WikiDataCollector.collect` → `WikiComposer.compose_page` (LLM) → `WikiPage`
- Parent modules have no knowledge of child page content
- All tiers call LLM (SKELETON gets smaller `code_budget` but still invokes LLM)
- WikiLink index rebuilt from store on every `compose_page` call
- Full regeneration only; no incremental capability for wiki content

**Benchmark** (1344-entity repo, `LLM__MAX_CONCURRENCY=5`):
- Full generation: ~11 hours
- Per-page average: ~30 seconds (LLM call)
- SKELETON entities: ~55% of total (740 entities still calling LLM)

### 1.2 Goals

| Priority | Goal | Metric |
|----------|------|--------|
| P0 | Full generation time < 2 hours | 11h → 2h (5.5x) |
| P0 | Parent pages reflect child content accurately | Qualitative |
| P1 | Business flow aggregation view | 15-30 business flow pages per repo |
| P1 | Configurable SKELETON handling | 3 strategies available |
| P2 | Incremental update on code change | Only affected pages regenerated |
| P2 | WikiLink cache eliminates repeated DB queries | 0 redundant store calls |

### 1.3 Non-Goals

- Replacing existing entity-level wiki pages with module-only docs (CodeWiki style)
- Multi-Agent framework integration (e.g., CrewAI, AutoGen)
- Dynamic Delegation (our graph structure already pre-decomposes entities)
- Complete dashboard rewrite (Phase 5 enhances existing components only)

---

## 2. Architecture Overview

### 2.1 Execution Flow

```
generate_wiki entry
  ├── WikiStructurePlanner.plan (existing)
  ├── ImportanceScorer.score_all (existing)
  ├── WikiLink cache warm-up (NEW)
  ├── [if incremental] Graph diff → affected entity set (NEW)
  │
  ├── Phase 1: Leaf Compose (topological batches, tier-aware)
  │   └── CORE/STANDARD → LLM compose (dependency order)
  │   └── SKELETON → strategy-dependent (template/light/skip)
  │
  ├── Phase 2: Parent Aggregate (bottom-up)
  │   ├── [if delegation triggered] Split into sub-groups → compose virtual modules
  │   └── Module pages composed from child/sub-group summaries
  │
  ├── Phase 3: Root Synthesis
  │   └── Repo overview from module summaries + community markdown
  │
  ├── Phase 4: Business Flow Aggregation (NEW)
  │   └── Community clustering → LLM business flow pages
  │
  ├── Backlink Building (NEW) → bidirectional "Referenced by" sections
  ├── Navigation Context (NEW) → breadcrumbs, parent/sibling/child links
  ├── Cross-View Links (NEW) → Code Wiki ↔ Business Wiki interconnection
  ├── Enrichment (existing, tier-gated)
  ├── Persist + Export (existing)
  ├── [if incremental] Propagate changes upward (NEW)
  └── Quality Evaluation (NEW) → structural + LLM judge scoring
```

### 2.2 Bottom-Up Composition (Core Change)

**Current flow (independent per node):**
```
walk(Module_A) → collect(Module_A code) → LLM → Module_A page
walk(Class_B)  → collect(Class_B code)  → LLM → Class_B page
// Module_A page knows nothing about Class_B page
```

**New flow (bottom-up):**
```
Phase 1: walk(Class_B) → collect(Class_B code) → LLM → Class_B page + summary
Phase 2: walk(Module_A) → collect(child summaries of [Class_B, ...]) → LLM → Module_A page
// Module_A page is synthesized FROM Class_B's summary
```

**Key data structure:**

```python
@dataclass
class WikiPageSummary:
    """Short summary extracted from a composed WikiPage for parent aggregation."""
    entity_uid: str
    title: str
    path: str  # wiki page path
    summary: str  # first 200 chars or LLM-extracted summary
    importance_tier: ImportanceTier | None
    page_type: PageType
```

After Phase 1 completes all leaf nodes, each `WikiPage` produces a `WikiPageSummary`.
Phase 2 uses these summaries as input context for parent module LLM calls.

---

## 3. Detailed Design

### 3.1 Phase 1: Leaf Node Compose (Tier-Aware)

#### 3.1.1 SkeletonStrategy Configuration

Add to `wiki/models.py`:

```python
class SkeletonStrategy(StrEnum):
    TEMPLATE = "template"       # Use _tier3_structural, no LLM call
    LIGHT_MODEL = "light_model" # Use a cheaper/faster model
    SKIP = "skip"               # Don't generate page, only mention in parent
```

Add to `config.py` `WikiConfig` (app-level settings):

```python
skeleton_strategy: str = Field(default="template")  # template | light_model | skip
skeleton_light_model: str = Field(default="")  # model name for light_model strategy
```

#### 3.1.2 Compose Flow Changes

In `WikiComposer.compose_page`, before the existing tier fallback logic:

```python
async def compose_page(self, page_data, page_type, config, *,
                       importance_tier=None, skeleton_strategy=None, ...):
    if importance_tier == ImportanceTier.SKELETON:
        if skeleton_strategy == SkeletonStrategy.SKIP:
            return None  # caller handles None as "no page"
        if skeleton_strategy == SkeletonStrategy.TEMPLATE:
            # Use existing _tier3_structural, skip LLM entirely
            tier = 3
            description = self._tier3_structural(page_data, page_type, eff_lang)
            # ... rest of page assembly (diagrams, wikilinks, etc.)
        elif skeleton_strategy == SkeletonStrategy.LIGHT_MODEL:
            # Use a separate, cheaper LLM for SKELETON entities
            tier = 2
            description = await self._tier2_llm_light(page_data, page_type, config)
    # ... existing CORE/STANDARD flow unchanged
```

#### 3.1.3 Parallel Execution

Leaf nodes (classes, functions with no children) are composed in parallel using the
existing `asyncio.Semaphore` mechanism (`compose_concurrency`). No change needed here;
the existing `walk_children_parallel` already handles this.

**Change:** In `_compose_all_pages`, separate the walk into two passes:
1. First pass: compose all leaf nodes (parallel)
2. Second pass: compose all non-leaf nodes bottom-up (using child summaries)

### 3.2 Phase 2: Parent Node Aggregation (Bottom-Up)

#### 3.2.1 New Method: `_compose_parent_from_children`

Added to `WikiComposer`:

```python
async def compose_parent_page(
    self,
    page_data: PageData,
    page_type: PageType,
    config: WikiConfig,
    child_summaries: list[WikiPageSummary],
) -> WikiPage:
    """Compose a module/parent page using child summaries instead of raw code."""
    children_context = "\n".join(
        f"- **{s.title}** ({s.importance_tier or 'unknown'}): {s.summary}"
        for s in child_summaries
    )
    # LLM prompt uses child summaries as primary context
    # Code context is minimal (module-level docstring, imports only)
    prompt = self._build_parent_prompt(page_data, children_context, config)
    description = await self._llm.generate(prompt, system=PARENT_SYSTEM_PROMPT)
    # ... standard page assembly
```

#### 3.2.2 Execution Order

```python
async def _compose_all_pages(self, ...):
    # Step 1: Identify leaf vs non-leaf nodes
    leaves, parents = partition_by_leaf_status(structure.root)

    # Step 2: Compose all leaves in parallel (tier-aware)
    leaf_pages = await self._compose_leaves_parallel(leaves, ...)

    # Step 3: Build summary index from leaf pages
    summary_index: dict[str, WikiPageSummary] = {
        p.path: extract_summary(p) for p in leaf_pages if p is not None
    }

    # Step 4: Compose parents bottom-up (deepest first)
    parents_sorted = topological_sort_bottom_up(parents)
    for parent_node in parents_sorted:
        child_summaries = [summary_index[c.path] for c in parent_node.children
                          if c.path in summary_index]
        page = await composer.compose_parent_page(
            page_data, parent_node.page_type, config, child_summaries
        )
        summary_index[page.path] = extract_summary(page)
        pages.append(page)
```

### 3.3 Phase 4: Business Flow Aggregation

#### 3.3.1 Flow

```
CommunityDetector.detect()
  → list[Community] (each with member entities)
  → For each community with size >= threshold:
      1. Collect member WikiPageSummaries from summary_index
      2. Collect call chain edges between members
      3. LLM generates business flow overview
      4. Generate Mermaid sequence diagram
      5. Create WikiPage(page_type=BUSINESS_FLOW)
```

#### 3.3.2 New Component: BusinessFlowPageComposer

Location: `wiki/business_flow_composer.py`

```python
class BusinessFlowPageComposer:
    """Generates business flow overview pages from community clusters."""

    def __init__(self, llm: LLMPort, community_service: CachedCommunityService):
        self._llm = llm
        self._community_service = community_service

    async def compose_flows(
        self,
        repository: str,
        summary_index: dict[str, WikiPageSummary],
        config: WikiConfig,
    ) -> list[WikiPage]:
        communities = await self._community_service.get_cached(repository)
        pages = []
        for community in communities:
            if community.size < config.business_flow_min_community_size:
                continue
            member_summaries = self._collect_member_summaries(
                community, summary_index
            )
            call_chains = self._extract_call_chains(community)
            page = await self._compose_flow_page(
                community, member_summaries, call_chains, config
            )
            pages.append(page)
        return pages
```

#### 3.3.3 Integration with WikiTreeNav

Business flow pages are attached to the `business_domain` view in the wiki tree:
- Each flow page gets a `HAS_CHILD` edge with `view_type="business_domain"`
- Visible when user switches to the "Business Domain" tab in the dashboard

### 3.4 WikiLink Cache

#### 3.4.1 Design

Location: `wiki/wikilink_cache.py`

```python
class WikiLinkCache:
    """In-memory cache for WikiPage title → URL mapping."""

    def __init__(self):
        self._index: dict[str, str] = {}
        self._loaded = False

    async def warm_up(self, wiki_store: WikiStore, repository: str):
        """Load all existing wiki page titles from store once."""
        result = await wiki_store.list_wiki_pages_all(repository)
        for row in (getattr(result, "data", None) or []):
            title = row.get("title")
            path = row.get("path")
            if title and path:
                self._index[str(title).strip()] = f"/wiki?path={quote(str(path), safe='')}"
        self._loaded = True

    def register(self, title: str, path: str):
        """Register a newly composed page into the cache."""
        self._index[title.strip()] = f"/wiki?path={quote(path, safe='')}"

    def get_index(self) -> dict[str, str]:
        return dict(self._index)
```

#### 3.4.2 Integration

- `WikiComposer.__init__` accepts optional `wikilink_cache: WikiLinkCache`
- `compose_page` uses `cache.get_index()` instead of `_wikilink_entity_index()` DB call
- After each page is composed, `cache.register(page.title, page.path)`
- Cache is created and warmed up in `_compose_all_pages` before the walk begins

### 3.5 Cross-Reference & Navigation Enhancement

#### 3.5.1 Bidirectional Backlinks

**Problem:** Current WikiLink only resolves `[[Title]]` → URL (forward). Pages don't show
"who references me" (backward), despite the graph already containing CALLS/IMPORTS/INHERITS edges.

**Design:** After all pages are composed, a `BacklinkBuilder` pass generates a "Referenced by" section
for each page using graph relationships.

```python
class BacklinkBuilder:
    """Generates bidirectional backlinks using graph relationships."""

    async def build_backlinks(
        self,
        pages: list[WikiPage],
        graph: GraphQueryPort,
        wikilink_cache: WikiLinkCache,
        repository: str,
    ) -> None:
        """Append 'Referenced by' sections to each page in-place."""
        # Build uid → wiki_path mapping from pages
        uid_to_path = {
            getattr(p, '_source_entity_uid', ''): p.path
            for p in pages if hasattr(p, '_source_entity_uid')
        }
        for page in pages:
            uid = getattr(page, '_source_entity_uid', '')
            if not uid:
                continue
            # Query: who CALLS/IMPORTS/INHERITS this entity?
            referrers = await graph.find_referrers(repository, uid)
            backlinks = []
            for ref_uid in referrers:
                ref_path = uid_to_path.get(ref_uid)
                if ref_path:
                    ref_title = wikilink_cache.get_title_for_path(ref_path)
                    backlinks.append(f"- [[{ref_title}]]")
            if backlinks:
                page.content += "\n\n## Referenced by\n\n" + "\n".join(backlinks)
```

Data source: Existing graph edges (CALLS where `target_uid = this`, IMPORTS where `target_uid = this`).

#### 3.5.2 Contextual Navigation Metadata

**Problem:** Users cannot navigate from a page to its parent, siblings, or children without the
tree sidebar. Pages lack positional context within the wiki structure.

**Design:** Extend `WikiPageMetadata` with navigation fields:

```python
@dataclass
class NavigationContext:
    parent_path: str | None = None
    parent_title: str | None = None
    sibling_paths: list[str] = field(default_factory=list)
    child_paths: list[str] = field(default_factory=list)
    related_flow_paths: list[str] = field(default_factory=list)  # business flows
    breadcrumbs: list[tuple[str, str]] = field(default_factory=list)  # [(title, path)]
```

- Populated during `_compose_all_pages` from the `WikiStructure` tree.
- Rendered in page content as breadcrumbs at top and navigation links at bottom.
- Example breadcrumb: `Repo > src/api > routes > wiki_task_routes.py`

#### 3.5.3 Cross-View Links (Code Wiki ↔ Business Wiki)

**Problem:** Code Wiki and Business Wiki exist as separate tree views, but pages don't link
across views. A class page doesn't show which business flows it participates in.

**Design:**
- Each entity page appends: `## Participates in Business Flows` with links to flow pages.
- Each business flow page lists: `## Core Components` with links to entity pages.
- Mapping source: community membership (entity_uid → community_id → flow_page_path).
- WikiLink resolver supports cross-view resolution via a unified namespace.

### 3.6 Dual-View Wiki Architecture

#### 3.6.1 Code Wiki (code_structure view)

```
Repo Overview
├── Module: src/api
│   ├── Class: WikiTaskRoutes
│   ├── Class: WikiPageRoutes
│   └── Function: health_check
├── Module: src/wiki
│   ├── Class: WikiService
│   ├── Class: WikiComposer
│   └── ...
└── Module: src/store
    └── ...
```

- Tree structure: Repo > Module > SubModule > Class/Function
- Page types: REPO_OVERVIEW > MODULE_OVERVIEW > CLASS_DETAIL / API_REFERENCE
- Content focus: Code implementation, API docs, dependency relationships
- Target audience: Developers understanding specific implementations

#### 3.6.2 Business Wiki (business_domain view)

```
Domain: Wiki Generation
├── Business Flow: Wiki Page Composition Pipeline
│   └── Components: [WikiService, WikiComposer, WikiDataCollector]
├── Business Flow: Wiki Search & Q&A
│   └── Components: [DeepSearchService, ConversationService]
└── Business Flow: Task Management
    └── Components: [WikiTaskStore, WikiTaskRegistry]
```

- Tree structure: Domain > Business Flow > member entity references
- Page types: DOMAIN_OVERVIEW > BUSINESS_FLOW > (cross-links to Code Wiki)
- Content focus: Business purpose, call chain diagrams, data flow
- Target audience: Product managers, new team members, AI agents

#### 3.6.3 View Switching & Interconnection

- Frontend `WikiTreeNav` already has tab switching (code_structure / business_domain) — no change.
- New: In-page cross-view navigation elements (§3.5.3).
- WikiLink namespace is unified: `[[WikiService]]` resolves regardless of which view the user is on.

### 3.7 Topological Processing Order for Leaves

**Insight from DocAgent (Meta AI):** Ablation studies confirm topological processing order is critical
for documentation quality. If entity B depends on entity A, generating A's documentation first allows
B's documentation to reference A's summary, improving cross-reference accuracy.

**Design:** Phase 1 leaf processing uses dependency-aware batching:

```python
async def _compose_leaves_topological(self, leaves, ...):
    """Compose leaf nodes in topological order for dependency-aware generation."""
    # Build dependency graph from CALLS/IMPORTS edges among leaf entities
    dep_graph = await self._build_leaf_dependency_graph(leaves)

    # Topological sort → batch by level (all nodes at same depth can parallel)
    batches = topological_batches(dep_graph)

    for batch in batches:
        # Nodes in same batch have no inter-dependencies → safe to parallelize
        batch_pages = await asyncio.gather(
            *(self._compose_single_leaf(node, ...) for node in batch)
        )
        # Register summaries so next batch can reference them
        for page in batch_pages:
            if page:
                summary_index[page.path] = extract_summary(page)
```

- Batch 0: Entities with no dependencies (utility classes, base types)
- Batch 1: Entities depending only on Batch 0
- Batch N: Entities depending on Batch 0..N-1
- Within each batch: full parallelism with `compose_concurrency` semaphore

This ensures that when composing entity B, the summary of its dependency A is already available
in the `summary_index` and can be injected as context in B's LLM prompt.

### 3.8 Dynamic Delegation for Complex Modules

**Insight from CodeWiki:** When a module's complexity exceeds single-pass capacity (too many children,
too much code, semantic diversity too high), the agent should dynamically split it into sub-modules.

**Problem in our system:** A module with 100+ child entities will produce a very long parent page.
The `compose_parent_page` LLM prompt may overflow context window or produce shallow descriptions
when too many child summaries are included.

#### 3.8.1 Delegation Criteria

```python
@dataclass
class DelegationDecision:
    should_delegate: bool
    sub_groups: list[list[WikiStructureNode]] | None = None
    reason: str = ""

def evaluate_delegation(
    node: WikiStructureNode,
    children_count: int,
    total_code_lines: int,
    config: WikiConfig,
) -> DelegationDecision:
    """Determine if a module needs dynamic delegation."""
    # Threshold-based criteria
    if children_count > config.delegation_max_children:  # default: 30
        return DelegationDecision(True, reason="too_many_children")
    if total_code_lines > config.delegation_max_code_lines:  # default: 5000
        return DelegationDecision(True, reason="too_much_code")
    return DelegationDecision(False)
```

#### 3.8.2 Sub-Module Grouping Strategy

When delegation is triggered, group children into coherent sub-modules:

1. **Graph-based grouping** (preferred): Use CALLS/IMPORTS edges between children to form
   connected components → each component becomes a virtual sub-module.
2. **Semantic clustering fallback**: If graph edges are sparse, use LLM to cluster children
   by name/docstring similarity.
3. **Simple chunking**: If neither works, split alphabetically into groups of `delegation_max_children`.

```python
async def _delegate_and_compose(self, node, children, config, composer):
    decision = evaluate_delegation(node, len(children), ...)
    if not decision.should_delegate:
        return await composer.compose_parent_page(node, all_child_summaries, config)

    # Group children into sub-modules
    groups = await self._group_children(node, children, config)

    # Compose each sub-group as a virtual module page
    group_pages = []
    for group in groups:
        group_summaries = [summary_index[c.path] for c in group]
        group_page = await composer.compose_parent_page(
            virtual_module_node(node, group), group_summaries, config
        )
        group_pages.append(group_page)

    # Compose the parent from group summaries (not individual children)
    group_summaries = [extract_summary(p) for p in group_pages]
    parent_page = await composer.compose_parent_page(node, group_summaries, config)
    return parent_page, group_pages
```

#### 3.8.3 Configuration

```python
# config.py WikiConfig additions
delegation_enabled: bool = Field(default=True)
delegation_max_children: int = Field(default=30)
delegation_max_code_lines: int = Field(default=5000)
delegation_grouping_strategy: str = Field(default="graph")  # graph | semantic | chunk
```

### 3.9 Quality Evaluation System

**Problem:** After generation, there's no automated way to measure documentation quality.
CodeWiki has CodeWikiBench (hierarchical rubric + LLM judges), DocAgent has Completeness /
Helpfulness / Truthfulness evaluation. Our existing `quality_score` only measures structural
metrics (presence of sections, diagram count, etc.).

#### 3.9.1 Three-Dimension Quality Evaluation

Inspired by DocAgent's framework, adapted for our wiki structure:

```python
class WikiQualityDimension(StrEnum):
    COMPLETENESS = "completeness"   # Are all important aspects documented?
    HELPFULNESS = "helpfulness"     # Is the documentation useful for understanding?
    TRUTHFULNESS = "truthfulness"   # Is the documentation accurate vs source code?

@dataclass
class WikiPageQualityScore:
    page_path: str
    completeness: float  # 0.0 - 1.0
    helpfulness: float
    truthfulness: float
    overall: float
    issues: list[str]
```

#### 3.9.2 Evaluation Pipeline

```
For each WikiPage (sample or all CORE entities):
  1. Structural checks (existing quality_score)
     - Has overview section? Has methods section? Has relationships?
     - Diagram present? WikiLinks resolved?

  2. LLM-as-Judge evaluation (NEW)
     - Judge receives: wiki page content + source code + graph metadata
     - Evaluates per dimension with rubric:
       - Completeness: "Does it cover purpose, key methods, relationships, usage?"
       - Helpfulness: "Can a new developer understand this component from the doc?"
       - Truthfulness: "Are code references accurate? Any hallucinations?"
     - Outputs score (0-1) + issues list

  3. Hierarchical aggregation (inspired by CodeWikiBench)
     - Page scores → Module scores (weighted by importance tier)
     - Module scores → Repository score
     - CORE entities weighted 3x, STANDARD 2x, SKELETON 1x
```

#### 3.9.3 Quality Evaluation Modes

| Mode | When to Use | LLM Calls | Coverage |
|------|-------------|-----------|----------|
| **quick** | After every generation | 0 | Structural checks only |
| **sampled** | Weekly or on-demand | ~20 (CORE sample) | LLM judge on representative pages |
| **full** | Before release/review | All CORE + STANDARD | Complete LLM quality audit |

#### 3.9.4 Quality Feedback Loop

When quality score drops below threshold (`quality_min_score`, default 0.6):
1. Log warning with specific issues
2. Mark low-quality pages for regeneration in next incremental pass
3. If `quality_auto_heal` enabled, trigger targeted regeneration with enhanced prompts

```python
# config.py WikiConfig additions
quality_evaluation_mode: str = Field(default="quick")  # quick | sampled | full
quality_min_score: float = Field(default=0.6)
quality_auto_heal: bool = Field(default=False)
quality_judge_model: str = Field(default="")  # use main LLM if empty
```

### 3.10 Incremental Update (Basic)

#### 3.10.1 Diff Detection

Location: `wiki/incremental_diff.py`

```python
@dataclass
class WikiDiff:
    """Entities whose wiki pages need regeneration."""
    changed_uids: set[str]  # entities with code_hash changes
    affected_parents: set[str]  # ancestor modules of changed entities
    affected_communities: set[int]  # communities containing changed entities

async def compute_wiki_diff(
    store: FalkorDBStore,
    repository: str,
    since_version: int,
) -> WikiDiff:
    """Compare current graph state with last wiki generation version."""
    # 1. Find entities whose code changed since last wiki gen
    changed = await store.execute_query(
        "MATCH (n {repository: $repo}) "
        "WHERE n.code_hash <> n.wiki_code_hash OR n.wiki_code_hash IS NULL "
        "RETURN n.uid",
        {"repo": repository},
    )
    changed_uids = {row[0] for row in changed.data or []}

    # 2. Propagate upward: find all ancestor modules via CONTAINS
    ancestors = await store.execute_query(
        "MATCH (parent)-[:CONTAINS*1..10]->(child) "
        "WHERE child.uid IN $uids AND parent.repository = $repo "
        "RETURN DISTINCT parent.uid",
        {"repo": repository, "uids": list(changed_uids)},
    )
    affected_parents = {row[0] for row in ancestors.data or []}

    # 3. Identify affected communities
    affected_communities = set()  # populated from community membership index

    return WikiDiff(changed_uids, affected_parents, affected_communities)
```

#### 3.10.2 Incremental Generation Flow

```python
async def generate_incremental(self, repository, since_version, ...):
    diff = await compute_wiki_diff(self._store, repository, since_version)

    # Only compose changed leaf entities
    changed_leaves = filter_leaves(diff.changed_uids, structure)
    leaf_pages = await self._compose_leaves_parallel(changed_leaves, ...)

    # Recompose affected parent modules (using updated child summaries)
    for parent_uid in diff.affected_parents:
        # Load existing child summaries + replace changed ones
        page = await self._compose_parent_from_children(...)

    # Recompose affected business flow pages
    for community_id in diff.affected_communities:
        page = await self._compose_flow_page(...)

    # Persist only changed pages
    await self._persist_pages_to_graph(changed_pages, ...)
```

#### 3.10.3 Version Tracking

Each wiki generation stores a `wiki_generation_version` (graph version at time of generation).
Incremental generation compares current graph version with stored version.

---

## 4. Configuration

New settings in `config.py`:

```python
class WikiConfig(BaseSettings):
    # ... existing fields ...

    # Phase 1: Tier-aware composition
    skeleton_strategy: str = Field(default="template")  # template | light_model | skip
    skeleton_light_model: str = Field(default="")

    # Phase 1: WikiLink cache
    wikilink_cache_enabled: bool = Field(default=True)

    # Phase 2: Business flow aggregation
    business_flow_aggregation_enabled: bool = Field(default=True)
    business_flow_min_community_size: int = Field(default=3)

    # Phase 2: Dynamic delegation
    delegation_enabled: bool = Field(default=True)
    delegation_max_children: int = Field(default=30)
    delegation_max_code_lines: int = Field(default=5000)
    delegation_grouping_strategy: str = Field(default="graph")  # graph | semantic | chunk

    # Phase 3: Incremental update
    incremental_enabled: bool = Field(default=False)

    # Phase 4: Quality evaluation
    quality_evaluation_mode: str = Field(default="quick")  # quick | sampled | full
    quality_min_score: float = Field(default=0.6)
    quality_auto_heal: bool = Field(default=False)
    quality_judge_model: str = Field(default="")  # use main LLM if empty
```

---

## 5. File Change Inventory

| File | Change | Phase |
|------|--------|-------|
| `wiki/models.py` | Add `SkeletonStrategy`, `WikiPageSummary`, `NavigationContext`, `DelegationDecision`, `WikiPageQualityScore` | P1-P4 |
| `wiki/composer.py` | Add tier-aware dispatch, `compose_parent_page`, delegation-aware compose | P1, P2 |
| `wiki/service.py` | Refactor `_compose_all_pages` into leaf/parent/root/flow phases; topological batching; delegation | P1-P3 |
| `wiki/wikilink_cache.py` | **New file** — WikiLink cache manager with bidirectional lookup | P1 |
| `wiki/backlink_builder.py` | **New file** — Bidirectional backlink generation from graph edges | P2 |
| `wiki/business_flow_composer.py` | **New file** — Business flow page composer from communities | P2 |
| `wiki/delegation.py` | **New file** — Dynamic delegation: criteria evaluation + child grouping | P2 |
| `wiki/quality_evaluator.py` | **New file** — Three-dimension quality evaluation (structural + LLM judge) | P4 |
| `wiki/community_context.py` | Add `get_communities_for_aggregation()` returning structured data | P2 |
| `wiki/incremental_diff.py` | **New file** — Graph diff computation | P3 |
| `config.py` | Add `skeleton_strategy`, `delegation_*`, `quality_*`, `incremental_enabled` | P1-P4 |
| `store/wiki_store.py` | Add `get_wiki_generation_version()`, `set_wiki_generation_version()` | P3 |
| `wiki/structure_planner.py` | Add leaf/non-leaf classification on `WikiStructureNode` | P1 |
| `store/falkordb_store.py` | Add `find_all_referrers_batch()` for backlink queries | P2 |
| `dashboard/src/hooks/useWikiNavigation.ts` | **New file** — NavigationContext fetch hook | P5 |
| `dashboard/src/components/wiki/WikiNavigationLinks.tsx` | **New file** — Parent/sibling/child navigation | P5 |
| `dashboard/src/components/wiki/WikiQualityBadge.tsx` | **New file** — Quality score badge | P5 |
| `dashboard/src/components/wiki/WikiQualitySummary.tsx` | **New file** — Repo quality summary card | P5 |
| `dashboard/src/components/wiki/WikiIncrementalTrigger.tsx` | **New file** — Incremental update button | P5 |
| `dashboard/src/hooks/useWikiIncremental.ts` | **New file** — Incremental generation mutation | P5 |
| `dashboard/src/components/wiki/WikiBreadcrumbs.tsx` | Use NavigationContext from API | P5 |
| `dashboard/src/components/wiki/WikiActiveTasks.tsx` | Multi-phase SSE progress | P5 |
| `dashboard/src/hooks/useWikiQualityScore.ts` | Use new quality evaluation API | P5 |

---

## 6. Phased Delivery Plan

### Phase 1: Speed Optimization + Foundation (est. 4-5 days)

- WikiLink cache (warm-up + register + bidirectional lookup)
- `SkeletonStrategy` enum and configuration
- Tier-aware `compose_page` dispatch
- Topological dependency batching for leaf nodes (DocAgent insight)
- `WikiPageSummary` data structure
- `NavigationContext` data structure

**Expected outcome:** Full generation 11h → ~2h; leaf ordering respects dependencies

### Phase 2: Hierarchical Composition + Business Flows + Navigation + Delegation (est. 6-8 days)

- `compose_parent_page` method (LLM with child summaries)
- Bottom-up parent aggregation in `_compose_all_pages`
- **Dynamic Delegation** for complex modules (§3.8): criteria evaluation + child grouping
- `BusinessFlowPageComposer` implementation
- Community → business flow mapping
- `BacklinkBuilder` for bidirectional backlinks
- Contextual navigation (breadcrumbs, parent/sibling/child links)
- Cross-view links (Code Wiki ↔ Business Wiki)
- Integration with `WikiTreeNav` business_domain view

**Expected outcome:** Higher quality parent pages + 15-30 business flow overview pages + full bidirectional navigation + adaptive handling of large modules

### Phase 3: Incremental Update (est. 3-4 days)

- `WikiDiff` computation from graph version comparison
- `generate_incremental` entry point
- Version tracking in wiki store
- Upward propagation of changes to parent/flow pages

**Expected outcome:** Iterative updates in minutes instead of hours

### Phase 4: Quality Evaluation System (est. 3-4 days)

- Structural quality checks (extend existing `quality_score`)
- LLM-as-Judge three-dimension evaluation (Completeness / Helpfulness / Truthfulness)
- Hierarchical score aggregation (page → module → repo)
- Quality feedback loop (auto-heal low-quality pages)
- Three evaluation modes: quick / sampled / full
- Quality score persistence and summary API

**Expected outcome:** Automated quality measurement + self-healing for low-quality pages

### Phase 5: Frontend Integration (est. 3-4 days)

- Enhanced WikiBreadcrumbs with backend NavigationContext
- WikiNavigationLinks component (parent/sibling/child/flow links)
- WikiQualityBadge and WikiQualitySummary components
- Multi-phase SSE progress display in WikiActiveTasks
- WikiIncrementalTrigger button for incremental updates
- Backend API endpoints for navigation and quality summary

**Expected outcome:** Dashboard fully reflects hierarchical wiki structure, quality scores, and incremental update capability

---

## 7. Risks & Mitigations

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| Bottom-up order incorrect (parent composed before child) | Medium | High | Strict topological sort; add assertion |
| SKELETON template quality too low for user expectations | Low | Medium | Default to `template`, allow `light_model` fallback |
| Community detection clusters too coarse/fine | Medium | Medium | `business_flow_min_community_size` tunable |
| Incremental diff misses transitive dependencies | Medium | High | Conservative: also regenerate 1-hop neighbors |
| Summary extraction loses important details | Low | Medium | Keep summary at 200 chars; add full page link |
| Delegation grouping produces incoherent sub-modules | Medium | Medium | Graph-based grouping preferred; fallback to semantic clustering |
| LLM quality judge scores inconsistent across runs | Medium | Low | Multi-model averaging (like CodeWikiBench); cache scores |
| Quality auto-heal triggers infinite regeneration loop | Low | High | Max 2 heal attempts per page per generation cycle |

---

## 8. Testing Strategy

- **Unit tests:** `WikiPageSummary` extraction, `SkeletonStrategy` dispatch, `WikiLinkCache`
- **Integration tests:** Bottom-up compose order verification, incremental diff correctness
- **Regression tests:** Existing `test_compose_all_pages*` must pass with new code paths
- **Quality benchmark:** Compare parent page quality (with/without child summaries) using LLM judge

---

## 9. Appendix: Industry Comparison

| Dimension | CodeWiki (ACL'26) | DeepWiki | RepoAgent | DocAgent (Meta) | Our Design |
|-----------|-------------------|----------|-----------|-----------------|------------|
| Granularity | Module (~30-50 pages) | Module + entity | Entity | Entity | Entity + module + business flow |
| Bottom-up synthesis | Yes | No | No | Yes (topological) | Yes (Phase 2) |
| Tiered processing | No | No | No | No | Yes (SKELETON strategy) |
| Cross-references | Global registry | Source links | Bidirectional calls | Cross-module | WikiLink + backlinks + cross-view |
| Navigation | Module tree | Architecture diagram click | None | None | Tree + breadcrumbs + parent/sibling/child |
| Business view | Feature-oriented modules | None | None | None | Community → business flow pages |
| Dual views | No | No | No | No | Code Wiki + Business Wiki |
| Incremental update | No | No | Git diff based | No | Graph diff + upward propagation |
| Agent consumption | Not addressed | RAG Q&A | Not addressed | Not addressed | MCP tools (existing) |
| Quality evaluation | CodeWikiBench | None | None | 3-dimension eval | quality_score (existing, extendable) |
| Topological ordering | Not specified | No | No | Yes (critical) | Yes (Phase 1 leaf batching) |
| Dynamic delegation | Yes | No | No | No | Not needed (graph pre-decomposed) |

### Key Inspirations Adopted

- **From CodeWiki:** Bottom-up hierarchical synthesis (§3.2), cross-reference registry (§3.4)
- **From DocAgent:** Topological processing order for leaves (§3.7)
- **From RepoAgent:** Bidirectional backlinks from call graph (§3.5.1)
- **From DeepWiki:** Interactive architecture diagram navigation (future consideration)
- **Original:** SKELETON tiered strategy, dual-view architecture, graph-driven incremental update
