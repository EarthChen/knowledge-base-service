# Wiki 质量修复 + 业务索引隔离 + 进度增强 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix wiki page quality issues (agent leakage, hallucination, CONTEXT_GAP), then implement business-scoped indexing and real-time pipeline progress tracking.

**Architecture:** Phase A fixes wiki generation post-processing (page_agent, sanitize, prompts). Phase B wires business_id through the indexing pipeline for graph isolation. Phase C adds LangGraph event stream monitoring for pipeline progress with a compose_leaf fine-grained callback.

**Tech Stack:** Python 3.11+, FastAPI, LangGraph >=0.2.0, FalkorDB, React 19, Vite, TanStack Query

**Source proposals:**
- `docs/proposals/PROPOSAL_20260508_150922_wiki_quality_remediation.md`
- `docs/proposals/PROPOSAL_20260508_135807_business_indexing_and_progress.md`

---

## Phase A: Wiki Quality Fixes (can run tasks 1-4 in parallel)

### Task 1: Agent Output Sanitization (P0)

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_page_agent.py`

- [ ] **Step 1: Write failing test — detect and strip agent thinking text**

```python
# tests/wiki/test_page_agent.py — add to existing test file

import pytest
from wiki.page_agent import strip_agent_artifacts

def test_strip_agent_artifacts_removes_thinking_prefix():
    raw = (
        "我需要补充 `CONTEXT_GAP` 中提到的缺失信息，包括：\n"
        "1. 订单回调请求体字段定义\n\n"
        "```json\n{\"tools\": [{\"name\": \"search_code\"}]}\n```\n\n"
        "---\n\n"
        "## Components\n\n| Component | Description |\n"
        "|-----------|-------------|\n| Foo | Bar |\n"
    )
    result = strip_agent_artifacts(raw)
    assert "我需要" not in result
    assert "tools" not in result
    assert "## Components" in result

def test_strip_agent_artifacts_preserves_clean_content():
    clean = "## 业务概述\n\n这是正常内容。\n\n## 核心服务详解\n\n详细说明。"
    result = strip_agent_artifacts(clean)
    assert result == clean

def test_strip_agent_artifacts_returns_empty_on_all_thinking():
    raw = "我需要查询两个缺失信息。\n让我先尝试搜索。"
    result = strip_agent_artifacts(raw)
    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py::test_strip_agent_artifacts_removes_thinking_prefix -v`
Expected: FAIL with "cannot import name 'strip_agent_artifacts'"

- [ ] **Step 3: Implement strip_agent_artifacts**

```python
# wiki/page_agent.py — add near top, after _CONTEXT_GAP_RE

import re

_THINKING_PREFIX_RE = re.compile(
    r"^(我需要|让我|从工作记忆|需要先|接下来我|首先我|I need to|Let me)",
)
_TOOL_JSON_BLOCK_RE = re.compile(
    r"```json\s*\{[\s\S]*?\"tools\"[\s\S]*?\}\s*```",
    re.MULTILINE,
)
_FIRST_HEADING_RE = re.compile(r"^(#{1,3}\s)", re.MULTILINE)

def strip_agent_artifacts(text: str) -> str:
    """Remove LLM agent thinking/reasoning text and inline tool-call JSON from wiki content."""
    if not text or not text.strip():
        return ""
    stripped = _TOOL_JSON_BLOCK_RE.sub("", text)
    stripped = stripped.strip()
    if _THINKING_PREFIX_RE.match(stripped):
        m = _FIRST_HEADING_RE.search(stripped)
        if m:
            stripped = stripped[m.start():]
        else:
            stripped = ""
    return stripped.strip()
```

- [ ] **Step 4: Wire strip_agent_artifacts into enrich() and fallback paths**

In `wiki/page_agent.py`, modify `enrich()`:

```python
# In the loop, after "if not tool_calls:"
if not tool_calls:
    if text_content:
        cleaned = strip_agent_artifacts(str(text_content))
        if cleaned:
            return cleaned
        log.warning("agent_output_was_pure_thinking", domain=domain_name)
        break  # fall through to fallback
    break

