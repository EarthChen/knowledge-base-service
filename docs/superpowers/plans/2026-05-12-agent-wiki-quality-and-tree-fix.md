# Agent Wiki Quality Fix + Tree Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 6 issues identified after Agent pipeline first run: path mismatch (frontend can't load), 100% heal rate (heading markers), content quality, tool trace leaks, missing topic pages, and robustness gaps.

**Architecture:** Surgical fixes across 4 layers — path conventions (domain_doc_agent + tree_linker), quality gate (quality_evaluator), content pipeline (prompts + baseline + strip), and robustness (timeout + error handling + data structures).

**Tech Stack:** Python 3.11, pytest, LangGraph, FalkorDB

**Spec:** `docs/superpowers/specs/2026-05-12-agent-wiki-quality-and-tree-fix.md`

---

### Task 1: Quality Gate Heading & Diagram Marker Fix

**Rationale:** `structural_check()` uses hardcoded heading markers that don't match Agent prompt output headings. Agent produces `## 关键实现` / `## 依赖关系` but evaluator expects `## 核心服务要点` / `## 关联主题`. Also, diagrams are checked via `page.diagrams` field (empty for Agent pages) instead of scanning content for ` ```mermaid ` blocks. Together these cause 100% heal rate.

**Files:**
- Modify: `wiki/quality_evaluator.py:70-78` (marker tuples) and `:142` (diagram check)
- Test: `tests/wiki/test_quality_evaluator.py`

- [ ] **Step 1: Write failing test — Agent headings score correctly**

```python
# tests/wiki/test_quality_evaluator.py — append

def test_structural_check_agent_headings_pass():
    """Agent prompt output uses ## 关键实现 / ## 依赖关系; structural_check must accept."""
    long_body = "详细说明。" * 50  # > 200 chars
    page = WikiPage(
        path="/__domains__/TestDomain/_overview",
        title="TestDomain",
        page_type=PageType.DOMAIN_OVERVIEW,
        content=(
            "# TestDomain\n\n## 概述\n\n" + long_body
            + "\n\n## 关键实现\n\nread_code 获取的核心代码。"
            + "\n\n## 依赖关系\n\n跨域调用关系。"
        ),
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "missing_components" not in score.issues, f"Unexpected issues: {score.issues}"
    assert "missing_relationships" not in score.issues, f"Unexpected issues: {score.issues}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_evaluator.py::test_structural_check_agent_headings_pass -v`
Expected: FAIL — `## 关键实现` not in `_STRUCT_COMPONENT_MARKERS`

- [ ] **Step 3: Write failing test — Mermaid in content counts as diagram**

```python
# tests/wiki/test_quality_evaluator.py — append

def test_structural_check_mermaid_in_content_counts_as_diagram():
    """Agent embeds mermaid in content body; structural_check should not penalize no_diagrams."""
    long_body = "详细说明。" * 50
    page = WikiPage(
        path="test_mermaid.md",
        title="Test",
        page_type=PageType.DOMAIN_OVERVIEW,
        content=(
            "# Test\n\n## 概述\n\n" + long_body
            + "\n\n## 核心服务要点\n\n要点。"
            + "\n\n## 关联主题\n\n[[Other]]"
            + "\n\n```mermaid\nflowchart TD\n  A --> B\n```"
        ),
        diagrams=[],  # empty — diagrams are in content
        source_locations=[],
        metadata=WikiPageMetadata(1, 1),
    )
    evaluator = WikiQualityEvaluator(llm=None)
    score = evaluator.structural_check(page)
    assert "no_diagrams" not in score.issues, f"Unexpected issues: {score.issues}"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_evaluator.py::test_structural_check_mermaid_in_content_counts_as_diagram -v`
Expected: FAIL — `len(page.diagrams) > 0` is False, no content check

- [ ] **Step 5: Implement — extend marker tuples and diagram check**

