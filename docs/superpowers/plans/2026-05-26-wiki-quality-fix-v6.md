# Wiki Quality Fix V6 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 15 issues identified in V7 audit, restoring topic tree navigation, language quality, link integrity, frontend UX, and security.

**Architecture:** Surgical edits across backend pipeline (Python) and frontend dashboard (React/TypeScript). Changes follow existing patterns — no new abstractions. TDD with existing pytest/vitest infrastructure.

**Tech Stack:** Python 3.12, FastAPI, FalkorDB, pytest-asyncio, React 19, TypeScript 5.9, Tailwind CSS 4, Vitest

**Spec:** `docs/superpowers/specs/2026-05-26-wiki-quality-fix-v6-design.md`

---

### Task 1: F2 — Edge Type Unification (`:WIKILINK` → `:WIKI_REFERENCES`)

**Files:**
- Modify: `wiki/confidence_inputs.py:71`
- Modify: `store/wiki_page_store.py:143-149`
- Modify: `wiki/lint.py` (all `:WIKILINK` references)
- Test: `tests/wiki/test_confidence_inputs.py`
- Test: `tests/store/test_wiki_page_store.py`

- [ ] **Step 1: Find and update all `:WIKILINK` references in `wiki/confidence_inputs.py`**

In `wiki/confidence_inputs.py` line 71, replace:
```python
"MATCH (src:WikiPage {repository: $repo})-[:WIKILINK]->(w:WikiPage {uid: $uid}) "
```
with:
```python
"MATCH (src:WikiPage {repository: $repo})-[:WIKI_REFERENCES {relation_type: 'wikilink'}]->(w:WikiPage {uid: $uid}) "
```

- [ ] **Step 2: Update `store/wiki_page_store.py` lines 143-149**

Replace all `:WIKILINK` with `:WIKI_REFERENCES {relation_type: 'wikilink'}` in the orphan degree query.

- [ ] **Step 3: Update `wiki/lint.py`**

Search for all `:WIKILINK` references and replace with `:WIKI_REFERENCES {relation_type: 'wikilink'}`.

- [ ] **Step 4: Update related test mocks**

Update mock graph data in test files to use `WIKI_REFERENCES` edge type instead of `WIKILINK`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/test_confidence_inputs.py tests/store/test_wiki_page_store.py tests/wiki/test_lint.py -x -v`
Expected: All PASS

---

### Task 2: F1 — Topic Tree Mount Fix

**Files:**
- Modify: `wiki/tree_linker.py:552-585`
- Test: `tests/wiki/test_tree_linker.py`

- [ ] **Step 1: Update `tp_q` query to return `business_domain`**

In `wiki/tree_linker.py`, find the `tp_q` query (around L495-510) and add `w.business_domain AS business_domain` to the RETURN clause.

- [ ] **Step 2: Build `domain_name_set` after `build_canonical_key_maps`**

After the `canonical_key_to_domain` dict is built, add:
```python
domain_name_set = {d.name for d in _flatten_domains(domain_tree)}
```
(Use whatever domain flattening helper already exists in the file)

- [ ] **Step 3: Rewrite matching logic at L566-585**

Replace the current `elif` logic with chain fallback:
```python
ck = str(row.get("canonical_key") or "").strip()
bd = str(row.get("business_domain") or "").strip()

matched_domain = None

# Priority 1: business_domain exact match
if bd and bd in domain_name_set:
    matched_domain = bd

# Priority 2: canonical_key in module mapping
if not matched_domain and ck:
    matched_domain = canonical_key_to_domain.get(ck)

# Priority 3: canonical_key is itself a domain slug
if not matched_domain and ck and ck in domain_name_set:
    matched_domain = ck

# Priority 4: path fuzzy fallback (only when all above fail)
if not matched_domain:
    matched_domain = _find_best_domain(top_level)
    if matched_domain:
        log.info(
            "nested_tree_topic_domain_fuzzy_fallback",
            business_id=business_id,
            path=path,
            matched_domain=matched_domain,
        )

if not matched_domain:
    log.warning(
        "nested_tree_topic_unresolvable",
        business_id=business_id,
        path=path,
        canonical_key=ck,
        business_domain=bd,
    )

if matched_domain:
    topic_pages_by_domain.setdefault(matched_domain, []).append(uid)
