# Comprehensive Audit Fix Proposal

**Created:** 2026-04-19T13:35:29  
**Status:** Implementing (Approved with revisions via Sequential Thinking review)  
**Scope:** Backend Quality + Dashboard UX + Agent Context Precision

### Review Revisions Applied
1. U11/U12 moved from Sprint 5 to Sprint 1 (trivial, do immediately)
2. B5: Use `_estimate_tokens` pattern (len//4) instead of tiktoken (avoid heavy dep)
3. B9: New fields are optional, no backfill required for existing nodes
4. B1: Will be split into sub-items (B1a/B1b/B1c) given complexity
5. A4: Must include `max_tokens` parameter to prevent oversized responses
6. Execution order: Phase A (Sprint 1 + trivial) → Phase B (Sprint 2 ∥ Sprint 3) → Phase C (Sprint 4) → Phase D (Sprint 5)

---

## 1. Background

Full audit of `knowledge-base-service` identified 28 improvement items across 3 dimensions:
- **Backend (B1–B10):** Retrieval quality, error handling, NLP preprocessing
- **Dashboard UX (U1–U12):** Exploration, navigation, developer experience
- **Agent Context Precision (A1–A6):** Reducing hallucination for coding agents

This proposal organizes all items into prioritized sprints based on impact/effort ratio, targeting the core goal: **users quickly explore project details, agents get precise context, code without hallucination**.

---

## 2. Priority Classification

### Sprint 1: High Impact / Quick Wins (Backend + Agent)

These directly affect retrieval precision and agent context quality — the highest-value improvements.

- [ ] **B7: Unified Error Response Format**
  - **Impact:** Security + API quality
  - **Effort:** Low (1-2h)
  - **Design:** Create `ErrorResponse` model; wrap all route exceptions in `error_handler` middleware
  - **Files:** `main.py`, new `api/error_handler.py`

- [ ] **B4: Robust LLM JSON Parsing**
  - **Impact:** Deep Search reliability
  - **Effort:** Low (1h)
  - **Design:** Add `json-repair` dependency; refactor `_parse_json_object_from_llm` to use it as fallback
  - **Files:** `query/deep_search.py`, `pyproject.toml`

- [ ] **A2: "No Results" Confidence Signal**
  - **Impact:** Agent hallucination prevention
  - **Effort:** Low (1h)
  - **Design:** When semantic_matches is empty, add `"confidence": 0.0, "no_results_reason": "..."` to response
  - **Files:** `api/mcp_server.py`, `query/hybrid_query.py`

- [ ] **A3: Source Line-Level References in graph_context**
  - **Impact:** Agent code precision
  - **Effort:** Low (1h)
  - **Design:** Propagate `start_line`/`end_line` from graph nodes into all `graph_context` items
  - **Files:** `query/hybrid_query.py`, `query/graph_query.py`

- [ ] **B9: Index Freshness Metadata**
  - **Impact:** Agent & User trust
  - **Effort:** Low (1-2h)
  - **Design:** Store `indexed_at` timestamp and `commit_sha` on graph nodes during indexing; expose in API responses and MCP
  - **Files:** `indexer/incremental_indexer.py`, `store/schema.py`, `api/mcp_server.py`

- [ ] **A6: Index Freshness MCP Tool**
  - **Impact:** Agent trust
  - **Effort:** Low (1h)
  - **Design:** New MCP tool `index_freshness(repository)` returning `last_indexed_at`, `commit_sha`, `node_count`
  - **Files:** `api/mcp_server.py`

### Sprint 2: Medium Impact / Search Quality (Backend)

- [ ] **B2: Query Router with Intent Classification**
  - **Impact:** Retrieval precision
  - **Effort:** Medium (3-4h)
  - **Design:** Reuse and extend `wiki/ask.py::detect_question_type` into `query/query_router.py`; route different intents to different search strategies (keyword-heavy for code lookup, semantic-heavy for concept, graph-first for flow)
  - **Files:** New `query/query_router.py`, modify `query/hybrid_query.py`

- [ ] **B5: Dynamic Synthesis Token Budget**
  - **Impact:** Deep Search quality
  - **Effort:** Low (1h)
  - **Design:** Replace hardcoded `[:4000]` with tiktoken-based token counting; use configurable budget from `Settings`
  - **Files:** `query/deep_search.py`, `config.py`

- [ ] **B6: Embedding Query Cache**
  - **Impact:** Performance
  - **Effort:** Low (1h)
  - **Design:** Add LRU cache (256 entries) on `EmbeddingGenerator.generate_for_query` keyed by query text
  - **Files:** `indexer/embedding_generator.py`

- [ ] **B8: Context Relevance Confidence Score**
  - **Impact:** Agent precision
  - **Effort:** Medium (2h)
  - **Design:** Compute normalized confidence from RRF score + reranker score; include in semantic_matches as `confidence: float`
  - **Files:** `query/hybrid_query.py`, `search/fusion.py`

- [ ] **A4: One-Stop Context Assembly MCP Tool**
  - **Impact:** Agent efficiency (reduce MCP call count)
  - **Effort:** Medium (3h)
  - **Design:** New MCP tool `get_complete_context(entity_name, repository?)` that assembles: code snippet + docstring + call chain (1 hop) + class hierarchy + business flows + wiki page content. Single call replaces 4-5 current calls.
  - **Files:** `api/mcp_server.py`, new `query/context_assembler.py`

- [ ] **A5: Dynamic Token Budget for Wiki Ask**
  - **Impact:** Answer quality
  - **Effort:** Low (1h)
  - **Design:** `WikiAskService` estimates question complexity from token count + question_type; adjusts budget (4000-12000)
  - **Files:** `wiki/ask.py`

### Sprint 3: High Impact / UX Enhancement (Dashboard)

- [ ] **U1: Global Command Palette (⌘K)**
  - **Impact:** User efficiency
  - **Effort:** Medium (3-4h)
  - **Design:** New `CommandPalette.tsx` component; listens for ⌘K/Ctrl+K; delegates to hybrid search API; shows results with type icons; keyboard navigation
  - **Files:** New `dashboard/src/components/CommandPalette.tsx`, modify `Layout.tsx`

- [ ] **U5: Wiki Page TOC Navigation**
  - **Impact:** Wiki usability
  - **Effort:** Medium (2-3h)
  - **Design:** Extract headings from markdown AST in `MarkdownRenderer`; render floating right-side TOC with scroll-spy active state
  - **Files:** New `dashboard/src/components/wiki/TableOfContents.tsx`, modify `WikiContent.tsx`

- [ ] **U7: Search Keyword Highlighting**
  - **Impact:** Search UX
  - **Effort:** Low (1-2h)
  - **Design:** Create `HighlightText` utility component; wrap name/docstring/content in `SearchResultCard` with highlights
  - **Files:** New `dashboard/src/components/HighlightText.tsx`, modify `SearchResultCard.tsx`

- [ ] **U2: Human-Readable Graph Context**
  - **Impact:** Search comprehension
  - **Effort:** Medium (2-3h)
  - **Design:** Replace raw `JsonView` with `GraphContextCards.tsx` showing relationship cards (e.g. "→ calls FooService.bar()" with file/line links)
  - **Files:** New `dashboard/src/components/GraphContextCards.tsx`, modify `SearchPage.tsx`

- [ ] **U8: Knowledge Health Dashboard**
  - **Impact:** Trust & monitoring
  - **Effort:** Medium (2-3h)
  - **Design:** New section in Overview page showing: index coverage %, last update time, orphan entity %, avg chunk quality score. Uses existing `/stats` + new `/stats/health` endpoint.
  - **Files:** New backend `GET /api/v1/stats/health`, modify `Overview.tsx`

### Sprint 4: Medium-Effort Enhancements

- [ ] **B1: Parent-Child Chunk Strategy**
  - **Impact:** Retrieval precision (high)
  - **Effort:** High (6-8h)
  - **Design:** For code: current AST chunks become "parent"; add sub-function-level chunks (logical blocks, ~200 tokens) as "child" with parent_uid reference. Retrieval searches children, returns parent for context completeness.
  - **Files:** `indexer/code_graph_builder.py`, `store/schema.py`, `query/semantic_query.py`

- [ ] **B10: Chinese NLP Preprocessing**
  - **Impact:** Chinese search quality
  - **Effort:** Medium (2-3h)
  - **Design:** Add `jieba` dependency; in `hybrid_query._extract_identifiers` and FTS preprocessing, detect CJK and apply segmentation
  - **Files:** `query/hybrid_query.py`, `wiki/search.py`, `pyproject.toml`

- [ ] **U3: Onboarding Quick Start**
  - **Impact:** New user activation
  - **Effort:** Medium (2-3h)
  - **Design:** Add `QuickStartBanner` to Overview; shows step indicators: ① Index a repo → ② Explore search → ③ Read Wiki → ④ Ask questions; dismissed after completion; stores state in localStorage
  - **Files:** New `dashboard/src/components/QuickStartBanner.tsx`, modify `Overview.tsx`

- [ ] **U4: Graph Explorer Enhancement**
  - **Impact:** Exploration depth
  - **Effort:** Medium (3-4h)
  - **Design:** Add node type filter chips, edge label visibility toggle, property detail panel on node click, minimap legend
  - **Files:** `dashboard/src/pages/GraphExplorer.tsx`

- [ ] **U6: Ask Panel Conversation History**
  - **Impact:** Continuity
  - **Effort:** Medium (2-3h)
  - **Design:** Store conversations in localStorage keyed by repository; show history list in AskPanel sidebar; support switching conversations
  - **Files:** Modify `dashboard/src/components/wiki/AskPanel.tsx`, new `useConversationHistory.ts` hook

### Sprint 5: Polish & Cleanup

- [ ] **U9: File Upload Entry**
  - **Impact:** Convenience
  - **Effort:** Medium (3h)
  - **Design:** Add drag-drop file upload zone on Indexing page; frontend sends to `POST /index/files`
  - **Files:** `dashboard/src/pages/Indexing.tsx`

- [ ] **U10: Dark Mode Support**
  - **Impact:** Developer experience
  - **Effort:** Medium (3-4h)
  - **Design:** Add dark mode toggle in Settings/Layout header; use Tailwind `dark:` variants; persist preference in localStorage
  - **Files:** `dashboard/src/index.css`, multiple components

- [ ] **U11: Remove Dead Code (GraphFlowChart)**
  - **Impact:** Codebase hygiene
  - **Effort:** Trivial (5min)
  - **Design:** Delete `dashboard/src/components/GraphFlowChart.tsx` if no imports reference it
  - **Files:** Delete `GraphFlowChart.tsx`

- [ ] **U12: Verify/Fix Typography Plugin**
  - **Impact:** Markdown rendering quality
  - **Effort:** Trivial (10min)
  - **Design:** Check if Tailwind v4 bundles typography; if not, `pnpm add @tailwindcss/typography`
  - **Files:** `dashboard/package.json`

- [ ] **B3: Retrieval Quality Evaluation Framework**
  - **Impact:** Long-term quality
  - **Effort:** High (6-8h)
  - **Design:** New `eval/` directory with ground-truth Q&A pairs, automated scoring (hit_rate, MRR, NDCG), comparison across config changes
  - **Files:** New `eval/` module

---

## 3. Implementation Approach

- **TDD:** Each backend item writes tests first, then implements
- **Subagent parallel:** Independent sprint items run concurrently via Task subagents
- **Code review:** Each sprint completes with review before commit
- **Incremental delivery:** Sprint 1 commits first (highest ROI)

---

## 4. Test Plan

### Backend Tests
- [ ] `test_error_handler.py` — verify no internal stack traces leak
- [ ] `test_deep_search_json_repair.py` — malformed JSON recovery
- [ ] `test_hybrid_no_results_confidence.py` — empty results include confidence signal
- [ ] `test_graph_context_line_refs.py` — graph_context items have start_line/end_line
- [ ] `test_query_router.py` — intent classification routes to correct strategy
- [ ] `test_embedding_cache.py` — cache hits skip computation
- [ ] `test_context_assembler.py` — one-stop context returns all sections
- [ ] `test_index_freshness.py` — freshness metadata accuracy

### Dashboard Tests
- [ ] Manual: ⌘K opens command palette, shows results, keyboard navigation works
- [ ] Manual: Wiki TOC floats right, scroll-spy highlights active section
- [ ] Manual: Search highlights match keywords in results
- [ ] Manual: Graph context shows readable cards instead of JSON

---

## 5. Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Parent-child chunk requires schema migration | Support both old/new schema during transition |
| json-repair may not handle all LLM output | Keep current parser as secondary fallback |
| ⌘K conflicts with system shortcuts | Use customizable keybinding |
| Breaking API changes for MCP consumers | Add new fields additively; never remove |
