# Wiki Quality Audit Report (2026-06-02, Rev.3)

**Corpus:** 5 pages (all domain_overview, all error placeholders), 0 topics  
**Source:** FalkorDB live data via `scripts/audit_wiki_data.py --repo ultron`  
**Pipeline run:** 2026-06-02T04:01 UTC, full rebuild after Sprint 1 partial apply  
**Previous audit:** 27 pages / 11 rejected (same date, pre-Sprint-1)

---

## Scope & Methodology

**Scope:** All wiki pages persisted in FalkorDB for the `ultron` repository. Both the current post-Sprint-1 state (5 pages) and the pre-Sprint-1 baseline (27 pages) are analyzed — issues are tagged accordingly.

**Methodology:**
1. Data extraction via `scripts/audit_wiki_data.py`
2. Code tracing to pinpoint root causes with file:line references
3. LangGraph checkpoint inspection (`data/checkpoints/ultron_wiki.db`)
4. Cross-reference with pre-Sprint-1 audit data

**Out of scope:** Frontend rendering bugs, search/RAG quality, indexer correctness.

**Baseline state tags used throughout:**
- `[post-S1]` — observable in current 5-page state
- `[pre-S1]` — observable in pre-Sprint-1 27-page state; requires pipeline recovery to verify
- `[both]` — present in both states

---

## Executive Summary

| Metric | Pre-Sprint-1 | Post-Sprint-1 (current) | Assessment |
|--------|-------------|------------------------|------------|
| Total pages (persisted) | 27 | **5** | **Catastrophic regression** |
| Error placeholder pages | 4 | **5 (100%)** | All pages are failures |
| Topic pages | 23 | **0** | Complete loss |
| L1 domain sections | 16+ | **2** | Extreme tree shrinkage |
| Error message | empty `TimeoutError` | `Exception: unknown compose failure` | New bug masks real errors |
| Domains with content | 23 | **0** | Total compose failure |

**Overall:** Sprint 1 "domain recovery" fixes were **partially applied** to dev, introducing **3 critical regressions** that turned a 4-domain failure into a **total pipeline failure**. All 5 persisted pages are error skeletons with `"unknown compose failure"`. Root cause: `compose_error_handler.py` API mismatch with LangGraph 1.2 + missing heartbeat implementation.

---

## Root Cause: Sprint 1 Incomplete Implementation (3 Critical Bugs) `[post-S1]`

These 3 bugs are the **blocking prerequisite** for all other fixes. Issues #1-#5 cannot be verified until these are resolved.

### Bug 1: `compose_error_fallback` signature mismatch (CRITICAL)

| Aspect | Expected (LangGraph 1.2) | Actual |
|--------|--------------------------|--------|
| Parameter | `error: NodeError` | `error: BaseException \| None = None` |
| Injection | LangGraph injects `NodeError` only when annotation matches | Never injected → `error=None` always |
| Result | Access `error.error` for real exception | Falls back to `Exception("unknown compose failure")` |

**Source:** `wiki/nodes/compose_error_handler.py:16`  
**Evidence:** All 5 pages show identical `"Exception: unknown compose failure"` text

### Bug 2: `idle_timeout=180` without heartbeat implementation

| Aspect | Design intent | Actual |
|--------|--------------|--------|
| idle_timeout | Reset on progress (heartbeat/token/callback) | Never resets — custom agent stack bypasses LangChain callbacks |
| Effect | Kill truly stuck nodes | Kills ALL nodes after 180s, even healthy ones doing RAG |
| Scope | Per-node | Entire `compose_domain_agents` node → all parallel domains cancelled |

**Source:** `wiki/pipeline_graph.py:275-278`  
**Why heartbeat never fires:** LLM via `LLMProvider.complete_with_tools()` (httpx POST, no streaming callback); tools via `ToolRegistry.dispatch()` (custom `@function_tool`, not LangChain Tool); RAG via `graph_store.execute_query()` (raw asyncio)