```

- [ ] **Step 4: Update existing tests**

Update `test_nested_tree_topic_unknown_canonical_key_skips_fuzzy_match` to expect business_domain fallback success (since V7 topics have correct business_domain).

Add new test `test_nested_tree_topic_business_domain_match` verifying business_domain takes priority.

- [ ] **Step 5: Run tree_linker tests**

Run: `uv run pytest tests/wiki/test_tree_linker.py -x -v`
Expected: All PASS

---

### Task 3: F3 — Topic Language Quality

**Files:**
- Modify: `wiki/domain_doc_agent.py:739-751`
- Modify: `wiki/output_guardrail.py:115-130`
- Test: `tests/wiki/test_domain_doc_agent.py`
- Test: `tests/wiki/test_output_guardrail.py`

- [ ] **Step 1: Localize TOPIC SCOPE in `domain_doc_agent.py`**

At L739-751, replace hardcoded English with language-conditional:
```python
if self._is_chinese_language():
    scope_text = (
        f"--- 主题范围 ---\n"
        f"你正在撰写「{topic.title}」章节。\n"
        f"仅聚焦以下模块：{topic_module_list}\n"
        f"描述：{topic.description}\n"
    )
else:
    scope_text = (
        f"--- TOPIC SCOPE ---\n"
        f"You are writing the \"{topic.title}\" section.\n"
        f"Focus ONLY on these modules: {topic_module_list}\n"
        f"Description: {topic.description}\n"
    )
topic_context = f"{baseline_context}\n\n{scope_text}" + glossary_section
```

- [ ] **Step 2: Harden `LanguageConsistencyCheck` for topics**

In `wiki/output_guardrail.py` L115-130, add `page_type` awareness:
```python
async def check(self, page_content: str, context: dict) -> CheckResult:
    target = context.get("target_language", "")
    if target not in self._CHINESE_TARGETS:
        return CheckResult(name=self.name, passed=True, score=1.0)

    threshold = context.get("cn_ratio_threshold", 0.4)
    cn_ratio = self._compute_cn_ratio(page_content)
    page_type = context.get("page_type", "")

    if cn_ratio < threshold:
        result = CheckResult(
            name=self.name,
            passed=False,
            score=cn_ratio,
            issues=[f"CN ratio {cn_ratio:.2f} below threshold {threshold} for target '{target}'"],
        )
        # Hard fail for topic pages — trigger heal
        if page_type == "topic":
            result.should_heal = True
        return result
    return CheckResult(name=self.name, passed=True, score=min(1.0, cn_ratio * 2))
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/wiki/test_output_guardrail.py tests/wiki/test_domain_doc_agent.py -x -v`

---

### Task 4: F4 — Stub Topic Interception

**Files:**
- Modify: `core/config.py` (add `topic_min_content_chars`)
- Modify: `wiki/nodes/quality_gate.py:55-79`
- Modify: `wiki/nodes/finalize.py:179-195`
- Test: `tests/wiki/nodes/test_quality_gate.py`
- Test: `tests/wiki/nodes/test_finalize.py`

- [ ] **Step 1: Add `topic_min_content_chars` config**

In `core/config.py`, in the `AppWikiFlags` class, add:
```python
topic_min_content_chars: int = Field(default=1000, description="Minimum content length for topic pages")
```

- [ ] **Step 2: Use config in `_check_min_content_length`**

In `wiki/nodes/quality_gate.py` L55-79, replace hardcoded `topic_min=1000` default with settings:
```python
def _check_min_content_length(
    page: dict[str, Any],
    overview_min: int | None = None,
    topic_min: int | None = None,
) -> dict[str, Any]:
    if overview_min is None:
        overview_min = get_settings().wiki.overview_min_content_chars
    if topic_min is None:
        topic_min = get_settings().wiki.topic_min_content_chars
    # ... rest unchanged
```

- [ ] **Step 3: Extend skeleton banner to topics in `finalize.py`**

At L179-195, modify condition:
```python
is_topic_index = page.get("metadata", {}).get("overview_kind") == "topic_index"
is_overview = page.get("page_type") == "domain_overview"
is_topic = page.get("page_type") == "topic"
if (
    (is_overview or is_topic)
    and len(content) < _get_skeleton_threshold()
    and not is_topic_index
):
```

- [ ] **Step 4: Update tests**

Update `test_topic_page_no_banner` → expect short topics DO get banner.
Add `test_stub_topic_gets_skeleton_banner`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_quality_gate.py tests/wiki/nodes/test_finalize.py -x -v`

---

### Task 5: F5+F6+F13 — Infra Filter + Terms + Debug Domain

**Files:**
- Modify: `core/config.py` (infrastructure_slug_keywords, term_overrides defaults)
- Modify: `wiki/nodes/graph_domain_decompose.py:192-234`
- Test: `tests/wiki/nodes/test_graph_domain_decompose.py`

- [ ] **Step 1: Expand infra keywords and class suffixes**

In `core/config.py`, update `infrastructure_slug_keywords` default:
```python
infrastructure_slug_keywords: list[str] = Field(
    default=["configuration", "typehandler", "aspect", "package-info", "wrapper",
             "handler", "executor", "debug", "groovy", "impl"],
    ...
)
```

