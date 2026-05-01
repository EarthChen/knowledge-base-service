# Design Spec: Architecture Cleanup & Frontend UX Fixes

> **Status**: Approved  
> **Created**: 2026-05-01  
> **Source**: `DEEP_ANALYSIS_20260501_085742_wiki_gaps_and_bugs.md`  
> **Scope**: Low-cost architecture fixes (A1-A3, A5, A7-A9) + Frontend UX (i18n, SSE, AskPanel context)

---

## 1. Scope Definition

### In Scope (Low Cost)

**Backend Architecture Cleanup:**

| ID | Task | Files | Approach |
|----|------|-------|----------|
| A1 | Reuse SystemOverviewComposer in pipeline | `pipeline_nodes.py`, `system_overview_composer.py` | Replace thin `synthesize_overviews_node` impl with `SystemOverviewComposer.compose()` |
| A2 | Break circular dependency | `page_composer_service.py`, `service.py` | Extract shared helpers to `wiki/helpers.py` |
| A3 | Clean up stale prompts.py templates | `prompts.py` | Delete unused `TOPIC_STRUCTURE_PROMPT`; keep `DOMAIN_CLASSIFY_PROMPT` only if tests migrate to it |
| A5 | Consolidate LLMPort Protocol | `context.py`, `topic_page_composer.py`, `contradiction_detector.py` | Single canonical `LLMPort` in `context.py`; others import from it |
| A7 | Rename `collect_modules` node | `pipeline_graph.py` | Rename to `classify_entity_roles` |
| A8 | Make compose concurrency configurable | `pipeline_nodes.py`, `config.py` | Read from `wiki_config` or `config_overrides` |
| A9 | Remove dead `domain_mapping` parameter | `pipeline_nodes.py` | Remove unused param from `_normalize_domain_tree` |

**Frontend UX Fixes:**

| ID | Task | Files | Approach |
|----|------|-------|----------|
| A10 | i18n unification | 12+ wiki components | Replace hardcoded zh/en strings with `t.wiki.*` keys |
| SSE | SSE disconnect UI feedback | `useWikiEvents.ts`, `WikiShell.tsx` | Add connection state (connected/reconnecting/disconnected) indicator |
| P3a | AskPanel page context injection | `WikiToolPanel.tsx`, `AskPanel.tsx`, `useWikiAsk.ts` | Pass `currentPageContent` to AskPanel; include as context in ask API call |

### Out of Scope (High Cost, Separate Sprint)

- A4: CoT pipeline integration
- A6: Quality gate layering (L1/L2/L3)
- T1-T8: Technical capability gaps
- C1-C4: CodeWiki-style features

---

## 2. Backend Architecture Cleanup — Detailed Design

### 2.1 A1: Reuse SystemOverviewComposer

**Current state**: `synthesize_overviews_node` builds a thin system prompt from first 200 chars of each domain's first page. `SystemOverviewComposer` has a full 7-section prompt but is not used by the LangGraph pipeline.

**Change**:
1. In `synthesize_overviews_node`, instantiate `SystemOverviewComposer` and call `compose()`
2. Pass domain summaries (extracted from generated pages) and repo info
3. Convert result to the same dict format the pipeline expects

**Constraints**:
- `SystemOverviewComposer.compose()` is async and accepts `domain_summaries`, `repo_infos`, etc.
- Must build these inputs from pipeline state (`domain_tree`, `pages`, `modules`)
- Fallback: if `SystemOverviewComposer` fails, use current thin implementation

### 2.2 A2: Break Circular Dependency

**Current state**: `page_composer_service.py` lazy-imports `_collect_nodes_by_depth` and similar helpers from `wiki.service`.

**Change**:
1. Identify all functions imported from `wiki.service` by `page_composer_service.py`
2. Move them to `wiki/helpers.py`
3. Both `service.py` and `page_composer_service.py` import from `helpers.py`

### 2.3 A3: Clean Up prompts.py

**Current state**: `TOPIC_STRUCTURE_PROMPT` is completely unused. `DOMAIN_CLASSIFY_PROMPT` is only used in tests.