### Bug 3: `RetryPolicy(retry_on=(TimeoutError,))` doesn't match `NodeTimeoutError`

LangGraph 1.2's `NodeTimeoutError` **does not inherit** built-in `TimeoutError` (see `langgraph/errors.py:170-171`). Therefore `retry_on=(TimeoutError,)` never triggers retry on idle timeout.

**Source:** `wiki/pipeline_graph.py:279`

### Auxiliary Issues `[post-S1]`

| Issue | Source | Impact |
|-------|--------|--------|
| Path format `{slug}/index` instead of `/__domains__/{slug}/_overview` | `compose_error_handler.py:37` | tree_linker, navigation, audit all fail to recognize pages |
| `quality_gate` only handles `agent_error`, not `error_fallback` | `quality_gate.py:238` | heal cycles never triggered for fallback pages |
| Domain traversal only top-level, not recursive container+leaf | `compose_error_handler.py:35-37` | Sub-domains missed in skeleton generation |

---

## P0 — Critical (6 issues)

### 0. Domain agent timeout → entire domains silently lost `[both]`

**Symptoms:** `family-system` (116 modules, largest domain) completely absent from final wiki. `intimacy-task-system`, `user-profile-and-vip`, `user-gift-interaction` also missing. Total: 4 domains, 11 rejected pages.

**Root Cause Chain (confirmed via LangGraph checkpoint on dev):**
```
① domain_decompose → family-system (116 modules) correctly identified
     ↓
② theme_aggregation(F10) + shell_collapse → reorganized as family-ecosystem (57 modules)
     ↓
③ compose_domain_agents → asyncio.wait_for(timeout=600s) TIMEOUT
  → _make_error_placeholder: "⚠️ 文档生成失败: " (empty after colon)
     ↓
④ quality_gate → detects agent_error → sends to heal (max 1 cycle) → heal fails
     ↓
⑤ finalize_node → _sanitize_published_content → only 12 chars remain
  → shell_domain_rejected (threshold=500, i.e. overview_min_content_chars//4)
  → __rejected__=True, content=''
     ↓
⑥ _pages_from_state skips → not persisted → prune_empty_domain_sections removes WikiSection
```

**Evidence (from `data/checkpoints/ultron_wiki.db`, thread `biz-ultron`):**

| Evidence | Data |
|----------|------|
| Run type | **Full** (`is_incremental=False`) |
| `domain_mapping['family-system']` | 116 modules (persists in all checkpoints) |
| Reorganized slug | `family-ecosystem` (57 modules, largest domain) |
| Error type | `generation_mode: agent_error` |
| Error message | **Empty** — Python 3.13 `str(TimeoutError())` returns `''` |
| Timeout config | `domain_agent_timeout_sec=600` (10 min) |
| Same-batch failures | intimacy-task-system(14), user-profile-and-vip(15), user-gift-interaction(25) |
| Reject threshold | 500 chars (`overview_min_content_chars=2000 // 4`) |
| Total rejected pages | 11 (4 agent_error overview + 7 quality gate) |

**Key Code Locations:**
- `wiki/nodes/domain_compose.py:476-484` — `asyncio.wait_for(..., timeout=domain_agent_timeout_sec)`
- `wiki/nodes/domain_compose.py:555-579` — `_make_error_placeholder()` with `str(error)[:200]`
- `wiki/nodes/finalize.py:871-881` — `shell_domain_rejected` hard reject
- `wiki/nodes/quality_gate.py:236-248` — agent_error heal (max 1 cycle)
- `core/config.py` — `domain_agent_timeout_sec=600`, `overview_min_content_chars=2000`

**Fix Priority:** Highest — entire domains are silently dropped