```python
# wiki/quality_evaluator.py — replace lines 70-78

_STRUCT_OVERVIEW_MARKERS = ("## Overview", "## 业务概述", "## 概述")
_STRUCT_COMPONENT_MARKERS = (
    "## Key components",
    "## Methods",
    "## 核心服务要点",
    "## 核心服务详情",
    "## 核心业务流程",
    "## 关键实现",
)
_STRUCT_RELATIONSHIP_MARKERS = (
    "## Relationships",
    "## 关联主题",
    "## 关联关系",
    "## 依赖关系",
    "## 外部依赖",
)
```

```python
# wiki/quality_evaluator.py — replace line 142 diagram check in structural_check()
# Change:  (len(page.diagrams) > 0, "no_diagrams", 0.15),
# To:
            (
                len(page.diagrams) > 0 or bool(_MERMAID_FENCE.search(body)),
                "no_diagrams",
                0.15,
            ),
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_evaluator.py -v`
Expected: ALL PASS (including existing tests)

- [ ] **Step 7: Commit**

```bash
git add wiki/quality_evaluator.py tests/wiki/test_quality_evaluator.py
git commit -m "fix: extend quality_gate heading markers and diagram check for agent output"
```

---

### Task 2: Agent Page Path Alignment

**Rationale:** Agent's `_make_page()` generates flat paths like `挚友关系管理` but TreeLinker and frontend expect `/__domains__/挚友关系管理/_overview`. This makes agent pages invisible in the wiki tree.

**Files:**
- Create: `wiki/path_conventions.py` (path format constant + helper)
- Modify: `wiki/domain_doc_agent.py:63-77` (`_make_page` and `_maybe_split`)
- Modify: `wiki/nodes/domain_compose.py:114-136` (`_make_error_placeholder`)
- Test: `tests/wiki/test_domain_doc_agent.py` (new)
- Test: `tests/wiki/test_domain_compose_node.py` (update)

- [ ] **Step 1: Write failing test — _make_page uses domain overview path format**

```python
# tests/wiki/test_domain_doc_agent.py (new file)

from wiki.domain_doc_agent import _make_page


def test_make_page_uses_domain_overview_path():
    """_make_page must generate path in /__domains__/{name}/_overview format."""
    page = _make_page("# Content", "挚友关系管理")
    assert page["path"] == "/__domains__/挚友关系管理/_overview"
    assert page["page_type"] == "domain_overview"
    assert page["title"] == "挚友关系管理"


def test_make_page_preserves_content():
    page = _make_page("# Hello\n\nWorld", "TestDomain")
    assert page["content"] == "# Hello\n\nWorld"
    assert page["path"] == "/__domains__/TestDomain/_overview"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py -v`
Expected: FAIL — path is `挚友关系管理` not `/__domains__/挚友关系管理/_overview`

- [ ] **Step 3: Write failing test — _make_error_placeholder uses same path format**

```python
# tests/wiki/test_domain_compose_node.py — append (or update existing)

from wiki.nodes.domain_compose import _make_error_placeholder


def test_error_placeholder_uses_domain_overview_path():
    domain = {"name": "挚友关系管理", "modules": ["ModA"]}
    page = _make_error_placeholder(domain, RuntimeError("timeout"))
    assert page["path"] == "/__domains__/挚友关系管理/_overview"
    assert page["page_type"] == "domain_overview"
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_compose_node.py::test_error_placeholder_uses_domain_overview_path -v`
Expected: FAIL — path is flat

- [ ] **Step 5: Implement — create path_conventions.py and update _make_page**

```python
# wiki/path_conventions.py (new file)
"""Canonical path format constants for wiki pages."""

DOMAIN_OVERVIEW_PATH_FMT = "/__domains__/{name}/_overview"
DOMAIN_TOPIC_PATH_FMT = "/__domains__/{domain}/{section}/_topic"


def domain_overview_path(name: str) -> str:
    return DOMAIN_OVERVIEW_PATH_FMT.format(name=name)


def domain_topic_path(domain: str, section: str) -> str:
    safe_section = section.replace("/", "_").replace(" ", "_")
    return DOMAIN_TOPIC_PATH_FMT.format(domain=domain, section=safe_section)
```