# In the fallback generate() path at the end:
try:
    fallback = await self._llm.generate(
        prompt=self._build_user_prompt(content, gaps, memory, domain_name),
        system=_AGENT_SYSTEM,
    )
    cleaned = strip_agent_artifacts(fallback)
    if cleaned:
        return cleaned
    log.warning("agent_fallback_was_pure_thinking", domain=domain_name)
    return content  # return original content unchanged
except Exception:
    log.warning("agent_fallback_failed", exc_info=True)
    return content
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent.py -k "strip_agent" -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/page_agent.py tests/wiki/test_page_agent.py
git commit -m "fix: strip agent thinking/tool-call artifacts from wiki page content"
```

---

### Task 2: CONTEXT_GAP Publish-Time Cleanup (P1)

**Files:**
- Modify: `wiki/nodes/compose.py`
- Test: `tests/wiki/test_compose_phases.py` (or new test)

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_compose_context_gap_cleanup.py

from wiki.nodes.compose import cleanup_context_gaps

def test_cleanup_context_gaps_replaces_marker():
    content = "## Overview\n\nSome text.\n\n<!-- CONTEXT_GAP: 缺少外部调用者信息 -->\n\nMore text."
    result = cleanup_context_gaps(content)
    assert "CONTEXT_GAP" not in result
    assert "缺少外部调用者信息" in result
    assert "> ℹ️" in result

def test_cleanup_context_gaps_handles_multiple():
    content = "<!-- CONTEXT_GAP: gap1 -->\n\ntext\n\n<!-- CONTEXT_GAP: gap2 -->"
    result = cleanup_context_gaps(content)
    assert result.count("ℹ️") == 2
    assert "CONTEXT_GAP" not in result

def test_cleanup_context_gaps_no_markers():
    content = "## Clean page\n\nNo gaps here."
    result = cleanup_context_gaps(content)
    assert result == content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_context_gap_cleanup.py -v`
Expected: FAIL

- [ ] **Step 3: Implement cleanup_context_gaps**

```python
# wiki/nodes/compose.py — add function

import re

_CONTEXT_GAP_CLEANUP_RE = re.compile(r"<!--\s*CONTEXT_GAP:\s*(.+?)\s*-->")

def cleanup_context_gaps(content: str) -> str:
    """Replace CONTEXT_GAP HTML comments with user-visible info notices."""
    return _CONTEXT_GAP_CLEANUP_RE.sub(r"> ℹ️ 此处信息待补充: \1", content)
```

- [ ] **Step 4: Wire into _sanitize_pages**

In `wiki/nodes/compose.py`, find `_sanitize_pages` (or `sanitize_wiki_content`) and add `cleanup_context_gaps` call at the end:

```python
# Inside the sanitization loop for each page
page_dict["content"] = cleanup_context_gaps(page_dict["content"])
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_context_gap_cleanup.py -v`
Expected: 3 PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/compose.py tests/wiki/test_compose_context_gap_cleanup.py
git commit -m "fix: replace CONTEXT_GAP markers with user-friendly notices at publish time"
```

---

### Task 3: Anti-Hallucination Prompt Strengthening (P0)

**Files:**
- Modify: `wiki/semantic_diagram_gen.py`
- Modify: `wiki/nodes/compose.py` (leaf summary prompt)
- Test: `tests/wiki/test_semantic_diagram_gen.py`

- [ ] **Step 1: Strengthen SemanticDiagramGenerator system prompt**

In `wiki/semantic_diagram_gen.py`, modify `_SYSTEM_PROMPT`:

```python
_SYSTEM_PROMPT = (
    "You are a software architecture diagramming expert. "
    "Generate valid Mermaid syntax only. "
    "No markdown fences, no explanatory text. Return ONLY the Mermaid code.\n\n"
    "CRITICAL CONSTRAINT: All participant names and node labels MUST come from "
    "the entity names provided in the context below. Do NOT invent services, "
    "components, or systems that are not listed. If the provided context is "
    "insufficient for a meaningful diagram, output exactly: NO_DIAGRAM\n\n"
    "Mermaid syntax rules:\n"
    "- Participant names must be simple identifiers (alphanumeric, no spaces, no special chars)\n"
    "- Use aliases for readable labels: participant SVC as ServiceLayer\n"
    "- Arrow messages can contain spaces and punctuation\n"
    "- Keep diagrams concise: 5-10 participants maximum\n"
)
```

- [ ] **Step 2: Strengthen _LEAF_MODULE_SUMMARY_SYSTEM**

In `wiki/nodes/compose.py`, find `_LEAF_MODULE_SUMMARY_SYSTEM` and align anti-hallucination constraint:

```python
_LEAF_MODULE_SUMMARY_SYSTEM = (
    "你是代码模块分析专家。根据提供的模块信息生成结构化摘要。"
    "输出纯 JSON，不要 markdown 围栏。"
    "核心约束：你的输出必须严格基于提供的代码信息。"
    "禁止编造不存在的类名、方法名、服务名或架构组件。"
    "如果某些依赖模块或外部调用的上下文不足，在 summary_text 中用 "
    "<!-- CONTEXT_GAP: 描述 --> 标记缺失部分，不要编造。"
)
```

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_semantic_diagram_gen.py tests/wiki/test_compose_pages_diagrams.py -v`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/semantic_diagram_gen.py wiki/nodes/compose.py
git commit -m "fix: strengthen anti-hallucination constraints in diagram and summary prompts"
```

---

### Task 4: Quality Evaluator Dynamic Truthfulness (P2)

**Files:**
- Modify: `wiki/quality_evaluator.py`
- Test: `tests/wiki/test_wiki_quality_score.py`

- [ ] **Step 1: Write failing test**

```python
# tests/wiki/test_quality_evaluator_truthfulness.py

import pytest
from unittest.mock import MagicMock
from wiki.quality_evaluator import WikiQualityEvaluator

def _make_page(content: str):
    page = MagicMock()
    page.path = "wiki/test-page"
    page.content = content
    page.title = "Test Page"
    page.diagrams = []
    page.source_locations = []
    return page

def test_truthfulness_drops_on_thinking_leak():
    evaluator = WikiQualityEvaluator()
    page = _make_page("我需要查询两个缺失信息。\n\n## 概述\n\n内容。")
    score = evaluator.structural_check(page)
    assert score.truthfulness < 1.0

def test_truthfulness_stays_high_for_clean_page():
    evaluator = WikiQualityEvaluator()
    page = _make_page("## 业务概述\n\n正常内容。\n\n## 核心服务详解\n\n详细说明。")
    score = evaluator.structural_check(page)
    assert score.truthfulness == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_evaluator_truthfulness.py -v`
Expected: FAIL (truthfulness is always 1.0)

- [ ] **Step 3: Implement dynamic truthfulness**

In `wiki/quality_evaluator.py`, modify `structural_check`:

```python
# Near the end of structural_check, before building the score object:
import re
_THINKING_LEAK_RE = re.compile(r"^(我需要|让我|从工作记忆|I need to|Let me)")
_FAKE_SOURCE_RE = re.compile(r"com/xxx/|source://src/")

truthfulness = 1.0
body = page.content or ""
if _THINKING_LEAK_RE.match(body.strip()):
    truthfulness -= 0.4
    issues.append("thinking_leak_detected")
if _FAKE_SOURCE_RE.search(body):
    truthfulness -= 0.3
    issues.append("fake_source_detected")