| Fix | Effort | Impact | Tradeoff |
|-----|--------|--------|----------|
| Dynamic timeout scaling (modules > 30 → timeout × 2) | S | Prevents timeout for large domains | Threshold 30 is based on largest successful domain having 25 modules; needs tuning with data |
| Fix `_make_error_placeholder`: `f"{type(e).__name__}: {e or 'timeout'}"` | S | Preserves error info | None |
| `error_handler` fallback: generate skeleton overview on timeout | M | Graceful degradation | **Tradeoff:** Users see incomplete content with warning banners; mitigated by degraded page counting + alerts |
| `finalize`: exempt `agent_error` pages from hard reject, keep skeleton + banner | S | No domain disappears | Same tradeoff as above — surfacing broken content vs losing domains entirely |
| Increase heal cycles for agent_error (1 → 3) | S | More recovery chances | Heal may also timeout; only helps if timeout was transient |
| Batch/accumulator for large domains (>30 modules) | L | Fundamental fix | Significant architecture change |

---

### 1. Topic pages contain fabricated Java APIs `[pre-S1]` — *Blocked by: pipeline recovery (Bug 1/2/3)*

**Symptoms:** Invented methods (`queryPopWindowStatus()`, `isValidUser()`), strategy classes, SQL DDL, full pseudo-implementations presented as real architecture.

**Root Cause Chain:**
```
Prompts mandate ≥3 code blocks → key_snippets often empty in graph →
LLM fabricates code → code_block_verifier NOT wired into topic sanitize →
content_guards EXCLUDES fenced code from hallucination scan →
quality_gate citation check = module names only (soft penalty) →
Pages persist with fabricated code
```