**Change**:
1. Delete `TOPIC_STRUCTURE_PROMPT`
2. Keep `DOMAIN_CLASSIFY_PROMPT` + `versioned_prompt` + `prompt_hash` utilities (they're useful infrastructure)
3. Add deprecation comment noting production uses inline prompts in planners

### 2.4 A5: Consolidate LLMPort

**Current state**: `LLMPort` Protocol defined in `context.py`. Similar protocols exist in `topic_page_composer.py` and `contradiction_detector.py` (`_LlmPort`).

**Change**:
1. Keep canonical `LLMPort` in `context.py`
2. In `topic_page_composer.py` and `contradiction_detector.py`, import from `context.py`
3. Remove local `_LlmPort` definitions

### 2.5 A7: Rename collect_modules Node

**Change**: In `pipeline_graph.py`, rename `"collect_modules"` to `"classify_entity_roles"`. Update all edge references.

### 2.6 A8: Configurable Concurrency

**Change**: Replace `_COMPOSE_CONCURRENCY = 5` with a value read from config:
```python
_COMPOSE_CONCURRENCY = int(os.environ.get("WIKI__COMPOSE_CONCURRENCY", "5"))
```

### 2.7 A9: Dead Parameter Removal

**Change**: Remove `domain_mapping` parameter from `_normalize_domain_tree` if unused internally.

---

## 3. Frontend UX Fixes — Detailed Design

### 3.1 A10: i18n Unification

**Components to fix** (12+):

| Component | Hardcoded Strings | Fix |
|-----------|------------------|-----|
| WikiDomainReviewPanel | "域树待审阅", "批准", "个模块", "重新生成此域", "子域" | Use `t.wiki.domain_review.*` |
| WikiToolPanel | "域树待审阅", "展开域审阅面板", "收起域审阅" | Use `t.wiki.domain_review.*` |
| WikiShell | "主题树", "代码结构" | Use `t.wiki.sidebar.*` |
| WikiTopicTreeNav | "暂无主题内容", zh aria-labels | Use `t.wiki.topic_tree.*` |
| WikiTopicContent | REVIEW_LABELS, "请选择", "通过", "提交", "取消" | Use `t.wiki.topic_content.*` |
| WikiKnowledgeGraph | "加载中...", "加载失败", "暂无域关系数据" | Use `t.wiki.knowledge_graph.*` |
| WikiBusinessFlowGraph | "Loading flows..." | Use `t.wiki.business_flow.*` |
| RelatedPages | "See Also" | Use `t.wiki.related_pages.*` |
| ClaimHistoryPanel | "Claim history", "(superseded)" | Use `t.wiki.claims.*` |

**Approach**:
1. Add all keys to the i18n locale files (zh + en)
2. Replace hardcoded strings with `t()` calls
3. Replace zh aria-labels with i18n keys

### 3.2 SSE Disconnect UI Feedback

**Current state**: `useWikiEvents` has reconnect logic but no UI indicator.

**Change**:
1. Add connection state to `useWikiEvents` return value: `'connected' | 'reconnecting' | 'disconnected'`
2. In `WikiShell`, render a subtle connection indicator based on state
3. Show reconnecting toast/banner with backoff timer

### 3.3 AskPanel Page Context Injection

**Current state**: AskPanel receives `repository` prop but no page content context.

**Change**:
1. Add `pageContext?: string` prop to AskPanel
2. Pass `currentPage.content` (truncated to reasonable limit) from WikiToolPanel
3. In `useWikiAsk`, prepend page context to the ask request body
4. Backend `wiki/ask.py` already supports `context` parameter — verify and wire

---

## 4. Implementation Order

1. **Backend batch** (parallel, independent changes): A2, A3, A5, A7, A8, A9
2. **Backend A1** (depends on understanding SystemOverviewComposer API)
3. **Frontend i18n** (A10, bulk string replacement)
4. **Frontend SSE** (small isolated change)
5. **Frontend AskPanel context** (P3a, requires API verification)

---

## 5. Testing Strategy

- Backend: Existing tests must pass after changes; add tests for renamed node
- Frontend: TypeScript compilation check; existing tests must pass
- Manual: Verify i18n strings render correctly in both zh/en locales

---

## 6. Success Criteria

- [ ] No circular dependency between `page_composer_service` and `service`
- [ ] `synthesize_overviews_node` uses `SystemOverviewComposer`
- [ ] `TOPIC_STRUCTURE_PROMPT` deleted from prompts.py
- [ ] Single `LLMPort` definition in `context.py`
- [ ] Node renamed to `classify_entity_roles` in pipeline graph
- [ ] Compose concurrency configurable via env var
- [ ] Dead parameter removed
- [ ] All 12+ components use i18n instead of hardcoded strings
- [ ] SSE connection status visible to user
- [ ] AskPanel receives page content as context
- [ ] All existing tests pass
