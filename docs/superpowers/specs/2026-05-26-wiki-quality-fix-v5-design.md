# Wiki Quality Fix v5 — Design Spec

**Date:** 2026-05-26
**Updated:** 2026-05-26 (V6 audit corrections)
**Status:** Approved
**Audit Source:** `docs/wiki-quality-audit.md` V5+V6 sections, `scripts/audit_result_v6.json`
**Scope:** Full fix for F1, F2, F4, F5 (Topic generation, domain filtering, term consistency, skeleton rejection). F3 resolved.

---

## Problem Statement

V5 audit (post V4 fixes) revealed 4 issues:

| ID | Problem | Severity | Data | Status |
|----|---------|----------|------|--------|
| F1 | Topic pages completely missing | P0 | 35 domains × 0 topics | Open |
| F2 | 10 infrastructure/class-name domains as top-level business domains | P1 | `backdoorserviceimpl`, `package-info`, `family-data-access-and-cache`, etc. | Open |
| F3 | ~~Tree structure incomplete~~ | ~~P1~~ | ~~0 Section→Page edges~~ | **RESOLVED (V6: audit script bug)** |
| F4 | Term inconsistency (LLM mistranslations) + parent hallucination | P2 | "关闭好友" instead of "挚友"; invented components in parent overviews | Open |
| F5 | Skeleton/empty pages published silently | P1 | `family-guild-rank-square` 472 chars | **NEW** |

> **V6 Update:** F3 was a false positive. The V5 audit script only queried `WikiSection→WikiSection` edges, missing `WikiSection→WikiPage` edges. Actual state: 55 Section→Page edges exist, 0 orphan pages. Fixed in `scripts/audit_wiki_data.py`.

---

## F1: Restore Topic Page Generation (P0)

### Root Cause

`DocOrchestrator.generate()` calls `plan_topics()` which may produce a topic split plan, but the result is stored in `memory.topic_outline` and never used for actual multi-page writing. The single-body write loop produces one overview page, and `_maybe_split()` is suppressed by `topic_split_done=True` flag + content being under `MAX_PAGE_TOKENS`.

The actual topic writing method `_write_with_outline()` only exists in the deprecated `use_orchestrator_template=False` branch.

### Design

**Hook pattern:** Add `_write_topics()` hook to `DocOrchestrator`, override in `DomainDocAgent`.

```
DocOrchestrator.generate():
  1. explore(memory)
  2. plan_topics(memory, module_names) → topic_plan
  3. NEW: pages = await self._write_topics(topic_plan, baseline_context, memory, module_names)
     3a. if pages is not None → return pages (skip single-body write)
     3b. if pages is None → fallback to existing single-body write loop
  4. (existing) single-body write loop → post_process → _maybe_split
```

### File Changes

#### `wiki/agents/doc_orchestrator.py`

Add default hook (returns None):
```python
async def _write_topics(
    self, topic_plan: list[Any] | None, baseline_context: str,
    memory: Any, module_names: list[str],
) -> list[dict[str, Any]] | None:
    """Hook for topic-based writing. Override in subclass to enable."""
    return None
```

Modify `generate()` after `plan_topics()` call:
```python
topic_plan = await self.plan_topics(memory, module_names)
if topic_plan is not None and hasattr(memory, "topic_outline"):
    memory.topic_outline = topic_plan

# Topic-based writing branch
if topic_plan is not None:
    pages = await self._write_topics(
        topic_plan, baseline_context, memory, module_names,
    )
    if pages is not None:
        return pages

# Fallback: single-body write loop (existing code unchanged)
```

#### `wiki/domain_doc_agent.py`

Store full outline in `plan_topics()`:
```python
async def plan_topics(self, memory, module_names):
    if len(module_names) <= 5:
        return None
    outline = await self._plan_topics(module_names, memory)
    if outline.should_split and len(outline.topics) > 1:
        self._topic_split_done = True
        self._topic_outline = outline  # NEW
        return outline.topics
    return None
```

Override `_write_topics()`:
```python
async def _write_topics(self, topic_plan, baseline_context, memory, module_names):
    from core.config import get_settings
    if not get_settings().wiki.enable_topic_pages:
        return None
    outline = getattr(self, "_topic_outline", None)
    if outline is None or not outline.should_split or len(outline.topics) <= 1:
        return None
    pages = await self._write_with_outline(outline, baseline_context, memory, module_names)
    _inject_executive_summaries(pages)
    return pages
```

#### `core/config.py`

```python
enable_topic_pages: bool = Field(
    default=True,
    description="Enable topic page generation in Orchestrator path",
)
```

### Tests

