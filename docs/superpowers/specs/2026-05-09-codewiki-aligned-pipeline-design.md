# CodeWiki-Aligned Pipeline Redesign

> **Status**: APPROVED (brainstorming complete)
> **Category**: Architecture / Wiki Quality / Pipeline Redesign
> **Related**: CodeWiki (ACL 2026, arXiv:2510.24428v6), `2026-05-09-graph-driven-deterministic-decomposition.md`
> **Approach**: 方案 1 — 管线内置换 (Pipeline Node Replacement)

---

## 1. Background & Problem Statement

### 1.1 Current System Quality Gap

Through comparison with CodeWiki (ACL 2026), we identified four root causes for our wiki generation quality deficit:

1. **Non-deterministic structure**: `TopicBasedStructurePlanner` uses LLM to freely generate module structure, causing different runs to produce different trees
2. **Chinese domain linking breakage**: LLM-generated Chinese titles fail to match in `tree_linker._find_best_domain()` heuristic string matching, leaving nodes orphaned
3. **No bottom-up synthesis**: Parent pages use template filling instead of synthesizing from child documents
4. **Incomplete evaluation**: L2 (LLM Judge) is a stub, L3 only runs on core-tier pages

### 1.2 CodeWiki Paper vs Implementation Reality

| Aspect | Paper Description | Actual Code (FSoft-AI4Code/CodeWiki) |
|---|---|---|
| Module decomposition | Graph algorithms (SCC + topological sort) | **LLM clustering** + recursive decomposition |
| Processing order | Bottom-up (children first) | DFS (children first) — confirmed |
| Agent tools | Not detailed | `read_code_components`, `generate_sub_module_documentation` |
| Cross-module registry | Mentioned | Empty dict (`registry = {}`) — not implemented |
| Evaluation | CodeWikiBench multi-judge | Not in open-source code |

**Our opportunity**: We have FalkorDB persistent graph storage, enabling us to implement the paper's ideal graph-algorithm-based decomposition — more deterministic than CodeWiki's actual LLM clustering approach.

### 1.3 Design Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Scope | All three problem domains in unified proposal | A (structure) is prerequisite for B (linking) and C (quality) |
| Decomposition strategy | Graph algorithms as skeleton + LLM-assisted grouping | Deterministic top-level structure + semantic understanding for sub-grouping |
| canonical_key generation | Based on code file paths (slug format) | Readable, deterministic, naturally linked to code |
| Backward compatibility | Direct replacement (no parallel introduction) | Cleaner; user preference |
| Architecture approach | Pipeline node replacement within LangGraph | Preserves checkpoint, progress, heal loop; changes limited to node implementations |

---

## 2. Architecture Design

### 2.1 Pipeline Flow Change

**Current pipeline** (15 nodes):
```
classify_entity_roles → detect_reorg → classify_domains → decompose_hierarchy
→ set_review_status → compose_leaf_modules → plan_topic_structure
→ compose_leaf_pages → quality_gate ⇄ heal_pages
→ summarize_leaves → compose_parent_pages → synthesize_overviews
→ create_links → finalize
```

**New pipeline** (11 nodes):
```
classify_entity_roles → detect_reorg
→ graph_decompose → assign_canonical_keys → generate_titles
→ set_review_status → compose_leaf_modules
→ compose_bottomup → quality_gate ⇄ heal_pages
→ create_links → finalize
```

**Node mapping**:

| Removed Nodes | Replacement | Change Type |
|---|---|---|
| `classify_domains` + `decompose_hierarchy` + `plan_topic_structure` | `graph_decompose` + `assign_canonical_keys` + `generate_titles` | 3→3 replacement |
| `compose_leaf_pages` + `compose_parent_pages` + `synthesize_overviews` + `summarize_leaves` | `compose_bottomup` | 4→1 merge |

### 2.2 New Node: `graph_decompose`

**Purpose**: Replace LLM-driven structure planning with graph-algorithm-based module decomposition.

**Input**: `state["modules"]` (entity list from FalkorDB)
**Output**: `state["module_tree"]` (hierarchical ModuleTree)

**Algorithm** (4 steps):

