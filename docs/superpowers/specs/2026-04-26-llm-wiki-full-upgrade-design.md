# LLM Wiki Full Upgrade Design

> From AI doc generator to self-maintaining LLM knowledge base.

**Created**: 2026-04-26  
**Status**: Draft  
**Scope**: 6 sub-projects covering architecture hardening, incremental ingest, agent interface, quality automation, and knowledge compilation.

---

## 1. Background & Motivation

### 1.1 Current State

The Knowledge Base Service generates wiki documentation from indexed code repositories using LLM-powered composition. Key capabilities:

- Multi-repo wiki generation with importance tiering (Core/Standard/Skeleton)
- Cross-repo business domain classification via LLM
- Graph-enhanced Q&A with 5 question-type strategies
- Wiki reference network and quality scoring
- Version history, annotations, SSE real-time updates
- Memory Loop for Q&A persistence
- Git push export

### 1.2 Gap Analysis (vs Karpathy LLM Wiki + DeepWiki)

Three fundamental gaps prevent the system from being a true LLM Wiki:

| # | Gap | Current | LLM Wiki Standard |
|---|-----|---------|-------------------|
| 1 | **Incremental Update** | Full regeneration only | Selective page update on source change |
| 2 | **Agent Interface** | Browser UI only | MCP tools + AGENTS.md schema |
| 3 | **Self-Maintenance** | Manual lint only | Automated lint/heal background worker |

Additional gaps: Memory Loop not fed into generation, no cross-entity knowledge compilation, no deep research mode, no user feedback loop.

### 1.3 Architecture & Code Quality Issues

**Backend**: ConversationStore not multi-worker safe, config injection inconsistent, broad exception handling, FalkorDB tight coupling.

**Frontend**: No error boundaries, no code splitting for heavy components (xyflow ~200KB), query cache keys too broad, dual MarkdownRenderer, tab bar missing ARIA tablist semantics.

---

## 2. Sub-Project Overview

```
SP1 + SP2 (parallel) → SP3 + SP4 (parallel) → SP5 → SP6

SP1: Backend Architecture Hardening     (S effort, no deps)
SP2: Frontend Architecture Hardening    (S effort, no deps)
SP3: Incremental Ingest Pipeline        (L effort, depends on SP1)
SP4: Agent/MCP Interface Layer          (M effort, depends on SP1)
SP5: Automated Lint/Heal + Quality Loop (M effort, depends on SP3)
SP6: Knowledge Compilation + Deep Research (L effort, depends on SP3+SP4)
```

---

## 3. SP1: Backend Architecture Hardening

### 3.1 Typed Domain Exception Hierarchy

Create `api/exceptions.py`:

```python
class KbError(Exception):
    """Base for all knowledge-base domain errors."""
    status_code: int = 500
    def __init__(self, message: str, *, detail: str | None = None):
        self.message = message
        self.detail = detail
        super().__init__(message)

class KbClientError(KbError):
    status_code = 400

class KbNotFound(KbError):
    status_code = 404

class KbConflict(KbError):
    status_code = 409

class KbServiceUnavailable(KbError):
    status_code = 503

class KbForbidden(KbError):
    status_code = 403
```

Register a global FastAPI exception handler in `api/error_handler.py` that catches `KbError` subclasses and returns the appropriate HTTP response. Route handlers raise typed exceptions; they never construct HTTP responses for error cases.

**Migration**: Replace all `raise HTTPException(...)` in route modules with the corresponding `KbError` subclass. Preserve existing error messages.

### 3.2 Request-Scoped Context

Introduce `api/request_context.py` using `contextvars`:

```python
from contextvars import ContextVar

_business_id: ContextVar[str] = ContextVar("business_id", default="default")
_request_id: ContextVar[str] = ContextVar("request_id", default="")

def get_current_business() -> str: ...
def get_current_request_id() -> str: ...
```

Set values in `RequestLoggingMiddleware`. Service-layer code that currently receives `business_id` as a function parameter can optionally read from context as a fallback. Explicit parameters remain preferred for testability.

### 3.3 Configuration DI Unification

- `get_settings()` calls must only appear in `lifespan`, FastAPI dependency functions, and `create_app()`.
- Service constructors accept configuration slices (e.g., `WikiService` receives `wiki_config: WikiSettings` rather than calling `get_settings().wiki` internally).
- Test code creates config objects directly, no monkey-patching required.

### 3.4 ConversationStore Persistence