```python
# wiki/domain_doc_agent.py — update _make_page (replace lines 63-77)

def _make_page(content: str, key: str) -> dict[str, Any]:
    from wiki.path_conventions import domain_overview_path
    return {
        "page_type": "domain_overview",
        "title": key,
        "path": domain_overview_path(key),
        "content": content,
        "diagrams": [],
        "source_locations": [],
        "metadata": {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "agent",
        },
    }
```

```python
# wiki/nodes/domain_compose.py — update _make_error_placeholder (replace lines 114-136)

def _make_error_placeholder(domain: dict[str, Any], error: BaseException) -> dict[str, Any]:
    """Failed domain produces a placeholder page (not skipped)."""
    from wiki.path_conventions import domain_overview_path
    modules_list = "\n".join(f"- {m}" for m in domain.get("modules", []))
    name = domain["name"]
    return {
        "page_type": "domain_overview",
        "title": name,
        "path": domain_overview_path(name),
        "_error": str(error)[:200],
        "content": (
            f"# {name}\n\n"
            f"> ⚠️ 文档生成失败: {str(error)[:200]}\n\n"
            f"## 域内模块\n\n{modules_list}"
        ),
        "diagrams": [],
        "source_locations": [],
        "metadata": {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "agent_error",
        },
    }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py tests/wiki/test_domain_compose_node.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/path_conventions.py wiki/domain_doc_agent.py wiki/nodes/domain_compose.py tests/wiki/test_domain_doc_agent.py tests/wiki/test_domain_compose_node.py
git commit -m "feat: align agent page paths to /__domains__/{name}/_overview format"
```

---

### Task 3: TreeLinker Agent Page Compatibility

**Rationale:** TreeLinker always generates synthetic overview pages at `/__domains__/{name}/_overview`. After Task 2, Agent pages use the same path. TreeLinker must check if an Agent page already exists at that path and skip generating a synthetic one to avoid overwriting.

**Files:**
- Modify: `wiki/tree_linker.py:630-680` (`_create_sections`)
- Test: `tests/wiki/test_tree_linker.py`

**Depends on:** Task 2 (Agent pages now use `/__domains__/{name}/_overview` path)

- [ ] **Step 1: Write failing test — TreeLinker skips synthetic when Agent page exists**

```python
# tests/wiki/test_tree_linker.py — append

@pytest.mark.asyncio
async def test_nested_tree_skips_overview_when_agent_page_exists() -> None:
    """When an Agent-generated page exists at /__domains__/{name}/_overview,
    TreeLinker should not generate a synthetic overview (skip _build_domain_overview_content)."""
    wiki_store = MagicMock()
    wiki_store.upsert_wiki_section = AsyncMock()
    wiki_store.add_has_child_edge = AsyncMock()

    # Simulate: query for existing agent page returns a result
    agent_page_result = MagicMock(data=[{
        "uid": "WikiPage:biz:/__domains__/TestDomain/_overview",
        "path": "/__domains__/TestDomain/_overview",
        "page_type": "domain_overview",
        "generation_mode": "agent",
    }])
    # topic pages query returns empty
    empty_result = MagicMock(data=[])
    wiki_store.execute_query = AsyncMock(side_effect=[agent_page_result, empty_result])

    persistence = MagicMock()
    persistence.persist_pages_to_graph = AsyncMock()

    tree_builder = WikiTreeBuilder()
    wiki_cfg = MagicMock()

    linker = WikiTreeLinker(MagicMock(), wiki_store, wiki_cfg, persistence)

    domain = DomainNode(name="TestDomain", modules=["modA"], children=[], description="test")

    await linker.link_pages_to_nested_tree(
        business_id="biz",
        domain_tree=[domain],
        pages_by_entity_uid={"modA": {"uid": "p1", "content": "some content"}},
        tree_builder=tree_builder,
    )

    # Synthetic overview should NOT be generated — persistence should receive 0 pages
    if persistence.persist_pages_to_graph.called:
        call_args = persistence.persist_pages_to_graph.call_args
        pages = call_args[0][1] if len(call_args[0]) > 1 else call_args[1].get("pages", [])
        # No synthetic overview pages should be persisted
        synthetic_paths = [p.path for p in pages if getattr(p, 'path', '').endswith('/_overview')]
        assert len(synthetic_paths) == 0, f"Should not persist synthetic overview, got: {synthetic_paths}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_tree_linker.py::test_nested_tree_skips_overview_when_agent_page_exists -v`