1. `test_orchestrator_calls_write_topics_when_plan_exists` — mock plan_topics returning topics, assert _write_with_outline called
2. `test_orchestrator_fallback_when_no_plan` — plan_topics returns None, assert single-body write path used
3. `test_enable_topic_pages_false_skips` — config flag off, assert returns None
4. `test_write_topics_output_structure` — verify returned pages contain 1 overview + N topics with correct page_type

---

## F2: Infrastructure Domain Filtering (P1)

### Root Cause

Domain decomposition treats all module clusters equally. Utility classes, config beans, TypeHandlers, and AOP aspects get promoted to top-level business domains.

V6 audit identified **10 definite infrastructure domains** (up from 8 in V5):

| Domain | Type | Merge Target |
|--------|------|--------------|
| `datasourceconfiguration` | Spring config | `__infrastructure__` |
| `package-info` | Java metadata | Delete |
| `longliststringtypehandler-*` | MyBatis TypeHandler | `user-profile-and-extend-data` |
| `internalserviceaspect-*` | AOP aspect | `__infrastructure__` |
| `backdoorserviceimpl` | Debug backdoor | Delete / `__infrastructure__` |
| `statisticsbehaviorhandler` | Single handler | `intimacy-relations` |
| `system-message-push` | Shared IM channel | `__infrastructure__` |
| `dealer-identity-service` | Identity wrapper | `user-profile-and-extend-data` |
| `intimacy-data-cleanup` | Single Kafka callback | `intimacy-growth-system` |
| `family-data-access-and-cache` | DAL/cache layer | `family-core-operations` |

### Design

Add `_filter_infrastructure_domains()` in `graph_domain_decompose.py`, called after `_cleanup_collision_slugs` and before `_enforce_domain_budget`.

**Filtering rules (generalized, no hardcoded slugs):**

1. **Single-class domain:** Domain contains exactly 1 module whose name is a single PascalCase identifier (e.g., `BackDoorServiceImpl`) → merge into nearest related domain by module count
2. **Known infrastructure patterns (configurable):** `AppWikiFlags.infrastructure_slug_keywords: list[str]` with defaults like `["configuration", "typehandler", "aspect", "package-info"]` — slugs containing any keyword are filtered
3. **Merge target:** Filtered modules merged into the domain with highest module overlap (shared imports/calls edges), or into a synthetic `_infrastructure` collector domain if no overlap found

### File Changes

#### `wiki/nodes/graph_domain_decompose.py`

Add `_filter_infrastructure_domains(domain_mapping, domain_display_names, infrastructure_keywords)` function.

#### `core/config.py`

```python
infrastructure_slug_keywords: list[str] = Field(
    default=["configuration", "typehandler", "aspect", "package-info", "wrapper"],
    description="Slug keywords that mark a domain as infrastructure (merged into nearby domain)",
)
```

### Tests

1. `test_single_class_domain_merged` — domain with 1 module gets merged
2. `test_infrastructure_keyword_filtered` — slug containing "configuration" gets filtered
3. `test_legitimate_domain_preserved` — normal business domain untouched

---

## F3: Tree Structure — ✅ RESOLVED

### Resolution (V6 Audit)

V5 reported "55 WikiPages fully orphaned, 0 Section→Page edges" — this was an **audit script bug**.

**Root cause of false positive:** `audit_wiki_data.py` tree query only joined `WikiSection→WikiSection`, missing `WikiSection→WikiPage` edges entirely.

**Actual state (verified V6 via direct FalkorDB query):**
- Section→Page edges: **55** (all pages connected)
- Section→Section edges: **35** (nested hierarchy correct)
- Space→Section edges: **3** (Space → __root__ + 2 repo sections)
- Orphaned pages: **0**

**Fix applied:** Added `(WikiSection)-[:HAS_CHILD]->(WikiPage)` query to `scripts/audit_wiki_data.py` (section 3b). No code changes needed in `tree_linker.py` or `business_pipeline_runner.py`.

---

## F5: Skeleton Page Rejection Gate (P1) — NEW

### Root Cause (V6 Discovery)

When `WikiPageAgent` exploration fails, `_generate_skeleton()` produces a minimal stub (e.g., 472 chars with empty sections). `finalize.py` strips `CONTEXT_GAP` markers, making the skeleton look like a normal (but empty) page. `quality_gate.py` has `_check_min_content_length` but it may trigger a heal cycle that also fails, then publishes the skeleton anyway.

**Evidence:** `family-guild-rank-square` — 472 chars, 5.1% Chinese ratio, all core sections empty.

### Design

After max heal iterations, if content still < `overview_min_content_length` (default 2000 chars):
1. Prepend visible banner: `> ⚠️ 本域文档待完善，内容可能不完整。`
2. Log warning with domain slug for operational visibility
3. Do NOT suppress the page entirely (presence in tree is better than gap)