```
Step 1: Load dependency graph from FalkorDB
  MATCH (a)-[r:DEPENDS_ON|CALLS|IMPORTS]->(b)
  WHERE a.repo_id = $repo_id AND b.repo_id = $repo_id
  RETURN a.uid, b.uid, type(r)
  → In-memory directed graph G=(V,E)

Step 2: Compute SCC (Tarjan's algorithm)
  → Merge cyclic-dependency nodes into super-nodes → DAG

Step 3: Topological sort
  → Deterministic processing order (dependencies processed first)

Step 4: Recursive decomposition with token constraint
  def recursive_decompose(nodes, max_tokens=30000):
      if total_tokens(nodes) <= max_tokens:
          return LeafModule(nodes)
      components = find_connected_components(subgraph(nodes))
      if len(components) > 1:
          return [recursive_decompose(c) for c in components]
      # CC cannot split further → LLM-assisted grouping
      groups = llm_cluster(nodes, max_groups=5)
      return [recursive_decompose(g) for g in groups]
```

**Determinism guarantee**: Steps 1-3 are pure algorithms. Step 4 only invokes LLM when graph algorithms cannot split a large connected component. For most codebases, CC splitting alone is sufficient.

**Entry point identification**: After SCC condensation, in-degree=0 super-nodes in the DAG are natural entry points (main functions, API endpoints, CLI handlers). These map to the top-level modules of the tree. The existing `classify_entity_roles` node already identifies entry_point roles, which can augment this identification.

**Token estimation**: `total_tokens(nodes)` is estimated as the sum of source file sizes (in characters) ÷ 4, providing a conservative approximation. For indexed entities, the `code_length` property from FalkorDB is used directly when available.

### 2.3 New Node: `assign_canonical_keys`

**Purpose**: Generate stable, path-based unique IDs for every node in the module tree.

**Algorithm**:
```python
def make_canonical_key(file_paths: list[str]) -> str:
    prefix = os.path.commonpath(file_paths)
    slug = prefix.strip('/').replace('/', '-').replace('_', '-').lower()
    # Deduplicate: if collision with existing key, append sorted entity_uids hash prefix (6 chars)
    if slug in existing_keys:
        uid_hash = hashlib.sha256("".join(sorted(entity_uids)).encode()).hexdigest()[:6]
        slug = f"{slug}-{uid_hash}"
    return slug  # e.g., "src-auth-login", "core-payment-service"
```

**Properties**:
- Deterministic: same files → same key
- Readable: derived from code paths
- Stable across LLM runs: no LLM involvement
- Solves Chinese domain linking: `canonical_key` replaces string matching throughout the pipeline

### 2.4 New Node: `generate_titles`

**Purpose**: Generate human-readable titles for each module node. This is where LLM is used for naming, but the structure is already locked.

**Input**: module_tree nodes with canonical_key + entity lists
**Output**: `state["canonical_keys"]` mapping (key → readable title)

```python
prompt = """
For each module, generate a concise Chinese title based on its code entities.
Module key: {canonical_key}
Code entities: {entity_names}
File paths: {file_paths}
Output: {"title": "简洁的中文标题", "description": "一句话描述"}
"""
```

**Key insight**: Even if LLM generates slightly different titles across runs, the `canonical_key` ensures linking always works. Title is for display only.

### 2.5 New Node: `compose_bottomup`

**Purpose**: Unified bottom-up generation replacing 4 separate nodes.

**Processing logic**:
```python
async def compose_bottomup_node(state, config):
    module_tree = state["module_tree"]
    domain_cache = state["domain_cache"]  # pipeline-level shared cache

    # Process in topological order: leaves first, then parents
    for node in module_tree.topological_order():
        if node.is_leaf():
            page = await generate_leaf_page(node, domain_cache, config)
        else:
            child_docs = [child.page for child in node.children]
            page = await synthesize_parent_page(node, child_docs, config)
        node.page = page
        state["pages"].append(page.to_dict())

    # Repository-level overview (top of the tree)
    all_top_docs = [n.page for n in module_tree.roots]
    overview = await synthesize_overview(all_top_docs, config)
    state["pages"].append(overview.to_dict())
```

**Leaf page generation** reuses existing `WikiPageAgent` + `WikiGenerationHarness`:
- Harness `domain_cache` is now injected from pipeline state (fixes P0 issue)
- Harness `gather` reuses `EnrichedDomainContext` from CCB (eliminates duplicate queries)

**Parent page synthesis** uses new `ParentSynthesizer`:
```python
class ParentSynthesizer:
    async def synthesize(self, node: ModuleNode, child_docs: list[WikiPage]) -> WikiPage:
        prompt = f"""
        Based on the following sub-module documents, generate a parent module overview for "{node.title}".

        Requirements:
        1. Summarize each sub-module's core responsibilities
        2. Explain collaboration relationships between sub-modules
        3. Generate architecture diagram (Mermaid)
        4. Link to sub-pages using canonical_key

        Sub-module documents:
        {format_child_docs(child_docs)}
        """
        content = await self.llm.generate(prompt)
        return WikiPage(
            path=node.canonical_key,
            title=node.title,
            content=content,
            page_type=PageType.DOMAIN_OVERVIEW,
            business_domain=node.canonical_key,
        )
```