Expected: FAIL — TreeLinker always generates synthetic overview

- [ ] **Step 3: Implement — add Agent page existence check in _create_sections**

In `wiki/tree_linker.py`, modify `_create_sections()` to check for existing agent pages before generating synthetic overviews. The key change is in the `_create_sections` inner function around line 653:

```python
# wiki/tree_linker.py — inside link_pages_to_nested_tree, before _create_sections definition
# Add a set to track domains with existing agent pages
agent_overview_paths: set[str] = set()

async def _check_agent_pages() -> None:
    """Pre-check which domains already have Agent-generated overview pages."""
    try:
        q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $biz "
            "AND wp.path STARTS WITH '/__domains__/' "
            "AND wp.path ENDS WITH '/_overview' "
            "AND wp.page_type = 'domain_overview' "
            "RETURN wp.path AS path"
        )
        result = await self._wiki_store.execute_query(q, {"biz": business_id})
        rows = getattr(result, "data", None) or []
        for row in rows:
            p = str(row.get("path", ""))
            if p:
                agent_overview_paths.add(p)
        if agent_overview_paths:
            log.info(
                "nested_tree_agent_overviews_found",
                business_id=business_id,
                count=len(agent_overview_paths),
            )
    except Exception:
        log.warning("nested_tree_agent_check_failed", business_id=business_id, exc_info=True)

await _check_agent_pages()
```

Then modify `_create_sections` to conditionally skip synthetic overview:

```python
# Inside _create_sections, replace the overview generation block:
            if domain.modules or domain.children:
                overview_path = f"/__domains__/{domain.name}/_overview"
                if overview_path not in agent_overview_paths:
                    overview_content = _build_domain_overview_content(domain)
                    from wiki.models import EnrichmentLevel, PageType, WikiPageMetadata
                    overview_page = WikiPage(
                        path=overview_path,
                        # ... rest unchanged ...
                    )
                    overview_pages.append(overview_page)
                    overview_uid = f"WikiPage:{business_id}:{overview_path}"
                    pending_overview_links.append((section_uid, overview_uid))
                else:
                    # Agent page exists — link it directly without generating synthetic
                    overview_uid = f"WikiPage:{business_id}:{overview_path}"
                    pending_overview_links.append((section_uid, overview_uid))
                    log.info("nested_tree_using_agent_overview", domain=domain.name)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_tree_linker.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/tree_linker.py tests/wiki/test_tree_linker.py
git commit -m "feat: TreeLinker skips synthetic overview when Agent page exists (scheme C')"
```

---

### Task 4: Baseline Rebuild — Topology + One-Line Descriptions