Replace in-memory `OrderedDict` with `aiosqlite`-backed store:

```
Table: conversations
  conversation_id TEXT PRIMARY KEY,
  repository TEXT,
  scope TEXT,
  turns_json TEXT,
  last_active REAL,
  created_at REAL
```

- TTL eviction via `last_active` column (same 30-minute default).
- LRU capacity limit via `DELETE ... ORDER BY last_active LIMIT ...`.
- Fallback to in-memory store if SQLite file is not writable.
- Database path configurable via `Settings.conversation_db_path` (default: `data/conversations.db`).

### 3.5 Test Plan

- Unit tests for each exception type → HTTP status mapping.
- Unit tests for request context set/get across async boundaries.
- Integration test: ConversationStore SQLite persistence survives process restart simulation.
- Verify no `get_settings()` calls remain in service-layer files (grep check).

---

## 4. SP2: Frontend Architecture Hardening

### 4.1 Error Boundary

Create `dashboard/src/components/ErrorBoundary.tsx`:
- Catches render errors in children.
- Displays a styled card with error message and "Retry" button.
- Logs error details to console with component stack.

Wrap these components:
- `WikiShell` (top-level wiki error boundary)
- `WikiContent` (protects content rendering from markdown/mermaid errors)
- `MarkdownRenderer` (innermost, catches per-render failures)

### 4.2 React.lazy Code Splitting

Lazy-load heavy components behind `Suspense` with loading skeletons:

| Component | Estimated Bundle | Trigger |
|-----------|-----------------|---------|
| `WikiReferenceGraph` | ~200KB (xyflow + dagre) | `toolTab === "refgraph"` |
| `WikiDiffViewer` | ~80KB | Version diff opened |
| `GraphInsightsPanel` | ~60KB | `toolTab === "insights"` |

### 4.3 Query Key Scoping

Standardize all TanStack Query keys to include `businessId`:

```typescript
// Before
queryKey: ["wiki"]

// After
queryKey: ["wiki", "pages", businessId, pagePath]
queryKey: ["wiki", "tree", businessId, viewType]
queryKey: ["wiki", "coverage", businessId]
queryKey: ["wiki", "quality-score", businessId]
queryKey: ["wiki", "references", businessId, pageUid]
```

Cache invalidation targets specific scopes rather than all wiki queries.

### 4.4 Tab Semantics

WikiShell toolbar receives proper ARIA roles:

```tsx
<div role="tablist" aria-label={t.wiki.tabListLabel}>
  <button role="tab" aria-selected={toolTab === "page"} aria-controls="wiki-panel-page">
    ...
  </button>
  ...
</div>
<div role="tabpanel" id="wiki-panel-page" aria-labelledby="wiki-tab-page">
  {/* panel content */}
</div>
```

Regenerate button receives `aria-busy={regeneratePending}`.

### 4.5 MarkdownRenderer Unification

Merge `dashboard/src/components/MarkdownRenderer.tsx` (root) and `dashboard/src/components/wiki/MarkdownRenderer.tsx` into a single component at the wiki path.

Root-level import sites switch to `import MarkdownRenderer from "../components/wiki/MarkdownRenderer"`. Wiki-specific features (wikilink resolution, annotation highlighting) activate via props:
- `wikiLinkParams?: Record<string, string>` (present = wiki mode)
- `headings?: ParsedHeading[]` (present = skip re-parsing)

### 4.6 Regeneration Hook Extraction

Extract `handleRegenerateWiki` from WikiShell into `useWikiRegenerate(businessId)` hook. The hook returns `{ regenerate, isPending, status }`.

### 4.7 Test Plan

- Unit test: ErrorBoundary catches thrown error and renders fallback.
- Integration test: lazy-loaded WikiReferenceGraph renders after Suspense resolves.
- Verify all query keys include businessId (grep check).
- Accessibility test: tab navigation works with ARIA roles.

---

## 5. SP3: Incremental Ingest Pipeline

### 5.1 Change Detection

New module `wiki/change_detector.py`:

```python
@dataclass
class AffectedPageSet:
    page_uids: list[str]
    affected_entities: list[str]
    trigger: str  # "git_push" | "manual" | "scheduled"
    files_changed: list[str]
    impact_radius: int  # 1-hop default

class ChangeDetector:
    def __init__(self, graph: GraphPort, wiki_store: WikiStore):
        ...

    async def detect_from_git_diff(
        self, repository: str, diff_output: str
    ) -> AffectedPageSet:
        """Parse git diff --name-status output, find affected entities."""
        ...

    async def detect_from_file_list(
        self, repository: str, changed_files: list[str]
    ) -> AffectedPageSet:
        """Direct file list input (for webhook payloads)."""
        ...
```