In `wiki/nodes/graph_domain_decompose.py`, add to `_INFRA_CLASS_SUFFIXES`:
```python
_INFRA_CLASS_SUFFIXES = (
    "Impl", "Configuration", "Config", "TypeHandler",
    # ... existing entries ...
    "Handler", "Executor",
)
```

- [ ] **Step 2: Set default term_overrides**

In `core/config.py`, update `term_overrides` default:
```python
term_overrides: dict[str, str] = Field(
    default={"closed-friend": "挚友", "closed friend": "挚友"},
    ...
)
```

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/wiki/nodes/test_graph_domain_decompose.py -x -v`

---

### Task 6: F7 — Topic Index Overview Synthesis

**Files:**
- Modify: `wiki/domain_doc_agent.py:772-787`
- Test: `tests/wiki/test_domain_doc_agent.py`

- [ ] **Step 1: Add LLM summary synthesis after topic index assembly**

At L774-781 in `domain_doc_agent.py`, after building the header, add an LLM call to generate a brief business overview:
```python
lang = ContentLanguage.from_any(self.content_language)
nav_heading = "## 章节导航" if lang.is_chinese else "## Section Navigation"

# Synthesize brief business overview for topic_index
topic_names = ", ".join(t.title for t in outline.topics)
if lang.is_chinese:
    summary_prompt = (
        f"为「{self.domain_display_name}」域撰写 2-3 段业务概述（200-400 字），"
        f"概括该域的业务价值、整体架构和核心能力。"
        f"该域包含以下子主题：{topic_names}。"
        f"只写概述段落，不要列举子主题。"
    )
else:
    summary_prompt = (
        f"Write a 2-3 paragraph business overview (200-400 words) for the '{self.domain_display_name}' domain. "
        f"Summarize its business value, architecture, and key capabilities. "
        f"Sub-topics: {topic_names}. Do not list sub-topics."
    )

summary_text = ""
try:
    summary_text = await self._page_agent.write(
        self.domain_name, summary_prompt, memory,
    )
    summary_text = summary_text.strip()
except Exception:
    log.warning("topic_index_overview_synthesis_failed", domain=self.domain_name, exc_info=True)

overview_content = (
    f"# {self.domain_display_name}\n\n"
    + (f"{summary_text}\n\n" if summary_text else "")
    + "\n".join(
        f"## {t.title}\n{t.description}\n"
        for t in outline.topics
    )
    + f"\n{nav_heading}\n\n" + "\n".join(topic_links)
)
```

- [ ] **Step 2: Run tests**

Run: `uv run pytest tests/wiki/test_domain_doc_agent.py -x -v`

---

### Task 7: F8 — Wikilink Composite Key

**Files:**
- Modify: `wiki/domain_doc_agent.py:770`
- Modify: `wiki/wikilink_cache.py:34-45`
- Modify: `wiki/nodes/links.py:25-45`
- Test: `tests/wiki/test_wikilink_cache.py`
- Test: `tests/wiki/nodes/test_links.py`

- [ ] **Step 1: Change topic link format to pure title**

In `wiki/domain_doc_agent.py` L770:
```python
# Before
topic_links.append(f"- [[{self.domain_name}/{topic.title}]]")
# After
topic_links.append(f"- [[{topic.title}]]")
```

- [ ] **Step 2: Add composite key support to `WikiLinkCache`**

In `wiki/wikilink_cache.py`, update `register()`:
```python
def register(self, title: str, path: str, business_domain: str = "") -> None:
    t = title.strip()
    if not t:
        return
    url = f"/wiki?path={path}"
    self._title_to_url[t] = url
    if business_domain:
        composite = f"{business_domain}/{t}"
        self._title_to_url[composite] = url