truthfulness = max(0.0, truthfulness)
```

Replace `truthfulness=1.0` in the return statement with `truthfulness=round(truthfulness, 2)`.

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_evaluator_truthfulness.py -v`
Expected: 2 PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/quality_evaluator.py tests/wiki/test_quality_evaluator_truthfulness.py
git commit -m "fix: compute truthfulness dynamically instead of hardcoding 1.0"
```

---

## Phase B: Business-Scoped Indexing

### Task 5: Backend — IndexBody business_id Required

**Files:**
- Modify: `api/models/index_models.py`
- Modify: `api/routes/index_routes.py`
- Test: `tests/api/test_index_routes.py` (existing or new)

- [ ] **Step 1: Write failing test — business_id required**

```python
# tests/api/test_index_business_id.py

import pytest
from fastapi.testclient import TestClient

def test_index_without_business_id_returns_422(client):
    """POST /index without business_id should fail validation."""
    resp = client.post("/api/v1/index", json={
        "repo_url": "https://example.com/repo.git",
    }, headers={"Authorization": "Bearer sk-admin-test"})
    assert resp.status_code == 422

def test_index_with_business_id_accepted(client):
    """POST /index with business_id should not fail validation (may fail on repo)."""
    resp = client.post("/api/v1/index", json={
        "repo_url": "https://example.com/repo.git",
        "business_id": "test-biz",
    }, headers={"Authorization": "Bearer sk-admin-test"})
    # 422 = validation error, anything else = validation passed
    assert resp.status_code != 422
```

Note: You'll need to check the actual test client setup in the project and adapt accordingly. Look at existing `tests/api/test_*.py` files for the fixture pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/api/test_index_business_id.py -v`
Expected: FAIL (business_id not required yet)

- [ ] **Step 3: Add business_id to IndexBody**

Find `IndexBody` in `api/models/index_models.py` and add:

```python
business_id: str  # Required — graph name will be kb_{business_id}
```

- [ ] **Step 4: Wire business_id through index_routes.py to ServiceRegistry**

In `api/routes/index_routes.py`, find the index endpoint and pass `body.business_id` to the indexing pipeline so that `ServiceRegistry.get_graph_store(body.business_id)` is used. Check how `ServiceRegistry` is currently invoked and add the business_id parameter.

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/api/test_index_business_id.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add api/models/index_models.py api/routes/index_routes.py tests/api/test_index_business_id.py
git commit -m "feat: require business_id in index requests for graph isolation"
```

---

### Task 6: Frontend — Indexing.tsx Business Selector

**Files:**
- Modify: `dashboard/src/pages/Indexing.tsx`

- [ ] **Step 1: Add business selector to Indexing.tsx**

Read the current `dashboard/src/pages/Indexing.tsx` to understand the existing form structure. Add:

1. Import `useBusiness` hook (check existing Business pages for the hook location)
2. Add a business selector dropdown at the top of the form (required)
3. When `businesses.length === 0` or no business selected, disable the index button and show "请先创建业务"
4. Include `business_id` in the index request body

- [ ] **Step 2: Verify in browser**

Navigate to `http://172.18.228.71:8100/indexing` and verify:
- Business selector appears
- Cannot submit without selecting a business
- Index request includes business_id

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Indexing.tsx
git commit -m "feat: add required business selector to indexing page"
```

---

### Task 7: Frontend — Repositories.tsx Business Filter

**Files:**
- Modify: `dashboard/src/pages/Repositories.tsx`

- [ ] **Step 1: Add business context to Repositories.tsx**

Read `dashboard/src/pages/Repositories.tsx`. Add:

1. Display current business name at the top
2. Filter repository list by current business (only show repos indexed under current business)

- [ ] **Step 2: Verify in browser**

- [ ] **Step 3: Commit**

```bash
git add dashboard/src/pages/Repositories.tsx
git commit -m "feat: filter repositories by current business context"
```

---

## Phase C: Pipeline Progress Enhancement

### Task 8: Backend — LangGraph Event Stream + Node-Phase Mapping

**Files:**
- Modify: `wiki/service.py`
- Test: `tests/wiki/test_service_progress.py`

- [ ] **Step 1: Define node name → phase mapping**

```python
# wiki/service.py — add constant