### 2.6 WikiPageAgent Enhancement: `delegate_submodule` Tool

**Purpose**: Allow Agent to dynamically delegate complex sub-modules (aligns with CodeWiki's `generate_sub_module_documentation`).

```python
DELEGATE_TOOL = {
    "type": "function",
    "function": {
        "name": "delegate_submodule",
        "description": (
            "When the current module is too complex to document in one pass, "
            "delegate a sub-section to a specialized sub-agent. Returns the "
            "generated documentation for that sub-section."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "entity_names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Entity names to delegate (functions, classes)",
                },
                "focus": {
                    "type": "string",
                    "description": "What aspect to focus on (e.g., 'error handling', 'data flow')",
                },
            },
            "required": ["entity_names"],
        },
    },
}
```

Implementation creates a sub-WikiPageAgent with scoped entities and merges the output back.

**Guard rails**: Maximum delegation depth is 2 (agent → sub-agent, no further nesting). Total delegated calls per parent agent capped at 3. These limits prevent resource exhaustion while still enabling meaningful decomposition.

### 2.7 Evaluation Enhancement

**quality_gate L3** upgraded to 4-dimension LLM Judge (aligning with CodeWikiBench):

| Dimension | Score Range | Criteria |
|---|---|---|
| Completeness | 1-5 | Covers all key functionality, public APIs, data flow |
| Accuracy | 1-5 | Code references are correct, no hallucinated entities |
| Readability | 1-5 | Clear writing, good structure, appropriate diagrams |
| Structure | 1-5 | Logical organization, proper heading hierarchy, navigation |

**heal_pages enhancement**: Repair agent can now invoke tools (read_code, query_call_chain) to fetch missing information during repair, not just LLM rewrite.

---

## 3. Data Model Changes

### 3.1 New: ModuleNode / ModuleTree

```python
@dataclass
class ModuleNode:
    canonical_key: str           # path-based slug, e.g. "src-auth-login"
    entity_uids: list[str]       # FalkorDB entity UIDs in this module
    file_paths: list[str]        # source files covered
    title: str = ""              # human-readable title (from generate_titles)
    description: str = ""
    children: list[ModuleNode] = field(default_factory=list)
    page: WikiPage | None = None # populated by compose_bottomup
    token_estimate: int = 0

    def is_leaf(self) -> bool:
        return len(self.children) == 0

@dataclass
class ModuleTree:
    roots: list[ModuleNode]
    repo_id: str

    def topological_order(self) -> list[ModuleNode]:
        """Return nodes in bottom-up order (leaves first, roots last)."""
        ...

    def all_nodes(self) -> list[ModuleNode]:
        """Flatten tree to list."""
        ...
```

### 3.2 WikiPipelineState Additions

```python
class WikiPipelineState(TypedDict):
    # ... existing fields ...
    module_tree: list[dict[str, Any]]      # serialized ModuleTree
    canonical_keys: dict[str, str]          # canonical_key → title
    domain_cache: dict[str, str]            # pipeline-level shared domain cache
```

### 3.3 Persistence Changes

`wiki/persistence.py` — WikiPage nodes in FalkorDB gain `canonical_key` property:
```cypher
SET page.canonical_key = $canonical_key
```

`wiki/tree_linker.py` — `_find_best_domain()` replaced with:
```python
def _find_domain_by_key(self, canonical_key: str, domain_pages: list) -> WikiPage | None:
    for page in domain_pages:
        if getattr(page, 'canonical_key', '') == canonical_key:
            return page
    return None
```

---

## 4. File Change Manifest

### 4.1 New Files (3)

| File | Responsibility | Est. Lines |
|---|---|---|
| `wiki/graph_module_decomposer.py` | SCC + topological sort + CC + LLM clustering, canonical_key generation | ~300 |
| `wiki/parent_synthesizer.py` | LLM synthesis of parent docs from child docs | ~150 |
| `wiki/models/module_tree.py` | ModuleNode / ModuleTree dataclasses | ~80 |

### 4.2 Modified Files (8)

| File | Change Scope |
|---|---|
| `wiki/pipeline_graph.py` | Replace 6 nodes with 4 new nodes; rewire edges |
| `wiki/pipeline_state.py` | Add module_tree, canonical_keys, domain_cache fields |
| `wiki/pipeline_nodes.py` | Add graph_decompose_node, assign_keys_node, generate_titles_node, compose_bottomup_node |
| `wiki/page_agent.py` | Add delegate_submodule tool definition and implementation |
| `wiki/harness.py` | domain_cache constructor injection; gather reuses CCB output |
| `wiki/tree_linker.py` | Replace _find_best_domain with canonical_key exact match |
| `wiki/persistence.py` | Add canonical_key field persistence |
| `wiki/pipeline_orchestrator.py` | Adapt PipelineResult for new fields |

### 4.3 Deprecated Logic

| File | Deprecated Element | Replacement |
|---|---|---|
| `wiki/topic_structure_planner.py` | Structure planning logic | Retool as TitleGenerator (title-only generation) |
| `wiki/domain_overview_composer.py` | Template-based overview | ParentSynthesizer |
| `wiki/nodes/compose.py` | compose_leaf_pages_node, compose_parent_pages_node | compose_bottomup_node |

---

## 5. LLM Call Budget

For a repository with ~100 code files:

| Phase | LLM Calls | Granularity | Notes |
|---|---|---|---|
| graph_decompose (Step 4 only) | ~2 | Per oversized module | Only when CC can't split |
| generate_titles | ~15 | Per module node | Lightweight: title only |
| compose_leaf_modules | ~15 | Per leaf module | Existing: module summaries |
| compose_bottomup (leaf) | ~15 | Per leaf module | WikiPageAgent + Harness |
| compose_bottomup (parent) | ~8 | Per parent node | ParentSynthesizer |
| quality_gate L3 | ~5 | Core-tier pages only | Optional LLM Judge |
| **Total** | **~60** | | vs. current ~45 (moderate increase) |

The increase (~15 calls) comes from ParentSynthesizer, which replaces template filling with LLM synthesis — a quality improvement trade-off.

---

## 6. Testing Strategy

| Test Type | Target | Verification |
|---|---|---|
| Unit: GraphModuleDecomposer | SCC correctness, topological order, canonical_key format | Mock graph data → assert tree structure |
| Unit: ParentSynthesizer | Output format, child doc inclusion | Mock LLM → assert Markdown structure |
| Unit: ModuleTree | topological_order, all_nodes traversal | Constructed tree → assert order |
| Unit: delegate_submodule | Tool invocation and result merging | Mock sub-agent → assert content integration |
| Integration: Full pipeline | End-to-end with mock LLM | assert pages generated, canonical_keys present |
| Determinism | Same input × 3 runs | assert module_tree structure identical |
| Regression | Existing test suite | All existing tests pass |
| Chinese domain linking | Chinese domain names in module tree | assert tree_linker resolves all nodes |

---

## 7. Success Criteria

1. **Determinism**: Same codebase, 3 consecutive runs → identical module_tree structure (canonical_keys match)
2. **Chinese domain linking**: Zero orphaned nodes when domain names contain CJK characters
3. **Quality**: L3 LLM Judge average score ≥ 3.5/5.0 across 4 dimensions
4. **Regression**: All existing tests pass; no degradation in pipeline throughput
5. **CodeWiki alignment**: All CodeWiki paper capabilities either implemented or identified as our unique advantage (see alignment matrix in `2026-05-09-graph-driven-deterministic-decomposition.md` §6)

---

## 8. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| FalkorDB graph incomplete (missing DEPENDS_ON edges) | Medium | Module tree too flat | Fallback to file-path-based grouping when graph is sparse |
| SCC produces single giant component | Low | No splitting possible | LLM clustering fallback (Step 4) |
| ParentSynthesizer hallucination | Medium | Inaccurate parent docs | L3 evaluation catches; repair loop fixes |
| delegate_submodule infinite recursion | Low | Resource exhaustion | Max delegation depth = 2; guard in tool implementation |
| Pipeline state size increase (module_tree) | Low | Memory pressure | ModuleTree serialization is lightweight (~KB per module) |

---

## References

1. CodeWiki: Evaluating AI's Ability to Generate Holistic Documentation for Large-Scale Codebases. arXiv:2510.24428v6, ACL 2026. ([GitHub](https://github.com/FSoft-AI4Code/CodeWiki))
2. Previous analysis: `docs/superpowers/specs/2026-05-09-graph-driven-deterministic-decomposition.md`