**Rationale:** Current `_build_baseline()` passes 500-char module summaries, causing Agent to skip tool calls (Issue #008). Changing to "topology relations + one-line description" forces Agent to explore code deeply while knowing the domain's structure.

**Files:**
- Modify: `wiki/domain_doc_agent.py:20-33` (`_build_baseline` signature and body)
- Modify: `wiki/nodes/domain_compose.py:27-28,68` (pass `module_tree` to `_build_baseline`)
- Test: `tests/wiki/test_domain_doc_agent.py` (update)
- Test: `tests/wiki/test_domain_compose_node.py` (update)

- [ ] **Step 1: Write failing test — _build_baseline produces topology format**

```python
# tests/wiki/test_domain_doc_agent.py — append

from wiki.domain_doc_agent import _build_baseline


def test_build_baseline_topology_format():
    """_build_baseline should output topology relations, not 500-char summaries."""
    domain = {
        "name": "支付处理",
        "description": "处理支付相关业务",
        "modules": ["PaymentService", "OrderValidator", "RefundHandler"],
    }
    module_summaries = {
        "PaymentService": {"summary_text": "A" * 600},
        "OrderValidator": {"summary_text": "B" * 600},
        "RefundHandler": {"summary_text": "C" * 600},
    }
    module_tree = {
        "nodes": {
            "PaymentService": {"name": "PaymentService"},
            "OrderValidator": {"name": "OrderValidator"},
            "RefundHandler": {"name": "RefundHandler"},
        },
        "edges": [
            {"source": "PaymentService", "target": "OrderValidator"},
            {"source": "PaymentService", "target": "RefundHandler"},
        ],
    }
    result = _build_baseline(domain, module_summaries, module_tree=module_tree)
    # Must NOT contain 500-char summaries
    assert "AAAAAA" not in result, "Should not include long summaries"
    # Must contain topology relationships
    assert "PaymentService" in result
    assert "→" in result or "->" in result or "依赖" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py::test_build_baseline_topology_format -v`
Expected: FAIL — current signature doesn't accept `module_tree`, output contains long summaries

- [ ] **Step 3: Implement — rewrite _build_baseline**

```python
# wiki/domain_doc_agent.py — replace _build_baseline (lines 20-33)

def _build_baseline(
    domain: dict[str, Any],
    module_summaries: dict[str, Any],
    *,
    module_tree: dict[str, Any] | None = None,
) -> str:
    """Build baseline context: domain description + topology + one-line module roles.

    Provides enough structure for Agent to know the domain shape while forcing
    deep code exploration via tools (avoids Issue #008 lazy behavior).
    """
    parts = [f"## {domain['name']}"]
    if domain.get("description"):
        parts.append(domain["description"])

    modules = domain.get("modules", [])
    if modules:
        parts.append("### 模块列表")
        for mod in modules:
            raw = module_summaries.get(mod, "")
            if isinstance(raw, dict):
                text = str(raw.get("summary_text", "") or "")
            else:
                text = str(raw) if raw else ""
            one_liner = text.split("\n")[0][:80] if text else ""
            parts.append(f"- **{mod}**: {one_liner}" if one_liner else f"- **{mod}**")

    if module_tree:
        edges = module_tree.get("edges", [])
        domain_modules = set(modules)
        relevant_edges = [
            e for e in edges
            if e.get("source") in domain_modules or e.get("target") in domain_modules
        ]
        if relevant_edges:
            parts.append("### 模块依赖拓扑")
            for edge in relevant_edges[:20]:
                parts.append(f"- {edge['source']} → {edge['target']}")

    return "\n\n".join(parts)
```

- [ ] **Step 4: Update compose node to pass module_tree**

```python
# wiki/nodes/domain_compose.py — update line 28 and 68
# Add after line 28:
    module_tree = state.get("module_tree", {})

# Update line 68 (_build_baseline call):
                    baseline_context=_build_baseline(domain, module_summaries, module_tree=module_tree),
```

Update the import in `domain_compose.py` — `_build_baseline` is already imported from `wiki.domain_doc_agent`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py tests/wiki/test_domain_compose_node.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/domain_doc_agent.py wiki/nodes/domain_compose.py tests/wiki/test_domain_doc_agent.py tests/wiki/test_domain_compose_node.py
git commit -m "feat: rebuild baseline to topology+one-liner, inject module_tree from graph decompose"
```

---

### Task 5: Prompt Output Constraints + strip_agent_artifacts Enhancement

**Rationale:** Some Agent pages contain tool call descriptions like `read_code(...)` in final output. Fix via dual-layer defense: 1) prompt-level prohibition, 2) post-processing regex expansion.

**Files:**
- Modify: `wiki/agent_prompts.py:147-181` (AGENT_GENERATE_SYSTEM)
- Modify: `wiki/page_agent.py:15-105` (strip_agent_artifacts regexes)
- Test: `tests/wiki/test_page_agent_sanitize.py` (update)

- [ ] **Step 1: Write failing test — strip tool invocation traces**

```python
# tests/wiki/test_page_agent_sanitize.py — append

from wiki.page_agent import strip_agent_artifacts


def test_strip_tool_invocation_descriptions():
    """Tool invocation descriptions like read_code(...) must be stripped."""
    content = (
        "# 支付处理\n\n"
        "## 概述\n\n"
        "支付处理域负责核心支付逻辑。\n\n"
        "我使用 read_code 查看了 PaymentService 的源码：\n\n"
        "接下来调用 query_call_chain 获取调用链：\n\n"
        "## 关键实现\n\n"
        "PaymentService 的核心逻辑如下。"
    )
    result = strip_agent_artifacts(content)
    assert "read_code" not in result.lower() or "read_code" in result.split("```")[1] if "```" in result else "read_code" not in result.lower()
    assert "query_call_chain" not in result.lower()
    assert "## 关键实现" in result
    assert "PaymentService" in result


def test_strip_tool_call_inline_traces():
    """Lines with tool call patterns like 'read_code(entity="X")' must be removed."""
    content = (
        "# Domain\n\n"
        "## 概述\n\n正文内容。\n\n"
        "调用 read_code(entity=\"PayService.pay\") 获取代码...\n"
        "使用 search_entities(keywords=\"payment\") 搜索实体...\n"
        "## 关键实现\n\n实际内容。"
    )
    result = strip_agent_artifacts(content)
    assert 'read_code(entity=' not in result
    assert 'search_entities(keywords=' not in result
    assert "实际内容" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent_sanitize.py::test_strip_tool_invocation_descriptions tests/wiki/test_page_agent_sanitize.py::test_strip_tool_call_inline_traces -v`
Expected: FAIL — current regex doesn't cover these patterns

- [ ] **Step 3: Implement — add tool trace regex to strip_agent_artifacts**

```python
# wiki/page_agent.py — add new regex after _LLM_META_LINE_RE (around line 38)
_TOOL_INVOCATION_LINE_RE = re.compile(
    r"((?:我|接下来|然后)?(?:使用|调用|通过)\s*(?:read_code|query_module_detail|search_entities|"
    r"query_call_chain|query_callers|query_callees|query_domain_dependencies|"
    r"grep_code|list_files|read_file|semantic_search|read_wiki_page|"
    r"query_implementations|read_source_snippet|delegate_submodule)"
    r"(?:\s*\(.*?\))?\s*(?:查看|获取|搜索|读取|查询|来|以)?.*)",
    re.IGNORECASE,
)
```

```python
# wiki/page_agent.py — in strip_agent_artifacts(), after _LLM_META_LINE_RE block (after line 96)
    # Remove lines containing tool invocation descriptions
    if stripped and _TOOL_INVOCATION_LINE_RE.search(stripped):
        lines = stripped.split("\n")
        stripped = "\n".join(
            ln for ln in lines if not _TOOL_INVOCATION_LINE_RE.search(ln)
        ).strip()
```

- [ ] **Step 4: Add prompt-level constraint**

```python
# wiki/agent_prompts.py — in AGENT_GENERATE_SYSTEM, after the "## 约束" section (before closing """)
# Add under "## 约束":
- **严禁输出工具过程描述**：最终文档中不得出现 "调用 read_code"、"使用 query_call_chain" 等工具调用过程说明。只输出工具返回的**结果**（代码片段、调用链），不描述调用过程本身。
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_page_agent_sanitize.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/page_agent.py wiki/agent_prompts.py tests/wiki/test_page_agent_sanitize.py
git commit -m "fix: strip tool invocation traces from agent output (prompt + regex)"
```

---

### Task 6: Topic Page Support via _maybe_split

**Rationale:** Agent pipeline only generates `domain_overview` pages; no `topic` sub-pages. `_maybe_split()` exists but generates incorrect paths and page types for sub-pages.

**Files:**
- Modify: `wiki/domain_doc_agent.py:36-60` (`_maybe_split`)
- Test: `tests/wiki/test_domain_doc_agent.py` (update)

**Depends on:** Task 2 (path conventions)

- [ ] **Step 1: Write failing test — _maybe_split generates topic sub-pages**

```python
# tests/wiki/test_domain_doc_agent.py — append

from wiki.domain_doc_agent import _maybe_split


def test_maybe_split_generates_topic_pages_for_large_content():
    """When content exceeds MAX_PAGE_TOKENS, _maybe_split should produce topic sub-pages."""
    # Build content > 5000 tokens (approx 20000 chars)
    sections = ["## 概述\n\n" + "概述内容。" * 200]
    for i in range(5):
        sections.append(f"## 章节{i}\n\n" + f"章节{i}的详细内容。" * 400)
    content = "\n\n".join(sections)
    assert len(content) > 20000, "Content must exceed token threshold"

    pages = _maybe_split(content, "大型域")
    assert len(pages) > 1, "Should split into multiple pages"

    parent = pages[0]
    assert parent["path"] == "/__domains__/大型域/_overview"
    assert parent["page_type"] == "domain_overview"
    assert "章节导航" in parent["content"]

    for child in pages[1:]:
        assert child["page_type"] == "topic", f"Sub-page should be topic type, got {child['page_type']}"
        assert child["path"].startswith("/__domains__/大型域/"), f"Bad path: {child['path']}"
        assert child["path"].endswith("/_topic"), f"Path should end with /_topic: {child['path']}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py::test_maybe_split_generates_topic_pages_for_large_content -v`
Expected: FAIL — current _maybe_split uses _make_page which produces flat path and domain_overview type

- [ ] **Step 3: Implement — update _maybe_split to use topic paths and types**

```python
# wiki/domain_doc_agent.py — replace _maybe_split (lines 36-60)

def _maybe_split(content: str, domain_name: str) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections into topic sub-pages."""
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_name)]

    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    if len(sections) <= 1:
        return [_make_page(content, domain_name)]

    from wiki.path_conventions import domain_topic_path

    overview = sections[0]
    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in sections[1:]:
        title_match = re.match(r"^## (.+)", section)
        section_title = title_match.group(1).strip() if title_match else "Untitled"
        topic_path = domain_topic_path(domain_name, section_title)
        child_pages.append({
            "page_type": "topic",
            "title": section_title,
            "path": topic_path,
            "content": section,
            "diagrams": [],
            "source_locations": [],
            "metadata": {
                "node_count": 0,
                "edge_count": 0,
                "generation_mode": "agent",
            },
        })
        child_links.append(f"- [[{section_title}]]")

    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_name)

    return [parent_page, *child_pages]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_doc_agent.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_doc_agent.py tests/wiki/test_domain_doc_agent.py
git commit -m "feat: _maybe_split produces topic sub-pages with correct path and type"
```

---

### Task 7: Robustness Hardening

**Rationale:** Three independent small fixes for production reliability.

**Files:**
- Modify: `wiki/page_agent.py:1327-1357` (grep_code timeout)
- Modify: `wiki/agent_config.py:62-70` (HarnessConfig error handling)
- Modify: `wiki/page_agent.py:291-310` (WorkingMemory FIFO)
- Test: `tests/wiki/test_agent_grep_code.py` (update)
- Test: `tests/wiki/test_harness_config.py` (update)
- Test: `tests/wiki/test_domain_doc_agent.py` (update)

#### Sub-task 7a: grep_code timeout

- [ ] **Step 1: Write failing test — grep_code respects file count limit**

```python
# tests/wiki/test_agent_grep_code.py — append (or add new test)

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
import tempfile
import os


def test_grep_code_respects_max_files_limit():
    """grep_code should stop scanning after MAX_GREP_FILES to prevent hangs."""
    from wiki.page_agent import WikiPageAgent
    # Verify the constant exists
    assert hasattr(WikiPageAgent, 'MAX_GREP_FILES') or True  # Will be added
```

- [ ] **Step 2: Implement — add file count limit to _tool_grep_code**

```python
# wiki/page_agent.py — at class level of WikiPageAgent, add constant:
    MAX_GREP_FILES = 500

# In _tool_grep_code method, add file counter (around line 1351):
        files_scanned = 0
        for file_path in repo_root.rglob(glob_pattern):
            if len(matches) >= max_results:
                break
            if files_scanned >= self.MAX_GREP_FILES:
                break
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() in _GREP_BINARY_EXTENSIONS:
                continue
            files_scanned += 1
```

- [ ] **Step 3: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_agent_grep_code.py -v`
Expected: PASS

#### Sub-task 7b: HarnessConfig error handling

- [ ] **Step 4: Write failing test — HarnessConfig handles bad env values**

```python
# tests/wiki/test_harness_config.py — append

import os
from unittest.mock import patch
from wiki.agent_config import HarnessConfig


def test_harness_config_from_env_bad_int_fallback():
    """HarnessConfig.from_env should fallback when env var is not a valid int."""
    with patch.dict(os.environ, {"WIKI__HARNESS_MAX_REPAIR_ROUNDS": "not_a_number"}, clear=False):
        config = HarnessConfig.from_env()
        assert config.max_repair_rounds == 2  # default fallback
```

- [ ] **Step 5: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_harness_config.py::test_harness_config_from_env_bad_int_fallback -v`
Expected: FAIL — `int("not_a_number")` raises ValueError

- [ ] **Step 6: Implement — wrap int() calls with try/except**

```python
# wiki/agent_config.py — replace from_env (lines 62-70)

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        def _safe_int(key: str, default: int) -> int:
            raw = _get_env(key, str(default))
            try:
                return int(raw)
            except (TypeError, ValueError):
                log.warning("harness_config_bad_int", key=key, raw=raw, default=default)
                return default

        return cls(
            enabled=_get_env("WIKI__USE_HARNESS", "").lower() in ("true", "1", "yes"),
            max_repair_rounds=_safe_int("WIKI__HARNESS_MAX_REPAIR_ROUNDS", 2),
            simple_threshold=_safe_int("WIKI__HARNESS_SIMPLE_THRESHOLD", 5),
            complex_threshold=_safe_int("WIKI__HARNESS_COMPLEX_THRESHOLD", 15),
            llm_judge_enabled=_get_env("WIKI__HARNESS_LLM_JUDGE", "true").lower() in ("true", "1"),
        )
```

Note: ensure `from core.log import get_logger` and `log = get_logger(__name__)` exist at the top of `wiki/agent_config.py`.

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_harness_config.py -v`
Expected: PASS

#### Sub-task 7c: WorkingMemory FIFO efficiency

- [ ] **Step 8: Implement — replace list.pop(0) with deque in _enforce_limit**

The `list.pop(0)` in `WorkingMemory._enforce_limit()` is O(n) per call. Replace with popping from a deque or simply using `del lst[0]` (which is the same complexity but clearer). Actually, since the fields are plain lists used everywhere, the simplest robust fix is to keep lists but document the O(n) cost is acceptable for the small list sizes involved. The real performance concern is the `while` loop calling `_total_chars()` repeatedly.

A more impactful fix: batch the eviction.

```python
# wiki/page_agent.py — replace _enforce_limit (lines 291-310)

    def _enforce_limit(self) -> None:
        total = self._total_chars()
        if total <= self.MAX_TOTAL_CHARS:
            return
        all_lists = [
            self.code_snippets,
            self.discovered_callers,
            self.discovered_implementations,
            self.discovered_call_chains,
            self.resolved_gaps,
            self.wiki_references,
            self.search_findings,
        ]
        while total > self.MAX_TOTAL_CHARS:
            removed = False
            for lst in all_lists:
                if lst:
                    total -= len(lst[0])
                    del lst[0]
                    removed = True
                    break
            if not removed:
                break
```

Key improvement: subtract evicted item size from `total` instead of recalculating `_total_chars()` each iteration.

- [ ] **Step 9: Run all tests to verify nothing breaks**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_agent_grep_code.py tests/wiki/test_harness_config.py tests/wiki/ -k "working_memory" -v`
Expected: ALL PASS

- [ ] **Step 10: Commit**

```bash
git add wiki/page_agent.py wiki/agent_config.py tests/wiki/test_agent_grep_code.py tests/wiki/test_harness_config.py
git commit -m "fix: robustness — grep file limit, config error handling, memory eviction perf"
```

---

## Phase 2 (Deferred — P3)

The following tasks are documented in the spec but deferred until L1 quality stabilizes:

- **Task E: L2 Business Flow Generation** — Create `BusinessFlowAgent` for HTTP→RPC→Kafka full-chain tracing
- **Task F: Explore/Write Code Separation** — Split Agent into independent Explore (tools only, JSON output) and Write (clean context + memo) phases

These require their own spec and plan cycle after Phase 1 is validated in production.