**Key Code Locations:**
- `wiki/unified_prompt_templates.py:26-44` — contradictory mandate (require code blocks + don't fabricate)
- `wiki/nodes/compose.py:156-180` — `_sanitize_pages()` doesn't call `verify_and_inject()`
- `wiki/content_guards.py:36-47` — `_CODE_FENCE_RE.sub("", content)` excludes code from scan
- `wiki/quality_gate.py:279-286` — citation = module names only, soft −0.05 penalty

| Fix | Effort | Impact |
|-----|--------|--------|
| Make code blocks conditional on snippet count in prompts | S | Stops fabrication pressure |
| Wire `verify_and_inject()` into `_sanitize_pages()` | M | Strips ungrounded blocks |
| Scan code fences in hallucination detection | M | Catches remaining |
| Hard-reject method references not in graph | M | Prose + code guard |

---

### 2. Wikilinks use title text instead of path (navigation broken) `[pre-S1]` — *Blocked by: pipeline recovery*

**Symptoms:** `[[用户状态]]`, `[[挚友关系核心服务]]` — frontend treats as path → 404 or wrong page.

**Root Cause:**
- Agent prompts instruct `[[topic_title]]` format (`agent_prompts.py:312`)
- `create_links_node` resolves titles → graph edges but **never rewrites content**
- `finalize._remove_invalid_wikilinks` validates but preserves title format
- Frontend `wikilinkParser.ts` expects `[[/path]]` or `[[/path|label]]`

**Fix:** Add content rewrite pass in `finalize_node`: `[[title]]` → `[[/path|title]]` using WikiLinkCache title→path map. Effort: **M**.

---

### 3. Duplicate domain pairs `[pre-S1]` — *Blocked by: pipeline recovery*

**Symptoms:** `relation-rank` + `relation-rank-service`, `quick-message` + `quick-message-service` — identical display names, parallel content.

**Root Cause:** Global stem merge runs **before** sub-domain split; split re-introduces `{parent}-service` slugs; no post-tree dedup pass.

**Fix:** Run `_merge_global_stem_suffix_domains()` **after** tree build + sub-split. Effort: **S**.

---

### 4. Cross-domain topic misplacement `[pre-S1]` — *Blocked by: pipeline recovery*

**Symptoms:** family modules under `intimacy-task-execution`; friend-relation modules under `intimacy`; ES service under wrong domain.

**Root Cause:** Embedding + call-graph similarity dominates prefix cannot-link → mis-clustered modules → LLM names cluster after dominant theme → scatter validation (checking if a cluster's modules span too many source prefixes) is **log-only** with no corrective action.

**Fix Bundle:**
- Wire scatter validation → split/re-cluster (M)
- Harden prefix cannot-link for family/intimacy/closed-friend prefixes (M)
- Cap call-graph discount when prefixes differ (M)

---

### 5. Slug ↔ display_name inversion (`quick-message` → 在线状态) `[pre-S1]` — *Blocked by: pipeline recovery*

**Symptoms:** Navigation labels don't match slug semantics.

**Root Cause:** LLM conflates related concepts; repair depends on small hardcoded map; naming cache freezes bad names without re-validation.

**Fix:** Re-validate on cache hit; expand known mappings; reject unresolvable inversions. Effort: **S**.

---

## P1 — High (8 issues)

### 6. Module pages: English H2 shell on Chinese wiki `[pre-S1]`

**Root Cause:** `composer.py:1140-1148` hardcodes English `## Overview` / `## Key components`; finalize normalization gated on missing `content_language`.

**Fix:** Chinese-first template; set `content_language` at compose time. Effort: **S**.

### 7. Double H1 on module pages `[pre-S1]`

**Root Cause:** Template emits `# {title}` + UI renders title as H1 + `strip_h1_title` only removes first leading H1.

**Fix:** Don't emit template H1; strip all body H1s matching title in finalize. Effort: **S**.

### 8. "No nested graph children" placeholder on all module pages `[pre-S1]`

**Root Cause:** `composer.py:1157` unconditional placeholder; tier-2 LLM echoes into body.

**Fix:** Omit section when children empty; strip in finalize. Effort: **S**.

### 9. 11/28 domains empty (39% dead-end rate) `[pre-S1]`

**Root Cause:** Over-split clustering + sub-domain hierarchy → empty parent shells; theme aggregation re-creates empty containers.

**Fix:** Lower `domain_budget_max` to 15–18; run small-leaf merge **after** tree build; strip empty post-aggregation. Effort: **M**.

### 10. Intimacy cluster: 5 near-identical domains `[pre-S1]`

**Root Cause:** Same as #4 + embedding merge threshold 0.8 too strict for CJK near-synonyms (亲密关系/亲密任务/亲密执行).

**Fix:** Lower embedding merge threshold to 0.72–0.75 for CJK; hardcode business prefixes. Effort: **M**.

### 11. Topic title format: `「·专题·N」` serial numbers `[pre-S1]`

**Root Cause:** `_deduplicate_exact_titles()` adds serial suffixes; titles lack semantic differentiation.

**Fix:** Use module-role disambiguation instead of numeric; drop slug from titles. Effort: **S**.

### 12. Table spacing / GFM rendering `[pre-S1]`

**Root Cause:** No markdown spacing normalizer in pipeline.

**Fix:** Regex normalizer in finalize ensuring `\n\n` before tables. Effort: **S**.

### 13. Terminology inconsistency (MOA, 挚友/封闭好友, quick-message) `[pre-S1]`

**Root Cause:** No glossary enforcement; LLM generates different translations per run.

**Fix:** Term override glossary in compose prompts; validate in quality gate. Effort: **M**.

---

## P2 — Medium (6 issues)

### 14. Module page identity mismatch (DeviceInfoDTO → wrong body) `[pre-S1]`

**Root Cause:** `composer.py` feeds module metadata to LLM but does not verify output references match the target module. 2/93 pages (2%) have body content describing a different module.

**Fix:** Add post-compose identity check comparing output module references against input module name. Effort: **M**.

### 15. Duplicate wikilinks in Related Topics `[pre-S1]`

**Root Cause:** `create_links_node` may emit duplicate edges; finalize does not dedup wikilinks within a section. ~10% of topic pages affected.

**Fix:** Dedup wikilinks per section in finalize. Effort: **S**.

### 16. L1 count too high (16 → target 6–8) `[pre-S1]`

**Root Cause:** Domain tree builder does not consolidate related L1 sections; `domain_budget_max=20` allows too many top-level categories.

**Fix:** Structural L1 consolidation pass in tree builder. Requires product decision on target structure. Effort: **L**.

### 17. Coverage gaps (voice rooms, payment depth) `[pre-S1]`

**Root Cause:** These features exist in the codebase but modules are not clustered into standalone domains, likely absorbed into larger catch-all domains.

**Fix:** Verify domain coverage after pipeline recovery; may need explicit domain seeding. Effort: **M**.

### 18. Module pages not linked to domain sections `[pre-S1]`

**Root Cause:** `domain_compose.py` generates domain overview but does not create child-page links for all constituent modules. 20/93 (21%) orphaned.

**Fix:** Add module-page linking pass in domain compose. Effort: **M**.

### 19. `Quick` L1 label not localized `[pre-S1]`

**Root Cause:** L1 section name generated from slug without localization. 1 section affected.

**Fix:** Apply same Chinese-first template as C1. Effort: **S**.

---

## Unified Repair Roadmap

All phases are sequential. **Phase A-0 is the critical blocker** — no other phase can be validated until pipeline recovery is complete.

### Phase A-0: Pipeline Recovery (P0 — addresses Root Cause Bugs 1/2/3 + Issue #0) `[post-S1]`

| ID | Fix | Effort | Files |
|----|-----|--------|-------|
| A0-1 | Dynamic timeout: `modules > 30 → timeout × 2` | S | `nodes/domain_compose.py`, `config.py` |
| A0-2 | Fix empty error msg: `f"{type(e).__name__}: {e or 'timeout'}"` | S | `nodes/domain_compose.py` |
| A0-3 | Finalize: exempt `agent_error` from hard reject, keep skeleton + banner | S | `nodes/finalize.py` |
| A0-4 | Increase heal cycles for agent_error: 1 → 3 | S | `quality_gate.py` |
| A0-5 | Complete LangGraph 1.2 API migration: fix `error_handler` signature (`NodeError`), fix `retry_on` (`NodeTimeoutError`), implement heartbeat (fix `_with_progress` runtime forwarding + background 60s pulse + agent loop boundary heartbeats) | M | `pipeline_graph.py`, `compose_error_handler.py`, `domain_compose.py`, `agents/runner.py` |

**Success metrics:** 0 error placeholder pages; family-ecosystem domain present; error messages contain real exception info.

### Phase A: Content Trust (P0 — addresses Issues #1-#3) `[pre-S1]`

| ID | Fix | Effort | Files |
|----|-----|--------|-------|
| A-1 | Make code blocks conditional on snippet availability | S | `unified_prompt_templates.py` |
| A-2 | Wire `verify_and_inject()` into topic sanitize | M | `nodes/compose.py`, `code_block_verifier.py` |
| A-3 | Scan code fences in hallucination detection | M | `content_guards.py` |
| A-4 | Wikilink content rewrite (title → path) in finalize | M | `nodes/finalize.py`, `wikilink_cache.py` |

**Success metrics:** <10% topics with fabricated code; >90% wikilinks in path format.

### Phase B: Domain Integrity (P0 — addresses Issues #3-#5) `[pre-S1]`

| ID | Fix | Effort | Files |
|----|-----|--------|-------|
| B-1 | Post-tree global stem merge (fix duplicate pairs) | S | `nodes/graph_domain_decompose.py` |
| B-2 | Slug↔display validation on cache hit + expand known map | S | `graph_domain_namer.py` |
| B-3 | Harden prefix cannot-link + cap cross-prefix discount | M | `domain_semantic_clusterer.py` |
| B-4 | Wire scatter validation → corrective split | M | `cluster_validation.py`, decompose node |

**Success metrics:** 0 duplicate domain pairs; family modules in family domain.

### Phase C: Polish & Consistency (P1 — addresses Issues #6-#8, #11-#12, #15, #19) `[pre-S1]`

| ID | Fix | Effort | Files |
|----|-----|--------|-------|
| C-1 | Chinese module template + strip English shell + localize Quick label | S | `composer.py`, `finalize.py` |
| C-2 | Strip all body H1s + remove template H1 | S | `composer.py`, `finalize.py` |
| C-3 | Remove "No nested graph children" placeholder | S | `composer.py` |
| C-4 | Table spacing normalizer | S | `finalize.py` |
| C-5 | Topic title: module-role disambiguation instead of numeric serial | S | `nodes/compose.py` |
| C-6 | Related Topics wikilink dedup | S | `finalize.py` |

**Success metrics:** Chinese H2 headings; no double H1; clean GFM tables.

### Phase D: Structure Optimization (P1-P2 — addresses Issues #9-#10, #13-#14, #16-#18) `[pre-S1]`

| ID | Fix | Effort | Files |
|----|-----|--------|-------|
| D-1 | Empty domain merge (11 → target 0 dead-ends) | M | `graph_domain_decompose.py`, config |
| D-2 | Intimacy cluster consolidation (5 → 2) | M | Config + merge logic |
| D-3 | Glossary enforcement in prompts + quality gate | M | `unified_prompt_templates.py`, `quality_gate.py` |
| D-4 | Module page identity verification | M | `composer.py` |
| D-5 | Link module pages into domain sections | M | `domain_compose.py` |
| D-6 | L1 restructure (16 → 6–8 pillars) | L | Tree builder + compose |
| D-7 | Domain coverage verification (voice rooms, payment) | M | Post-recovery analysis |

**Success metrics:** <10% dead-end domains; terminology consistent; all modules linked.

---

## Gap Analysis: Pipeline vs Best Practices

| Aspect | Pre-Sprint-1 | Post-Sprint-1 (current) | Best practice |
|--------|-------------|------------------------|---------------|
| Timeout | `wait_for(600s)` per-domain | `idle_timeout=180` node-level (no heartbeat) | `idle_timeout` + `heartbeat` + `run_timeout` |
| On timeout | Empty error → reject → domain lost | `unknown compose failure` → all domains lost | `error_handler(NodeError)` → skeleton + degrade |
| Retry | 1 heal cycle | `RetryPolicy(TimeoutError)` — mismatch | `RetryPolicy(NodeTimeoutError)` |
| Failure isolation | Per-domain (good) | All-or-nothing (worse) | Per-domain heartbeat + node-level safety net |
| Error info | `str(TimeoutError())` = empty | `unknown compose failure` (signature bug) | `NodeError.error` → full exception chain |
| Progress signal | None | None (heartbeat not implemented) | `runtime.heartbeat()` on tool/LLM/RAG |
| Observability | stdout only | stdout only | structlog + checkpoint error provenance |

For detailed industry comparison (Cursor Temporal migration, LangGraph patterns, Durable Execution landscape), see [`docs/wiki-resilience-patterns.md`](wiki-resilience-patterns.md).

---

## Comparison with Previous Audit (v13/v14)

| Issue | v13 status | Current status |
|-------|------------|----------------|
| Fabricated code in topics | Identified | **Root cause traced; fix plan A-1 to A-3** |
| Duplicate domains | Phase B partially implemented | **2 pairs remain; post-tree stem merge gap found** |
| English H2 on modules | Identified | **Root cause: template + missing content_language** |
| Empty domains (39%) | Config tuned (budget_max=20) | **Still 11 empty; need post-tree merge** |
| Wikilink broken | Not in v13 scope | **NEW P0: title-only links, no path rewrite** |
| Title serial `·专题·N` | Phase B-2 implemented | **Partially fixed; still in production data** |
| Stem merge timing | Phase A-3 added | **Bug found: runs before sub-split** |

---

## Data Files

| File | Size | Contents |
|------|------|----------|
| `data/wiki-audit.json` | 232KB | Full audit data (27 pages with content) |
| `data/wiki-audit-summary.json` | — | Compact summary |
| `data/wiki-content-samples.json` | — | Selected content samples for spot-checking |
| `data/checkpoints/ultron_wiki.db` | — | LangGraph checkpoint (evidence source for root cause analysis) |