_NODE_PHASE_MAP: dict[str, tuple[str, float]] = {
    # node_name: (phase_name, cumulative_base_pct)
    "classify_entities_node": ("classify_entities", 0.0),
    "classify_domains_node": ("classify_domains", 0.05),
    "compose_leaf_pages_node": ("compose_leaf", 0.10),
    "compose_parent_pages_node": ("parent_aggregate", 0.65),
    "synthesize_overviews_node": ("overview", 0.80),
    "heal_pages_node": ("quality_eval", 0.85),
    "create_links_node": ("linking", 0.90),
    "persist_node": ("persisting", 0.95),
}
```

Note: Verify actual node function names by reading `wiki/pipeline_orchestrator.py` or the LangGraph graph definition. Adapt the mapping accordingly.

- [ ] **Step 2: Write failing test for phase mapping**

```python
# tests/wiki/test_service_progress.py

from wiki.service import _NODE_PHASE_MAP

def test_node_phase_map_covers_all_phases():
    phases = {v[0] for v in _NODE_PHASE_MAP.values()}
    expected = {"classify_entities", "classify_domains", "compose_leaf",
                "parent_aggregate", "overview", "quality_eval", "linking", "persisting"}
    assert phases == expected

def test_node_phase_map_percentages_ascending():
    pcts = [v[1] for v in _NODE_PHASE_MAP.values()]
    assert pcts == sorted(pcts)
```

- [ ] **Step 3: Implement event stream listener in wiki/service.py**

In the wiki generation function (likely `generate_business_wiki` or similar), replace the current pipeline invocation with `astream_events` usage:

```python
async for event in graph.astream_events(state, config=config, version="v2"):
    kind = event.get("event")
    name = event.get("name", "")
    if kind == "on_chain_start" and name in _NODE_PHASE_MAP:
        phase, base_pct = _NODE_PHASE_MAP[name]
        await progress_callback(phase=phase, progress_pct=base_pct, detail=f"{phase} 开始")
```

Ensure `progress_callback` updates `task_store` with the phase/pct/detail.

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_service_progress.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/service.py tests/wiki/test_service_progress.py
git commit -m "feat: add LangGraph event stream listener for automatic phase tracking"
```

---

### Task 9: Backend — compose_leaf Fine-Grained Progress Callback

**Files:**
- Modify: `wiki/nodes/compose.py`

- [ ] **Step 1: Add progress callback to compose_leaf_modules_node**

In `compose_leaf_modules_node` (or `compose_leaf_pages_node`), find the batch loop that processes modules. Add a progress callback every N modules:

```python
# Inside the module processing loop
progress_callback = configurable.get("progress_callback")
for i, batch in enumerate(batches):
    # ... existing batch processing ...
    if progress_callback and (i + 1) % 10 == 0:
        done = min((i + 1) * batch_size, total_modules)
        pct = 0.10 + 0.55 * (done / total_modules)  # 10% base + 55% weight
        await progress_callback(
            phase="compose_leaf",
            progress_pct=round(pct, 3),
            detail=f"模块合成 {done}/{total_modules}",
        )
```

