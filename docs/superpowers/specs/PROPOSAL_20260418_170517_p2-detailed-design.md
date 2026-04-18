# P2 Detailed Design Supplement — Wiki Generation

> **Status**: `[AwaitingApproval]`
> **Parent Spec**: `2026-04-17-wiki-generation-design.md` Section P2
> **Created**: 2026-04-18
> **Purpose**: Supplement the P2 high-level plan with executable technical design for all 14 identified gaps.

---

## Table of Contents

1. [Track A: Full Repo Wiki Generation](#track-a)
2. [Track B: Multi-LLM Provider](#track-b)
3. [Track C: Export + UI](#track-c)
4. [Test Plan](#test-plan)
5. [Subagent Dispatch Plan](#subagent-dispatch)
6. [Coverage Targets](#coverage-targets)
7. [Revised Effort Estimates](#effort-estimates)

---

## 1. Track A: Full Repo Wiki Generation {#track-a}

### 1.1 compose_repo_wiki() Data Flow (Gap #1)

```
[Trigger: scope="repo" + mode="full"|"structure"]
    │
    ▼
[1. Module Discovery]
    │ Query graph: MATCH (m:Module) WHERE m.repository=$repo RETURN m
    │ Sort by path; filter out test/vendor modules
    │
    ▼
[2. Architecture Layer Classification]
    │ Classify modules into layers using naming heuristics + graph edges:
    │   - API/Controller layer: modules with HTTP handler annotations or route patterns
    │   - Service/Business layer: modules with most CALLS edges to other service modules
    │   - Data/Repository layer: modules with DB/ORM imports
    │   - Infrastructure layer: config, util, middleware
    │   - Test layer: test directories (excluded from wiki)
    │
    ▼
[3. Recursive Page Generation]
    │ For each module in dependency order (leaf → root):
    │   a. Generate MODULE_OVERVIEW page (existing P1 flow)
    │   b. Generate CLASS_DETAIL pages for all classes in module
    │   c. Generate API_REFERENCE pages for public functions/endpoints
    │
    ▼
[4. Cross-Module Pages]
    │ a. REPO_OVERVIEW: top-level summary, module list, tech stack
    │ b. ARCHITECTURE_OVERVIEW: layer diagram, inter-module dependencies
    │ c. DATA_FLOW: key data pipelines traced via CALLS edges
    │
    ▼
[5. Context Injection + Cross-linking]
    │ a. Build hierarchical context (repo → module → page)
    │ b. Auto-link cross-references across all pages
    │ c. Generate glossary from all entity names
    │
    ▼
[6. Export Bundle]
    │ WikiExporter.export_json(all_pages, structure)
```

**Key design decisions:**
- Dependency order generation ensures parent summaries are available when composing children
- Architecture classification is **heuristic-first** (naming patterns + edge analysis), no LLM call required
- Concurrency: up to 3 modules composed in parallel, classes within a module sequential (glossary consistency)

### 1.2 New Page Type Templates (Gap #2)

PageType enum already defines all 6 types. Here are the detailed template structures:

#### ARCHITECTURE_OVERVIEW

```markdown
# Architecture Overview — {repository}

## System Layers
{mermaid: layered architecture diagram}

## Layer Details
### {layer_name} Layer
- **Modules**: {module_list}
- **Responsibilities**: {auto-generated from module summaries or structural description}
- **Key Dependencies**: {inter-layer dependency list}

## Inter-Module Dependencies
{mermaid: module dependency graph, full repo scope}

## Technology Stack
- Languages: {detected from file extensions}
- Frameworks: {detected from import patterns}
- External Dependencies: {from imports/requires}
```

| Section | Data Source | Mermaid Type |
|---------|-----------|-------------|
| System Layers | `GraphQueryService.find_module_dependencies()` + layer classifier | `graph TD` (top-down layered) |
| Layer Details | Module nodes + their relationships | None (text) |
| Inter-Module Dependencies | All IMPORTS edges between modules | `flowchart LR` |
| Technology Stack | File extensions + import patterns from graph | None (text) |

#### DATA_FLOW

```markdown
# Data Flow — {flow_name}

## Overview
{one-paragraph description of this data pipeline}

## Flow Diagram
{mermaid: call flowchart showing data transformation steps}

## Stages
### Stage 1: {entry_point}
- **Component**: {class/function name}
- **Input**: {parameter types}
- **Output**: {return type or side effect}
- **Source**: {source_location_link}

## Data Transformations
| Step | Component | Transform | Source |
|------|-----------|-----------|--------|
| 1 | {name} | {input → output} | {link} |
```

| Section | Data Source | Mermaid Type |
|---------|-----------|-------------|
| Flow Diagram | `GraphQueryService.find_call_chain()` from entry points | `flowchart LR` |
| Stages | Node properties + method signatures | None (table) |

**Entry point detection**: Functions/methods with no inbound CALLS edges within the module, or annotated as API endpoints.

#### API_REFERENCE (enhanced from P1)

```markdown
# API Reference — {module_name}

## Endpoints / Public Functions
| Name | Signature | Description | Source |
|------|-----------|-------------|--------|
| {fn_name} | `{signature}` | {summary} | {source_link} |

## Request/Response Models
### {model_name}
{fields table with types}

## Usage Examples
{LLM-generated or structural code snippet}
```

#### REPO_OVERVIEW (enhanced from P1)

```markdown
# {repository} — Project Wiki

## Overview
{LLM summary or structural description of the entire repository}

## Architecture
{brief architecture summary with link to Architecture Overview page}

## Module Index
| Module | Description | Classes | Functions |
|--------|-------------|---------|-----------|
| {module} | {summary} | {count} | {count} |

## Quick Links
- [Architecture Overview](architecture/overview.md)
- [Data Flows](data-flows/index.md)
```

### 1.3 Incremental Update Algorithm (Gap #3)

```
[Git Push / Re-index Event]
    │
    ▼
[1. Diff Extraction]
    │ Reuse IncrementalIndexer._get_changed_files():
    │   git diff --name-status base_ref head_ref
    │   Returns: list[(status, old_path, new_path)]
    │
    ▼
[2. File → Graph Node Mapping]
    │ For each changed file:
    │   Query: MATCH (n)-[:DEFINED_IN]->(f:File {path: $path})
    │          WHERE n.repository = $repo
    │          RETURN n.uid, n.name, labels(n)
    │   Result: set of affected node UIDs
    │
    ▼
[3. Neighbor Expansion (1-hop)]
    │ For each affected node:
    │   Query: MATCH (n {uid: $uid})-[:CALLS|INHERITS|IMPORTS]-(neighbor)
    │          RETURN neighbor.uid
    │   Add neighbors to "potentially affected" set
    │   (Neighbors may need context updates even if their code didn't change)
    │
    ▼
[4. Wiki Page Resolution]
    │ Map affected UIDs → Wiki page paths:
    │   - Class UID → classes/{fqn_slug}.md
    │   - Module UID → modules/{path}.md
    │   - If a module has >30% classes affected, regenerate entire module overview
    │
    ▼
[5. Selective Regeneration]
    │ For each affected page:
    │   a. Re-collect data (DataCollector)
    │   b. Re-compose content (Composer, with existing glossary)
    │   c. Re-export (Exporter, update cross-refs)
    │   d. Update cache entry
    │
    ▼
[6. Consistency Guard]
    │ a. Glossary: diff new glossary vs old; if >20% terms changed, regenerate all pages
    │ b. Cross-refs: scan all pages for broken links after update; fix any stale refs
    │ c. Context: re-inject parent context only for pages whose parent changed
```

**Consistency Guard Rules:**

| Guard | Trigger | Action |
|-------|---------|--------|
| Glossary drift | >20% terms added/removed | Full glossary rebuild + all pages refresh context |
| Broken cross-refs | Any `[text](path)` pointing to deleted page | Remove link or redirect to parent |
| Stale parent context | Parent module page regenerated | Re-inject updated parent summary into children |
| Version stamp | Any regeneration | Increment graph_version_hash |

### 1.4 Consistency Guard Detailed Design (Gap #4)

```python
@dataclass
class IncrementalUpdateResult:
    affected_pages: list[str]       # page paths regenerated
    neighbor_pages: list[str]       # pages with context-only update
    glossary_refreshed: bool        # True if full glossary rebuild triggered
    broken_refs_fixed: int          # number of cross-refs repaired
    pages_unchanged: int            # pages confirmed up-to-date
    graph_version: int              # new version after update

class WikiIncrementalUpdater:
    def __init__(self, service: WikiService, store: FalkorDBStore):
        ...

    async def update_from_diff(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],  # (status, old_path, new_path)
    ) -> IncrementalUpdateResult:
        ...

    async def _map_files_to_nodes(self, repository: str, file_paths: list[str]) -> set[str]:
        """Map file paths to graph node UIDs via DEFINED_IN edges."""
        ...

    async def _expand_neighbors(self, uids: set[str]) -> set[str]:
        """1-hop neighbor expansion for context propagation."""
        ...

    async def _check_glossary_drift(self, old_glossary: dict, new_glossary: dict) -> bool:
        """Return True if >20% terms changed, triggering full rebuild."""
        ...
```

---

## 2. Track B: Multi-LLM Provider {#track-b}

### 2.1 Provider Abstract Interface (Gap #5)

```python
from abc import ABC, abstractmethod
from typing import AsyncIterator

class BaseLLMProvider(ABC):
    """Abstract base for all LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def supports_streaming(self) -> bool: ...

    @property
    @abstractmethod
    def max_context_tokens(self) -> int: ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        **kwargs,
    ) -> str: ...

    @abstractmethod
    async def complete_json(
        self,
        messages: list[dict[str, str]],
        schema: dict,
        *,
        model: str | None = None,
        **kwargs,
    ) -> dict: ...

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        **kwargs,
    ) -> AsyncIterator[str]:
        """Optional streaming. Default: yield full response."""
        yield await self.complete(messages, **kwargs)

    @abstractmethod
    async def close(self) -> None: ...
```

**Concrete implementations:**

| Provider | Class | Endpoint |
|----------|-------|----------|
| Gateway (default) | `GatewayLLMProvider` | Existing gateway WebSocket/HTTP |
| OpenAI Direct | `OpenAIProvider` | `https://api.openai.com/v1` |
| Azure OpenAI | `AzureOpenAIProvider` | `https://{resource}.openai.azure.com/` |
| Custom Compatible | `CustomOpenAIProvider` | User-supplied `base_url` |

### 2.2 Provider Selection Strategy (Gap #6)

```python
@dataclass
class ProviderConfig:
    default_provider: str = "gateway"  # "gateway" | "openai" | "azure" | "custom"
    fallback_provider: str | None = None
    providers: dict[str, dict] = field(default_factory=dict)
    # Example:
    # providers:
    #   openai:
    #     api_key: "sk-..."
    #     model: "gpt-4o"
    #   azure:
    #     api_key: "..."
    #     resource_name: "my-resource"
    #     deployment_name: "gpt-4o"
    #   custom:
    #     base_url: "http://localhost:8080/v1"
    #     api_key: "..."

class LLMProviderFactory:
    """Factory for creating LLM providers with fallback chain."""

    def __init__(self, config: ProviderConfig):
        self._config = config
        self._providers: dict[str, BaseLLMProvider] = {}

    def get_provider(self, name: str | None = None) -> BaseLLMProvider:
        """Get provider by name, or default."""
        target = name or self._config.default_provider
        if target not in self._providers:
            self._providers[target] = self._create(target)
        return self._providers[target]

    async def complete_with_fallback(self, messages, **kwargs) -> str:
        """Try default provider, fallback on failure."""
        try:
            return await self.get_provider().complete(messages, **kwargs)
        except Exception:
            if self._config.fallback_provider:
                return await self.get_provider(self._config.fallback_provider).complete(messages, **kwargs)
            raise
```

**Selection logic:**
- **Default**: `settings.llm.provider` (global config), defaults to `"gateway"` for backward compatibility
- **Per-request override**: `WikiGenerateBody.llm_provider` field (optional)
- **Fallback**: if primary fails, try `settings.llm.fallback_provider`
- **Model mapping**: each provider has its own default model; override via `model` parameter

### 2.3 Security Controls (Gap #7)

| Action | Required Role | Rationale |
|--------|-------------|-----------|
| Use default provider | `VIEWER` | Read-only wiki generation |
| Switch provider per-request | `ADMIN` | Provider switching may have cost implications |
| Configure provider credentials | `ADMIN` (via settings) | Security-sensitive |
| View available providers | `VIEWER` | Informational |

**Implementation:**
- Add `llm_provider: str | None = None` to `WikiGenerateBody` (optional, defaults to global config)
- In `wiki_generate` endpoint: if `body.llm_provider` is set and differs from default, check `require_role(Role.ADMIN)`
- Provider API keys stored in `config.py` / environment variables only (never in API request)

---

## 3. Track C: Export + UI {#track-c}

### 3.1 P1 Overlap Assessment (Gap #14)

| P2 Task | P1 Already Implemented | P2 Remaining Work |
|---------|----------------------|-------------------|
| T-C1 MD file export | `WikiExporter.export_markdown_fileset()` | **Disk write orchestration**: actual file I/O to `docs/wiki/` + git-friendly directory structure + index.md generation |
| T-C2 Wiki cache layer | `WikiCache` (in-memory LRU, key=(repo,scope,mode,version)) | **Persistent layer**: file-based or Redis cache for surviving process restarts |

**Revised effort:**
- T-C1: 0.5d (only disk I/O + index.md, core logic exists)
- T-C2: 1d (persistent cache layer on top of existing LRU)

### 3.2 Persistent Cache Design (Gap #8)

**Strategy: Two-tier cache (Memory LRU + File-based persistence)**

```
┌─────────────────┐     ┌──────────────────────┐
│ Memory LRU (P1) │────→│ File Cache (P2)       │
│ Fast, volatile   │     │ JSON files on disk    │
│ Max 100 entries  │     │ Survives restarts     │
│ WikiCache        │     │ WikiPersistentCache   │
└─────────────────┘     └──────────────────────┘
```

```python
class WikiPersistentCache:
    """File-based persistent cache for wiki pages."""

    def __init__(self, cache_dir: str = ".wiki_cache"):
        self._dir = Path(cache_dir)
        self._dir.mkdir(parents=True, exist_ok=True)

    def _key_path(self, repo: str, scope: str, mode: str, version: int) -> Path:
        key = f"{repo}__{scope}__{mode}__{version}"
        return self._dir / f"{hashlib.sha256(key.encode()).hexdigest()[:16]}.json"

    def get(self, repo, scope, mode, version) -> list[WikiPage] | None:
        path = self._key_path(repo, scope, mode, version)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        if data.get("version") != version:
            path.unlink(missing_ok=True)
            return None
        return [WikiPage.from_dict(p) for p in data["pages"]]

    def put(self, repo, scope, mode, version, pages: list[WikiPage]) -> None:
        path = self._key_path(repo, scope, mode, version)
        data = {"version": version, "pages": [p.to_dict() for p in pages]}
        path.write_text(json.dumps(data, ensure_ascii=False))

    def invalidate(self, repo: str) -> None:
        """Remove all cache files for a repository."""
        for path in self._dir.glob(f"{repo}__*"):
            path.unlink(missing_ok=True)
```

**Why file-based over Redis:**
- Redis is already used by FalkorDB; adding wiki cache to Redis would couple wiki lifecycle to DB lifecycle
- File cache is simpler, sufficient for single-instance P2 deployment
- P3 can add Redis-backed cache if multi-instance needed

### 3.3 Dashboard Wiki Page Architecture (Gap #9)

**Existing dashboard:** React 19 + Vite 8 + TypeScript + Tailwind v4 + TanStack Query + React Router v7.

**New route:** `/wiki` → `WikiPage` component

```
┌─────────────────────────────────────────────────────────────────┐
│ WikiPage                                                         │
│ ┌──────────────┐ ┌──────────────────────────────────────────┐   │
│ │ WikiSidebar  │ │ WikiContent                              │   │
│ │              │ │ ┌──────────────────────────────────────┐ │   │
│ │ TreeView     │ │ │ Breadcrumbs                          │ │   │
│ │ (directory)  │ │ ├──────────────────────────────────────┤ │   │
│ │              │ │ │ MarkdownRenderer                     │ │   │
│ │ SearchBar    │ │ │  - react-markdown                    │ │   │
│ │ (P1.5 API)  │ │ │  - remark-mermaid plugin             │ │   │
│ │              │ │ │  - Source location links (IDE deep)  │ │   │
│ │              │ │ ├──────────────────────────────────────┤ │   │
│ │              │ │ │ DiagramPanel (Mermaid.js)            │ │   │
│ │              │ │ └──────────────────────────────────────┘ │   │
│ │              │ │                                          │   │
│ │              │ │ ┌──────────────────────────────────────┐ │   │
│ │              │ │ │ AskSidebar (collapsible)             │ │   │
│ │              │ │ │  - Chat input                        │ │   │
│ │              │ │ │  - SSE answer stream                 │ │   │
│ │              │ │ │  - Source references                  │ │   │
│ │              │ │ └──────────────────────────────────────┘ │   │
│ └──────────────┘ └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

**Components:**

| Component | Library | Backend API |
|-----------|---------|-------------|
| TreeView | Custom recursive component | `GET /api/v1/wiki/{repo}/pages` |
| MarkdownRenderer | `react-markdown` + `rehype-raw` | Content from page detail API |
| MermaidPlugin | `mermaid` (CDN or bundled) | Diagram data from page response |
| SearchBar | Custom input + dropdown | `POST /api/v1/wiki/search` |
| AskSidebar | Custom chat UI | `POST /api/v1/wiki/ask` (SSE) |
| IDE Deep Links | `<a href="vscode://...">` | `source_locations` from page |
| Breadcrumbs | React Router based | Path segments from URL |

**IDE link configuration:**
```typescript
const editorTemplates: Record<string, (path: string, line: number) => string> = {
  vscode: (p, l) => `vscode://file/${p}:${l}`,
  cursor: (p, l) => `cursor://file/${p}:${l}`,
  idea: (p, l) => `idea://open?file=${p}&line=${l}`,
};
// User selects preferred editor in Settings page
```

### 3.4 DeepResearch Mode Definition (Gap #10)

**DeepResearch** is a multi-turn investigation mode that uses the MCP Agent path to recursively explore code.

**Flow:**
1. User asks a complex question (e.g., "How does the authentication flow work end-to-end?")
2. System runs initial Ask query
3. If answer references entities not yet explored, automatically issues follow-up searches
4. Builds a research tree with sources
5. Synthesizes a comprehensive answer from all exploration branches

**Scope for P2:** Basic multi-turn investigation using existing Ask API with automatic follow-up. No MCP Agent integration in P2 (deferred to P3).

**P2 implementation:**
```python
class DeepResearchService:
    """Multi-turn investigation using iterative Ask + Search."""

    async def research(
        self,
        repository: str,
        question: str,
        max_depth: int = 3,
        max_branches: int = 5,
    ) -> AsyncIterator[dict]:
        """Yields progress events + final synthesis."""
        ...
```

**Deferred to P3:** MCP Agent integration for autonomous code exploration beyond wiki content.

---

## 4. Test Plan (Gap #11) {#test-plan}

### Track A Tests

#### test_repo_wiki_generation.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_compose_repo_discovers_modules` | Repo with 3 modules | Returns pages for all 3 modules |
| `test_compose_repo_architecture_classification` | Modules with different naming | Correct layer assignment |
| `test_compose_repo_dependency_order` | A→B→C module deps | C generated before B before A |
| `test_compose_repo_overview_page` | Full repo | REPO_OVERVIEW page with module index |
| `test_compose_repo_architecture_page` | Full repo | ARCHITECTURE_OVERVIEW with layer diagram |
| `test_compose_repo_concurrent_limit` | 10 modules | Max 3 composed in parallel |

#### test_page_types.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_architecture_overview_has_layer_diagram` | Mock graph | Mermaid graph TD with layers |
| `test_architecture_overview_tech_stack` | Files with .java/.py | Detected languages listed |
| `test_data_flow_from_entry_point` | Call chain A→B→C | Mermaid flowchart with 3 stages |
| `test_data_flow_no_entry_points` | Module with no public funcs | Graceful empty flow |
| `test_api_reference_lists_public` | Class with 3 public, 2 private | Only 3 in reference table |
| `test_repo_overview_module_index` | 5 modules | Table with 5 rows + counts |

#### test_incremental_update.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_diff_single_file_modified` | 1 file changed | Only affected page regenerated |
| `test_diff_file_deleted` | 1 file deleted | Page removed, cross-refs cleaned |
| `test_diff_neighbor_expansion` | Class A modified, B calls A | Both A and B pages updated |
| `test_diff_module_threshold` | >30% classes in module changed | Module overview regenerated |
| `test_glossary_drift_trigger` | >20% terms changed | Full glossary rebuild |
| `test_glossary_stable` | <20% terms changed | No rebuild |
| `test_broken_ref_cleanup` | Page deleted, ref exists | Ref removed from linking page |
| `test_version_stamp_increment` | Any change | graph_version incremented |

### Track B Tests

#### test_llm_providers.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_gateway_provider_complete` | Valid messages | String response via gateway |
| `test_openai_provider_complete` | Valid messages | String response via OpenAI API |
| `test_azure_provider_complete` | Valid messages | String response via Azure endpoint |
| `test_custom_provider_complete` | Valid messages + base_url | String response via custom endpoint |
| `test_provider_factory_default` | No name | Returns gateway provider |
| `test_provider_factory_named` | name="openai" | Returns OpenAI provider |
| `test_provider_fallback_on_error` | Primary fails | Falls back to secondary |
| `test_provider_fallback_none` | Primary fails, no fallback | Raises original error |
| `test_provider_api_permission` | VIEWER tries to switch | 403 Forbidden |
| `test_provider_admin_switch` | ADMIN switches provider | Success |

### Track C Tests

#### test_persistent_cache.py

| Test Case | Input | Expected |
|-----------|-------|----------|
| `test_file_cache_put_get` | Put then get | Returns same pages |
| `test_file_cache_miss` | Get nonexistent | Returns None |
| `test_file_cache_version_mismatch` | Old version file | Returns None, file deleted |
| `test_file_cache_invalidate_repo` | Invalidate repo | All repo files removed |
| `test_two_tier_memory_then_disk` | Miss memory, hit disk | Returns from disk, populates memory |

#### test_wiki_dashboard.py (E2E, Playwright)

| Test Case | Scenario | Expected |
|-----------|----------|----------|
| `test_wiki_page_loads` | Navigate to /wiki | Sidebar tree + content area |
| `test_wiki_tree_navigation` | Click module in tree | Page content updates |
| `test_wiki_mermaid_renders` | Page with diagram | Mermaid SVG visible |
| `test_wiki_search` | Type in search bar | Results dropdown appears |
| `test_wiki_ask_chat` | Submit question in Ask sidebar | Streaming answer appears |
| `test_wiki_ide_link` | Click source location | IDE link format correct |
| `test_wiki_breadcrumbs` | Navigate deep page | Breadcrumb path correct |

---

## 5. Subagent Dispatch Plan (Gap #12) {#subagent-dispatch}

```
Phase 7: P2 — Track A + Track B (parallel)
════════════════════════════════════════════

┌──────────────────────────────────────┐  ┌──────────────────────────────────┐
│ Subagent-15: T-A1 compose_repo [2d] │  │ Subagent-18: T-B1 Provider       │
│                                      │  │  Abstraction [1d]                │
│ TDD:                                 │  │                                  │
│  test_repo_wiki_generation.py        │  │ TDD:                             │
│  → wiki/repo_composer.py             │  │  test_llm_providers.py           │
│                                      │  │  → llm/base_provider.py          │
│ Gate: repo compose tests pass        │  │  → llm/provider_factory.py       │
│       coverage ≥80%                  │  │                                  │
└──────────────────────────────────────┘  │ Gate: provider tests pass        │
                                          │       backward compat verified   │
Subagent-16: T-A2 New Page Types [3d]    └──────────────────────────────────┘
  Depends: Subagent-15
  TDD: test_page_types.py               Subagent-19: T-B2+B3 OpenAI/Azure/
  → wiki/page_templates.py                Custom Providers [2d]
  Gate: all 4 page type tests pass        Depends: Subagent-18
        snapshot tests stable             TDD: extend test_llm_providers.py
                                          Gate: all provider tests pass

Subagent-17: T-A3 Incremental [5d]      Subagent-20: T-B4 Provider Config [0.5d]
  Depends: Subagent-15                     Depends: Subagent-19
  TDD: test_incremental_update.py          TDD: test_provider_api.py
  → wiki/incremental.py                    Gate: API + permission tests pass
  Gate: all incremental tests pass
        consistency guard verified

Phase 8: P2 — Track C
═══════════════════════

Subagent-21: T-C1+C2 Export + Cache [1.5d]
  Depends: Subagent-15
  TDD: test_persistent_cache.py + test_disk_export.py
  → wiki/persistent_cache.py + wiki/disk_exporter.py
  Gate: cache + export tests pass

Subagent-22: T-C3 Dashboard Wiki Page [7d]
  Depends: Subagent-21 + P1.5 complete
  Components: WikiPage, WikiSidebar, MarkdownRenderer, AskSidebar
  Gate: E2E tests pass (Playwright)

Phase 9: P2 Integration
════════════════════════

Subagent-23: P2 Integration Tests [2d]
  - Run ALL tests
  - Verify all 3 tracks work together
  - Full regression check
  Gate: overall coverage ≥80%, zero regressions
```

---

## 6. Coverage Targets (Gap #13) {#coverage-targets}

| Module | Minimum Coverage | Rationale |
|--------|-----------------|-----------|
| `wiki/repo_composer.py` | 80% | Orchestration with async concurrency |
| `wiki/page_templates.py` | 90% | Template correctness critical |
| `wiki/incremental.py` | 85% | Complex diff/mapping logic |
| `llm/base_provider.py` | 90% | Interface contract |
| `llm/provider_factory.py` | 85% | Factory + fallback logic |
| `wiki/persistent_cache.py` | 90% | Cache correctness critical |
| `dashboard/src/pages/Wiki.tsx` | N/A | Frontend covered by E2E |
| **Overall wiki module** | **≥80%** | **Project quality gate** |

---

## 7. Revised Effort Estimates (Gap #14 partial) {#effort-estimates}

| Task | Original | Revised | Justification |
|------|----------|---------|---------------|
| T-A1 | 2d | 2d | Reasonable, P1 infrastructure solid |
| T-A2 | 3d | 3d | 4 page types with templates + Mermaid |
| T-A3 | 3.5d | **5d** | Consistency Guard is complex; neighbor propagation + glossary drift detection |
| T-B1 | 1d | 1d | Clean refactoring with Protocol |
| T-B2 | 1.5d | 1.5d | OpenAI + Azure both use httpx |
| T-B3 | 0.5d | 0.5d | Trivial subclass |
| T-B4 | 0.5d | 0.5d | API field + permission check |
| T-C1 | 1d | **0.5d** | P1 already implemented export_markdown_fileset |
| T-C2 | 1.5d | **1d** | File-based on top of existing LRU |
| T-C3 | 5d | **7d** | Frontend with 7 sub-features |
| Integration | (implicit) | **2d** | Full regression + cross-track verification |
| **Total** | **~3 weeks** | **~4.5 weeks** | More realistic with complexity adjustments |

---

## Approval Checklist

- [ ] Track A: compose_repo_wiki data flow approved
- [ ] Track A: New page type templates approved
- [ ] Track A: Incremental update algorithm approved
- [ ] Track B: Provider interface + factory approved
- [ ] Track B: Security controls approved
- [ ] Track C: Persistent cache design approved
- [ ] Track C: Dashboard architecture approved
- [ ] Subagent dispatch plan approved
- [ ] Effort estimates approved