Detection algorithm:
1. Parse changed file paths from git diff.
2. Query graph: `MATCH (e) WHERE e.file IN $files RETURN e.uid, e.name`.
3. Expand 1-hop via CALLS/IMPORTS edges: `MATCH (e)-[:CALLS|IMPORTS*1]-(neighbor) WHERE e.uid IN $uids RETURN DISTINCT neighbor.uid`.
4. Find WikiPages linked via SOURCE_ENTITY: `MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(e) WHERE e.uid IN $all_uids RETURN wp.uid`.

### 5.2 Selective Regeneration

New method `WikiService.generate_incremental()`:

```python
async def generate_incremental(
    self,
    repository: str,
    affected: AffectedPageSet,
    language: str = "en",
    llm_provider: str | None = None,
) -> IncrementalResult:
    """Regenerate only affected wiki pages. Preserve annotations on unchanged pages."""
    ...
```

Behavior:
- Only compose pages whose UIDs are in `affected.page_uids`.
- Unchanged pages: no modification (annotations, version preserved).
- Changed pages: version +1, new `generated_at`, content regenerated.
- New entities (files added): generate new WikiPage nodes.
- Deleted entities (files removed): mark WikiPage as `deprecated: true` rather than deleting.

### 5.3 Change Audit Log

New graph node type `WikiChangeLog`:

```
(:WikiChangeLog {
  uid: "changelog:<business_id>:<timestamp>",
  business_id: str,
  repository: str,
  timestamp: str (ISO 8601),
  trigger: "git_push" | "manual" | "scheduled",
  files_changed: int,
  entities_affected: int,
  pages_regenerated: int,
  pages_deprecated: int,
  summary: str (LLM-generated change summary, 1-2 sentences)
})
```

Linked to affected WikiPages via `(:WikiChangeLog)-[:UPDATED]->(:WikiPage)`.

### 5.4 Webhook Integration

Extend `api/routes/webhook_routes.py`:
- Accept Git push webhook payload (GitHub/GitLab format).
- Extract changed file list from payload.
- Call `ChangeDetector.detect_from_file_list()`.
- Enqueue incremental generation task.

### 5.5 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/wiki/ingest` | Trigger incremental ingest with file list or git ref |
| GET | `/api/v1/wiki/changelog` | Paginated change audit log |
| GET | `/api/v1/wiki/changelog/{log_uid}` | Single changelog detail |

### 5.6 Test Plan

- Unit test: ChangeDetector correctly identifies affected entities from diff output.
- Unit test: 1-hop expansion finds transitive dependencies.
- Integration test: generate_incremental preserves unchanged pages and their annotations.
- Integration test: Webhook triggers incremental ingest end-to-end.

---

## 6. SP4: Agent/MCP Interface Layer

### 6.1 MCP Server

New module `api/mcp_wiki_server.py` implementing MCP (Model Context Protocol) server:

| Tool Name | Input | Output | Description |
|-----------|-------|--------|-------------|
| `wiki_search` | `{query, business_id, limit?, max_tokens?}` | `{results: [{title, path, snippet, score}]}` | Semantic search across wiki pages |
| `wiki_explain` | `{entity_name, business_id, compact?}` | `{definition, relationships[], signatures[], key_facts[]}` | Structured entity explanation |
| `wiki_navigate` | `{path?, business_id, depth?}` | `{tree: [{uid, title, type, children[]}]}` | Browse wiki tree structure |
| `wiki_qa` | `{question, business_id, conversation_id?}` | `{answer, sources[], conversation_id}` | Q&A with conversation memory |
| `wiki_impact` | `{file_path, business_id}` | `{affected_pages[], affected_entities[]}` | Change impact analysis |

### 6.2 Compact Knowledge Format

When `compact=true` or `max_tokens` is specified, return structured JSON optimized for LLM context windows:

```json
{
  "entity": "WikiAskService",
  "type": "class",
  "module": "wiki/ask.py",
  "definition": "Interactive wiki Q&A service with hybrid search and graph-enhanced context.",
  "relationships": [
    {"type": "depends_on", "target": "WikiSearchService"},
    {"type": "depends_on", "target": "MemoryLoop"},
    {"type": "used_by", "target": "wiki_routes.wiki_ask_stream"}
  ],
  "signatures": [
    "async def ask_stream(repository, question, scope?, ...) -> AsyncIterator[dict]",
    "async def ask(repository, question, ...) -> AskResponse"
  ],
  "key_facts": [
    "Supports 5 question types: concept, flow, relation, impact, general",
    "Graph-enhanced context collection with token budget management",
    "Conversation history with LRU eviction (200 max, 30min TTL)"
  ]
}
```

### 6.3 AGENTS.md Auto-Generation

New module `wiki/agents_md_generator.py`:

Auto-generates project-level `AGENTS.md` from wiki metadata:

```markdown
# Project Knowledge Base

## Overview
{business wiki overview page content, summarized}

## Key Modules
| Module | Description | Wiki Path |
|--------|-------------|-----------|
| auth.py | Authentication and authorization | /wiki/auth |
| ... | ... | ... |

## How to Query
- Search: `wiki_search("how does authentication work?")`
- Explain: `wiki_explain("AuthService")`
- Impact: `wiki_impact("auth.py")`

## Wiki Structure
- business_domain/ — Business domain overviews
- code_structure/ — Per-repository technical documentation
```

Regenerated after each wiki generation. Stored as a WikiPage with `page_type: "agents_md"`.

### 6.4 Test Plan

- Unit test each MCP tool with mock data.
- Integration test: MCP server responds to tool calls via stdio transport.
- Test compact mode token budget enforcement.
- Verify AGENTS.md generation includes all indexed repositories.

---

## 7. SP5: Automated Lint/Heal + Quality Loop

### 7.1 Lint Scheduler

New module `wiki/lint_scheduler.py`:

```python
class LintScheduler:
    def __init__(
        self,
        lint_factory: Callable[[], Awaitable[WikiLintService]],
        interval_hours: float = 6.0,
        run_after_generation: bool = True,
    ): ...

    async def start(self) -> None: ...
    async def stop(self) -> None: ...
    async def run_once(self) -> LintReport: ...
```

Integrated into `lifespan` alongside existing `SyncScheduler`.

### 7.2 Auto-Heal Actions

| Lint Finding | Severity | Auto-Action |
|-------------|----------|-------------|
| Stale page (source newer than page) | HIGH | Queue for incremental regeneration |
| Orphan page (no SOURCE_ENTITY) | MEDIUM | Mark `deprecated: true`, exclude from search |
| Broken reference | MEDIUM | Remove broken ref edge, log warning |
| Low coverage section | LOW | Add to regeneration priority queue |
| Contradiction detected | HIGH | Create admin notification, no auto-fix |

### 7.3 Memory Loop Generation Injection

Modify `WikiComposer.compose_page()`:

```python
async def compose_page(self, page_data, page_type, config, parent_context=""):
    # ... existing context building ...

    # Inject relevant Q&A memories
    if self._memory_loop is not None:
        enriched_context = await self._memory_loop.inject_into_generation(
            context_str, business_id=config.repository
        )
        context_str = enriched_context

    # ... LLM generation ...
```

This closes the learning loop: User asks question → Answer recorded → Next generation incorporates the Q&A → Wiki proactively addresses common questions.

### 7.4 User Feedback System

**Backend**:

New graph node `WikiFeedback`:
```
(:WikiFeedback {
  uid, page_uid, rating: "up"|"down", comment: str,
  author: str, created_at: str
})
-[:FEEDBACK_ON]->(:WikiPage)
```

API endpoints:
- `POST /api/v1/wiki/pages/{page_uid}/feedback` — Submit feedback
- `GET /api/v1/wiki/feedback/summary` — Aggregate feedback stats

**Frontend**:

Add thumbs up/down buttons to WikiContent footer. Optional text feedback on "down" vote. Display aggregate feedback count on WikiQualityScoreCard.

**Generation impact**: Pages with net-negative feedback receive 1.5x token budget on next generation.

### 7.5 Test Plan

- Unit test: LintScheduler executes at configured interval.
- Unit test: Auto-heal actions (stale → regenerate, orphan → deprecate).
- Integration test: Memory Loop injection produces richer wiki content.
- Integration test: Feedback submission and aggregation.

---

## 8. SP6: Knowledge Compilation + Deep Research

### 8.1 Cross-Entity Concept Merging