### File Changes

1. `wiki/nodes/finalize.py` — add skeleton detection + banner injection
2. `wiki/nodes/quality_gate.py` — ensure min-length check triggers on final iteration

### Tests

1. `test_skeleton_page_gets_banner` — page < 2000 chars gets warning banner
2. `test_normal_page_no_banner` — page > 2000 chars unchanged

---

## F4: Generalized Term Consistency (P2)

### Root Cause

LLM generates Chinese translations for English domain names/concepts without consistent guidance. Different LLM calls produce different translations for the same term.

### Design

**No hardcoded terms.** Fully dynamic pipeline:

#### Phase 1: Term Extraction (in domain decompose node)

After domain decomposition, extract a term glossary:

1. Collect all `domain_display_names` (LLM-generated Chinese names)
2. Collect `BusinessConcept.name` + `description` from graph
3. Collect Chinese fragments from Module descriptions/Javadoc comments
4. Make a single LLM call to consolidate into a `{english_slug: preferred_chinese_term}` glossary
5. Store as `WikiState.term_glossary: dict[str, str]`

#### Phase 2: Term Injection (in agent prompts)

When building write prompts, dynamically inject the term glossary:

```
--- 术语约束 (Term Glossary) ---
以下术语在本项目中有确定的中文表达，请严格使用:
{dynamic glossary entries}
```

#### Phase 3: Term Verification (in output guardrail)

Add `TermConsistencyCheck` to `OutputGuardrailChain`:
- Read `term_glossary` from context
- For each term pair, check if the English term appears in content without its Chinese equivalent nearby
- Flag violations (soft warning, not hard fail)

#### Phase 4: User Override

```python
# core/config.py — AppWikiFlags
term_overrides: dict[str, str] = Field(
    default_factory=dict,
    description="Manual term override map {english: chinese}, takes precedence over auto-extracted",
)
```

### Sub-fix: Parent Domain Hallucination Prevention

V6 found parent overview pages (`family-system`, `intimacy-system`) contain invented component names. Fix: add constraint to parent overview prompt in `wiki/prompts.py`:

```
严禁发明代码库中不存在的组件名称、接口名称或事件名称。仅引用子域文档中已确认存在的实体。
```

### File Changes

1. `wiki/nodes/graph_domain_decompose.py` — add term extraction after domain naming
2. `wiki/agent_prompts.py` — add `build_term_glossary_prompt(glossary)` helper
3. `wiki/domain_doc_agent.py` — inject glossary into write context
4. `wiki/output_guardrail.py` — add `TermConsistencyCheck`
5. `core/config.py` — add `term_overrides` config
6. `wiki/prompts.py` — add anti-hallucination constraint to `system_wiki_parent_overview()`

### Tests

1. `test_term_extraction_from_display_names` — verify glossary generated from domain names
2. `test_term_injection_in_prompt` — verify glossary appears in write prompt
3. `test_term_consistency_check_detects_mismatch` — guardrail catches inconsistency
4. `test_user_override_takes_precedence` — override supersedes auto-extracted

---

## Implementation Order

| Batch | Fix | Dependencies | Est. Lines |
|-------|-----|-------------|------------|
| B1 | F1: Topic generation | None | ~60 |
| B2 | F2: Infrastructure filtering | None (parallel with B1) | ~50 |
| ~~B3~~ | ~~F3: Tree structure~~ | — | **RESOLVED** |
| B3 | F5: Skeleton rejection gate | F1 (new topics may also need gate) | ~30 |
| B4 | F4: Term consistency + parent anti-hallucination | F1+F2 | ~90 |

B1 and B2 can be implemented in parallel. B3 depends on B1. B4 depends on B1+B2.

---

## Rollback Mechanisms

| Fix | Rollback Config |
|-----|----------------|
| F1 | `enable_topic_pages=False` → single overview per domain |
| F2 | `infrastructure_slug_keywords=[]` → no filtering |
| F3 | RESOLVED — no rollback needed |
| F4 | `term_overrides={}` + skip glossary extraction → no term enforcement |
| F5 | Remove banner injection in finalize (additive change, safe to revert) |

---

## Success Criteria (post-deployment audit)

| Metric | V6 Current | Target |
|--------|-----------|--------|
| Topic pages | 0 | >50 |
| Topics per domain (domains >5 modules) | 0 | 2-5 avg |
| Infrastructure domains | 10 | 0-2 |
| Section→Page edges | 55 ✅ (was misreported) | = total_pages |
| Skeleton pages (<2000 chars, no banner) | 1 | 0 |
| Parent page hallucinated components | ~3 pages | 0 |
| Term violations (known terms) | ~4 title mismatches | 0 |
| Overall wiki quality score | 5.5/10 | 7/10 |