```

- [ ] **Step 3: Add composite key matching to `create_links_node`**

In `wiki/nodes/links.py`, in the title/path index building, add:
```python
for p in pages:
    bd = p.get("business_domain", "")
    title = p.get("title", "")
    if bd and title:
        composite_key = f"{bd}/{title}".lower()
        page_titles[composite_key] = p.get("path", "")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/wiki/test_wikilink_cache.py tests/wiki/nodes/test_links.py -x -v`

---

### Task 8: F9 — Mobile Sidebar Fix

**Files:**
- Modify: `dashboard/src/components/wiki/WikiToolbar.tsx:49-57`
- Test: Manual verification or Vitest

- [ ] **Step 1: Remove `hidden` class from sidebar toggle button**

In `WikiToolbar.tsx`, find the button with `className="hidden ... lg:flex"` and change to `className="flex ..."` (remove `hidden` and `lg:` prefix).

- [ ] **Step 2: Run frontend linting**

Run: `cd dashboard && pnpm lint`
Expected: No new errors

---

### Task 9: F10+F11 — Frontend topic_index UI + Breadcrumb + Search

**Files:**
- Modify: `dashboard/src/components/wiki/WikiToolPanel.tsx`
- Modify: `dashboard/src/components/wiki/WikiBreadcrumbs.tsx:28-43`
- Modify: search result components
- Modify: wiki search API types

- [ ] **Step 1: Add `overview_kind` awareness to `WikiToolPanel`**

When `page.context?.overview_kind === "topic_index"`, render with a distinct visual style (e.g., card layout for each section heading).

- [ ] **Step 2: Improve breadcrumbs to use page titles**

In `WikiBreadcrumbs.tsx` L28-43, build a `segmentToTitle` map from the page data or topic tree, and use `titleMap[seg] || decodeURIComponent(seg)` for display.

- [ ] **Step 3: Add `page_type` to search results**

Extend `WikiSemanticWikiHit` type to include `page_type`, and display it as a badge in `WikiSemanticSearchResults`.

- [ ] **Step 4: Run frontend tests**

Run: `cd dashboard && pnpm lint && pnpm test`

---

### Task 10: F12 — SensitiveContentGuardrail

**Files:**
- Modify: `wiki/output_guardrail.py`
- Modify: `wiki/nodes/finalize.py`
- Test: `tests/wiki/test_output_guardrail.py`
- Test: `tests/wiki/nodes/test_finalize.py`

- [ ] **Step 1: Add `SensitiveContentCheck` class**

In `wiki/output_guardrail.py`, add:
```python
class SensitiveContentCheck:
    """Detect and flag sensitive information patterns in wiki content."""

    name = "sensitive_content"

    _PATTERNS = [
        re.compile(r"https?://(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|internal\.|localhost)", re.IGNORECASE),
        re.compile(r"(?:password|secret|api[_-]?key|private[_-]?key)\s*[:=]\s*\S+", re.IGNORECASE),
    ]

    async def check(self, page_content: str, context: dict) -> CheckResult:
        findings = []
        for pattern in self._PATTERNS:
            matches = pattern.findall(page_content)
            if matches:
                findings.extend(matches[:3])
        if findings:
            return CheckResult(
                name=self.name,
                passed=False,
                score=0.0,
                issues=[f"Sensitive patterns detected: {len(findings)} matches"],
            )
        return CheckResult(name=self.name, passed=True, score=1.0)
```

- [ ] **Step 2: Add redaction to finalize**

In `wiki/nodes/finalize.py`, in `_sanitize_published_content()`, add redaction patterns:
```python
_REDACT_PATTERNS = [
    (re.compile(r"https?://(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.|internal\.|localhost)\S*", re.IGNORECASE), "[INTERNAL_URL]"),
    (re.compile(r"((?:password|secret|api[_-]?key)\s*[:=]\s*)\S+", re.IGNORECASE), r"\1[REDACTED]"),
]

for pattern, replacement in _REDACT_PATTERNS:
    content = pattern.sub(replacement, content)
```

- [ ] **Step 3: Register check and run tests**

Register `SensitiveContentCheck` in the guardrail runner.

Run: `uv run pytest tests/wiki/test_output_guardrail.py tests/wiki/nodes/test_finalize.py -x -v`

---

### Task 11: F14+F15 — Incremental Default + Data Cleanup

**Files:**
- Modify: `core/config.py` (incremental_enabled default)
- Modify: `wiki/persistence.py` (cleanup scope)
- Create: `scripts/cleanup_module_overviews.py`

- [ ] **Step 1: Change `incremental_enabled` default to `True`**

In `core/config.py`, in `AppWikiFlags`:
```python
incremental_enabled: bool = Field(default=True, ...)
```

- [ ] **Step 2: Extend cleanup to include `module_overview`**

In `wiki/persistence.py`, in `cleanup_stale_wiki_pages`, update:
```python
"AND w.page_type IN ['topic', 'domain_overview', 'module_overview'] "
```

- [ ] **Step 3: Create cleanup script**

Create `scripts/cleanup_module_overviews.py` for one-time cleanup of legacy pages.

- [ ] **Step 4: Run persistence tests**

Run: `uv run pytest tests/wiki/test_persistence.py -x -v`

---

## Verification Checklist

After all tasks complete:
- [ ] `uv run pytest` — full backend suite passes
- [ ] `cd dashboard && pnpm lint && pnpm test` — frontend passes
- [ ] `uv run ruff check .` — no lint errors
- [ ] Review diff for unintended changes