New module `wiki/concept_merger.py`:

1. After all per-repo wiki pages are generated, run concept detection.
2. Query: `MATCH (e1:WikiPage), (e2:WikiPage) WHERE e1.repository <> e2.repository` with embedding similarity > 0.9.
3. For matched pairs, generate a `ConceptPage` that synthesizes both descriptions.
4. ConceptPage includes: unified definition, per-repo differences, cross-references.

Output: New `WikiPage` nodes with `page_type: "concept"` and edges to source pages.

### 8.2 Inline Wikilinks

Modify `WikiComposer` LLM prompt to include an entity index:

```
When referencing these known entities, use [[EntityName]] notation:
- AuthService (wiki/auth/AuthService)
- UserRepository (wiki/store/UserRepository)
- ...
```

Post-processing in `WikiExporter`:
- Regex-match `[[EntityName]]` in generated content.
- Replace with actual wiki path links: `[EntityName](/wiki/path/to/entity)`.
- Unresolved links logged as warnings.

### 8.3 Deep Research Mode

Extend `WikiAskService` with `ask_deep_research()`:

```python
async def ask_deep_research(
    self,
    repository: str,
    question: str,
    max_rounds: int = 5,
    business_id: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Multi-turn investigative research.

    1. Decompose question into sub-questions
    2. Search wiki for each sub-question
    3. Synthesize findings
    4. Generate follow-up questions if gaps remain
    5. Produce final research report
    """
```

SSE events:
- `research:plan` — Initial sub-question decomposition
- `research:finding` — Per sub-question result
- `research:synthesis` — Intermediate synthesis
- `research:report` — Final compiled report

Frontend: New "Deep Research" tab or mode toggle in AskPanel.

### 8.4 Business Flow Visualization

Reuse `@xyflow/react` (already in WikiReferenceGraph):

- Query `BusinessFlow` nodes from graph.
- Render as directed flowchart: entry points → processing steps → outputs.
- Each step node links to its wiki page.
- Color-coding by domain.

New component: `WikiBusinessFlowGraph.tsx`, lazy-loaded.

### 8.5 Test Plan

- Unit test: Concept merger identifies similar entities across repos.
- Unit test: Wikilink post-processing resolves known entities and flags unknown.
- Integration test: Deep research produces multi-round results.
- Verify business flow nodes render correctly with mock data.

---

## 9. Migration & Compatibility

### 9.1 Database Schema Changes

| Change | Type | Migration |
|--------|------|-----------|
| `WikiChangeLog` node type | Addition | Auto-created on first ingest |
| `WikiFeedback` node type | Addition | Auto-created on first feedback |
| `ConceptPage` page_type | Addition | New value in WikiPage.page_type |
| `conversations` SQLite table | Addition | Created on first use |
| `WikiPage.deprecated` property | Addition | Default `false` for existing pages |

All changes are additive. No breaking changes to existing graph data.

### 9.2 API Compatibility

All new endpoints are additive. No changes to existing endpoint signatures. Existing clients (dashboard, tests) require no modifications for SP1-SP3.

SP4 (MCP) is a new communication channel, independent of REST API.

### 9.3 Feature Flags

Each sub-project's features can be independently enabled/disabled via `config.Settings`:

```python
class WikiSettings(BaseModel):
    incremental_ingest_enabled: bool = False
    mcp_server_enabled: bool = False
    lint_scheduler_enabled: bool = False
    deep_research_enabled: bool = False
    concept_merging_enabled: bool = False
    feedback_enabled: bool = False
```

---

## 10. Success Criteria

| Sub-Project | Metric | Target |
|-------------|--------|--------|
| SP1 | Zero `get_settings()` in service layer | 0 calls |
| SP1 | Exception types cover all HTTP error paths | 100% |
| SP2 | Largest JS chunk (excluding vendor) | < 150KB |
| SP2 | All query keys include businessId | 100% |
| SP3 | Incremental ingest time vs full generation | < 30% |
| SP3 | Unchanged page annotations preserved | 100% |
| SP4 | MCP tools respond within | < 2s p95 |
| SP4 | AGENTS.md covers all indexed repos | 100% |
| SP5 | Lint auto-heal rate | > 60% of findings |
| SP5 | Memory-enriched pages mention Q&A topics | Qualitative |
| SP6 | Concept pages generated for cross-repo entities | > 0 |
| SP6 | Deep research produces cited report | Qualitative |