- [ ] **Step 2: Run existing compose tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_phases.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add wiki/nodes/compose.py
git commit -m "feat: add fine-grained progress callback in compose_leaf module processing"
```

---

### Task 10: Backend — wiki_task_routes Progress API Adaptation

**Files:**
- Modify: `api/routes/wiki_task_routes.py`

- [ ] **Step 1: Ensure detail field is exposed in task status API**

Check `api/routes/wiki_task_routes.py` to verify the task status endpoint returns `detail` field. If `update_status` already supports `**extra`, and the response serializes all fields, this may be a no-op. Verify and add if missing.

- [ ] **Step 2: Verify with curl**

```bash
# After starting a wiki generation task, poll status:
curl -H "Authorization: Bearer sk-admin-test" "http://172.18.228.71:8100/api/v1/wiki/business/tasks/{task_id}"
```

Verify `detail` field appears in response.

- [ ] **Step 3: Commit (if changes needed)**

```bash
git add api/routes/wiki_task_routes.py
git commit -m "feat: expose detail field in wiki task status API"
```

---

### Task 11: Frontend — WikiActiveTasks Phase Indicator + Detail

**Files:**
- Modify: `dashboard/src/components/wiki/WikiActiveTasks.tsx`
- Modify: `dashboard/src/i18n/zh.ts`
- Modify: `dashboard/src/i18n/en.ts`

- [ ] **Step 1: Extend phaseI18nKeys**

Read current `WikiActiveTasks.tsx` to find `phaseI18nKeys` mapping. Add missing phases:

```typescript
const phaseI18nKeys: Record<string, string> = {
  classify_entities: 'wiki.phase.classify_entities',
  classify_domains: 'wiki.phase.classify_domains',
  compose_leaf: 'wiki.phase.compose_leaf',
  parent_aggregate: 'wiki.phase.parent_aggregate',
  overview: 'wiki.phase.overview',
  quality_eval: 'wiki.phase.quality_eval',
  linking: 'wiki.phase.linking',
  persisting: 'wiki.phase.persisting',
  // keep existing mappings too
};
```

- [ ] **Step 2: Add i18n translations**

In `dashboard/src/i18n/zh.ts`:
```typescript
'wiki.phase.classify_entities': '实体分类',
'wiki.phase.classify_domains': '域分类',
'wiki.phase.compose_leaf': '模块合成',
'wiki.phase.parent_aggregate': '父域聚合',
'wiki.phase.overview': '系统概览',
'wiki.phase.quality_eval': '质量修复',
'wiki.phase.linking': '交叉引用',
'wiki.phase.persisting': '持久化',
```

In `dashboard/src/i18n/en.ts`:
```typescript
'wiki.phase.classify_entities': 'Classifying Entities',
'wiki.phase.classify_domains': 'Classifying Domains',
'wiki.phase.compose_leaf': 'Composing Modules',
'wiki.phase.parent_aggregate': 'Aggregating Domains',
'wiki.phase.overview': 'System Overview',
'wiki.phase.quality_eval': 'Quality Healing',
'wiki.phase.linking': 'Cross-referencing',
'wiki.phase.persisting': 'Persisting',
```

- [ ] **Step 3: Add stage flow indicator UI**

In `WikiActiveTasks.tsx`, add a horizontal step indicator showing all phases with current phase highlighted and completed phases checked.

- [ ] **Step 4: Display task.detail text**

Show `task.detail` (e.g., "模块合成 400/847") below or beside the progress bar.

- [ ] **Step 5: Verify in browser**

Navigate to wiki generation and observe:
- Stage indicator shows phases
- Current phase highlighted
- Detail text updates
- Progress bar advances

- [ ] **Step 6: Commit**

```bash
git add dashboard/src/components/wiki/WikiActiveTasks.tsx dashboard/src/i18n/zh.ts dashboard/src/i18n/en.ts
git commit -m "feat: add phase flow indicator and detail text to wiki progress UI"
```

---

## Phase E: Verification

### Task 12: End-to-End Verification

- [ ] **Step 1: Run full test suite**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
uv run pytest tests/ -x --timeout=60 -q
```

- [ ] **Step 2: Build frontend**

```bash
cd dashboard && pnpm build
```

- [ ] **Step 3: Integration test — index with business_id + generate wiki + verify quality**

1. Create a business via API
2. Index a repo with that business_id
3. Generate wiki for that business
4. Run the quality scan script to verify:
   - 0 THINKING_LEAK pages
   - 0 raw CONTEXT_GAP markers
   - Progress was tracked during generation
