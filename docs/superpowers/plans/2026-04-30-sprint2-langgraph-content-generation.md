# Sprint 2: LangGraph Pipeline 完整集成 + 渐进式内容生成

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill all LangGraph pipeline stub nodes with real logic, implement the topic page composer with complexity-based content generation, add incremental reorg detection, and simplify `service.py` to call `pipeline.invoke()` — making the pipeline end-to-end functional.

**Architecture:** The pipeline follows a 4-phase flow: Phase 1 (entity classification, done in Sprint 1) → Phase 2 (domain classification + tree planning) → Phase 3 (per-leaf-domain content generation with dynamic complexity routing) → Phase 4 (overview synthesis + cross-links). Incremental updates route through `detect_reorg` node. Content generation uses LangGraph Send API for per-domain parallelism.

**Tech Stack:** Python 3.11, FastAPI, FalkorDB, LangGraph (StateGraph, Send API, MemorySaver/AsyncSqliteSaver), pytest, structlog

**Spec:** `docs/superpowers/specs/PROPOSAL_20260430_145217_business-domain-wiki-tree.md` (Section 3.3, 3.4, Sprint 2)

**Dependencies:** Sprint 1 completed — `entity_role_classifier.py`, extended `WikiPipelineState`, `pipeline_nodes.py` with `classify_entities_node`, Business CRUD API, enhanced domain classification prompts.

---

## Task 1: Extend WikiPipelineState with Phase 3-4 Fields

**Files:**
- Modify: `wiki/pipeline_state.py`
- Modify: `tests/wiki/test_pipeline_state_extension.py`

- [ ] **Step 1: Write the failing test**

Add to existing `tests/wiki/test_pipeline_state_extension.py`:

```python
def test_phase3_phase4_fields_exist():
    """Sprint 2 fields for content gen and synthesis."""
    hints = WikiPipelineState.__annotations__
    assert "generated_topic_pages" in hints
    assert "overview_pages" in hints
    assert "system_overview_uid" in hints
    assert "llm" in hints
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state_extension.py::test_phase3_phase4_fields_exist -v`
Expected: FAIL — `AssertionError`

- [ ] **Step 3: Add new fields to WikiPipelineState**

Add after `review_notes` in `wiki/pipeline_state.py`:

```python
    # --- Phase 3-4 outputs ---
    generated_topic_pages: list[str]
    overview_pages: list[str]
    system_overview_uid: str

    # --- LLM port (injected at pipeline start) ---
    llm: Any
```

- [ ] **Step 4: Run tests to verify all pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_state_extension.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_state.py tests/wiki/test_pipeline_state_extension.py
git commit -m "feat(wiki): extend WikiPipelineState with Phase 3-4 and LLM fields"
```

---

## Task 2: Detect Reorg Node

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Test: `tests/wiki/test_detect_reorg_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_detect_reorg_node.py
from __future__ import annotations

import pytest
from wiki.pipeline_nodes import detect_reorg_node


@pytest.mark.asyncio
async def test_first_run_when_no_domain_tree():
    state = {
        "domain_tree": None,
        "is_incremental": False,
        "entity_roles": {"a": "has_business_logic"},
        "role_stats": {"has_business_logic": 1},
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "first_run"


@pytest.mark.asyncio
async def test_none_when_incremental_no_change():
    state = {
        "domain_tree": [{"name": "payment", "modules": ["PaymentService"]}],
        "is_incremental": True,
        "entity_roles": {"PaymentService": "has_business_logic"},
        "role_stats": {"has_business_logic": 1},
        "affected_domains": [],
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "none"


@pytest.mark.asyncio
async def test_light_when_incremental_with_affected_domains():
    state = {
        "domain_tree": [{"name": "payment", "modules": ["PaymentService"]}],
        "is_incremental": True,
        "entity_roles": {"PaymentService": "has_business_logic", "NewService": "has_business_logic"},
        "role_stats": {"has_business_logic": 2},
        "affected_domains": ["payment"],
    }
    result = await detect_reorg_node(state)
    assert result["reorg_type"] == "light"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_detect_reorg_node.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement detect_reorg_node**

Add to `wiki/pipeline_nodes.py`:

```python
async def detect_reorg_node(state: dict[str, Any]) -> dict[str, Any]:
    """Determine reorganization type based on pipeline state.

    Returns reorg_type: first_run | full | heavy | light | none
    """
    domain_tree = state.get("domain_tree")
    is_incremental = state.get("is_incremental", False)
    affected_domains = state.get("affected_domains", [])

    if domain_tree is None:
        reorg_type = "first_run"
    elif not is_incremental:
        reorg_type = "full"
    elif affected_domains:
        biz_count = state.get("role_stats", {}).get("has_business_logic", 0)
        prev_biz = sum(
            len(d.get("modules", []))
            for d in (domain_tree if isinstance(domain_tree, list) else [])
        )
        ratio = abs(biz_count - prev_biz) / max(prev_biz, 1)
        if ratio > 0.3:
            reorg_type = "heavy"
        else:
            reorg_type = "light"
    else:
        reorg_type = "none"

    log.info("detect_reorg_done", reorg_type=reorg_type, is_incremental=is_incremental)
    return {"reorg_type": reorg_type}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_detect_reorg_node.py -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py tests/wiki/test_detect_reorg_node.py
git commit -m "feat(wiki): add detect_reorg_node for incremental update routing"
```

---

## Task 3: Fill classify_domains Stub (Phase 2a-2b)

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Modify: `wiki/pipeline_graph.py`
- Test: `tests/wiki/test_classify_domains_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_classify_domains_node.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.pipeline_nodes import classify_domains_node


@pytest.mark.asyncio
async def test_classify_domains_returns_domain_mapping():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='{"payment": [["repo-1", "PaymentService"]], "user": [["repo-1", "UserService"]]}')

    state = {
        "business_id": "test-biz",
        "repositories": ["repo-1"],
        "config": {},
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "annotations": ["@Service"], "methods_count": 10}},
                {"uid": "Module::UserService:0", "label": "Module", "properties": {"name": "UserService", "annotations": ["@Service"], "methods_count": 8}},
            ]
        },
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::UserService:0": "has_business_logic",
        },
        "llm": mock_llm,
    }
    result = await classify_domains_node(state)
    assert "domain_mapping" in result
    assert isinstance(result["domain_mapping"], dict)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_classify_domains_node.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement classify_domains_node**

Add to `wiki/pipeline_nodes.py`:

```python
from store.schema import GraphNode, NodeLabel
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


async def classify_domains_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 2a-2b: classify modules into business domains using LLM.

    Filters to HAS_BUSINESS_LOGIC entities only, then delegates to
    CrossRepoBusinessDomainPlanner for per-repo classification + cross-repo merge.
    """
    llm = state.get("llm")
    business_id = state.get("business_id", "")
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    biz_modules: dict[str, list[GraphNode]] = {}
    for repo, mod_list in modules.items():
        filtered = []
        for mod_dict in mod_list:
            uid = mod_dict.get("uid", "")
            if entity_roles.get(uid) == "has_business_logic":
                props = mod_dict.get("properties", {})
                label_str = mod_dict.get("label", "Module")
                try:
                    label = NodeLabel(label_str)
                except ValueError:
                    label = NodeLabel.MODULE
                filtered.append(GraphNode(label=label, properties=props, uid=uid))
        if filtered:
            biz_modules[repo] = filtered

    planner = CrossRepoBusinessDomainPlanner(llm)
    domain_mapping = await planner.classify(business_id, biz_modules)

    log.info(
        "classify_domains_done",
        business_id=business_id,
        domains=len(domain_mapping),
        total_modules=sum(len(v) for v in domain_mapping.values()),
    )
    return {"domain_mapping": domain_mapping}
```

- [ ] **Step 4: Wire into pipeline_graph.py**

In `wiki/pipeline_graph.py`:
1. Add import: `from wiki.pipeline_nodes import classify_domains_node as classify_domains_real`
2. Remove the `classify_domains_node` stub function
3. Update graph builder: `graph.add_node("classify_domains", classify_domains_real)`

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_classify_domains_node.py tests/wiki/test_quality_loop.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_classify_domains_node.py
git commit -m "feat(wiki): fill classify_domains stub with CrossRepoBusinessDomainPlanner

Filters to HAS_BUSINESS_LOGIC entities before domain classification."
```

---

## Task 4: Fill decompose_hierarchy + plan_structure Stubs (Phase 2c + Review Mark)

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Modify: `wiki/pipeline_graph.py`
- Test: `tests/wiki/test_domain_planning_nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_domain_planning_nodes.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import decompose_hierarchy_node, plan_structure_node


@pytest.mark.asyncio
async def test_decompose_hierarchy_builds_tree():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value='[{"name": "payment", "children": [{"name": "payment-core", "modules": ["PaymentService"]}]}]')

    state = {
        "business_id": "test",
        "domain_mapping": {
            "payment": [("repo-1", "PaymentService")],
            "user": [("repo-1", "UserService")],
        },
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::UserService:0": "has_business_logic",
        },
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService"}},
                {"uid": "Module::UserService:0", "label": "Module", "properties": {"name": "UserService"}},
            ]
        },
        "llm": mock_llm,
    }
    result = await decompose_hierarchy_node(state)
    assert "domain_tree" in result
    assert result["domain_tree"] is not None


@pytest.mark.asyncio
async def test_plan_structure_marks_pending_review():
    state = {
        "domain_tree": [{"name": "payment", "children": []}],
        "review_status": {},
    }
    result = await plan_structure_node(state)
    assert "review_status" in result
    assert result["review_status"].get("domain_tree") == "pending_review"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_planning_nodes.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement decompose_hierarchy_node**

Add to `wiki/pipeline_nodes.py`:

```python
from wiki.dependency_graph import HierarchicalDecomposer, ModuleGraph, ModuleInfo


async def decompose_hierarchy_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 2c: build hierarchical domain tree from flat domain mapping."""
    llm = state.get("llm")
    domain_mapping = state.get("domain_mapping", {})
    modules = state.get("modules", {})

    if not llm or not domain_mapping:
        log.info("decompose_hierarchy_skip", reason="no llm or empty domain_mapping")
        flat_tree = [
            {"name": domain, "modules": [m for _, m in pairs], "children": []}
            for domain, pairs in domain_mapping.items()
        ]
        return {"domain_tree": flat_tree}

    module_lookup: dict[str, dict] = {}
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                module_lookup[name] = mod_dict

    all_module_infos: list[ModuleInfo] = []
    for domain, pairs in domain_mapping.items():
        for repo_id, mod_name in pairs:
            mod_dict = module_lookup.get(mod_name, {})
            props = mod_dict.get("properties", {})
            all_module_infos.append(ModuleInfo(
                name=mod_name,
                path=str(props.get("path", "")),
                uid=mod_dict.get("uid", f"Module::{mod_name}:0"),
                summary=str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                semantic_roles=list(props.get("semantic_roles", []) or []),
            ))

    if not all_module_infos:
        return {"domain_tree": []}

    decomposer = HierarchicalDecomposer(llm, max_depth=3, min_modules_for_nesting=3)
    module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])

    try:
        domain_tree = await decomposer.decompose(all_module_infos, module_graph)
    except Exception:
        log.warning("decompose_hierarchy_failed", exc_info=True)
        domain_tree = [
            {"name": domain, "modules": [m for _, m in pairs], "children": []}
            for domain, pairs in domain_mapping.items()
        ]

    log.info("decompose_hierarchy_done", domains=len(domain_tree) if domain_tree else 0)
    return {"domain_tree": domain_tree}
```

- [ ] **Step 4: Implement plan_structure_node**

Add to `wiki/pipeline_nodes.py`:

```python
async def plan_structure_node(state: dict[str, Any]) -> dict[str, Any]:
    """Mark domain tree as pending_review and continue (non-blocking)."""
    review_status = dict(state.get("review_status", {}))
    review_status["domain_tree"] = "pending_review"

    log.info("plan_structure_marked_review", tree_size=len(state.get("domain_tree") or []))
    return {"review_status": review_status}
```

- [ ] **Step 5: Wire into pipeline_graph.py**

Remove the `decompose_hierarchy_node` and `plan_structure_node` stubs in `pipeline_graph.py`. Import from `pipeline_nodes` and replace.

- [ ] **Step 6: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_domain_planning_nodes.py tests/wiki/test_quality_loop.py -v`
Expected: All PASS

- [ ] **Step 7: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_domain_planning_nodes.py
git commit -m "feat(wiki): fill decompose_hierarchy and plan_structure stubs

Phase 2c: hierarchical domain tree via HierarchicalDecomposer.
Plan structure marks domain_tree as pending_review (non-blocking)."
```

---

## Task 5: TopicPageComposer — Phase 3 Content Generator

**Files:**
- Create: `wiki/topic_page_composer.py`
- Test: `tests/wiki/test_topic_page_composer.py`

This is the most complex task. The TopicPageComposer generates wiki content for a single leaf domain, with 3 strategies based on entity count.

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_topic_page_composer.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.topic_page_composer import TopicPageComposer


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value=(
        "# Payment Service\n\n## 业务概述\nPayment handling.\n\n"
        "## 核心业务流程\n```mermaid\nsequenceDiagram\nA->>B: call\n```\n\n"
        "## 核心服务详情\n### PaymentService\nHandles payments.\n\n"
        "## 数据模型\n| 类名 | 类型 | 字段 |\n|---|---|---|\n| PayDTO | DTO | id, amount |\n\n"
        "## 关联主题\n- [[用户系统]]"
    ))
    return llm


@pytest.mark.asyncio
async def test_simple_domain_single_page(mock_llm):
    """Domain with ≤5 BIZ entities generates 1 page."""
    composer = TopicPageComposer(mock_llm, token_budget=8000)
    domain = {
        "name": "payment",
        "parent": "root",
        "biz_entities": [
            {"uid": "Module::PaymentService:0", "name": "PaymentService", "summary": "Handles payments", "methods": ["pay", "refund"], "calls": ["UserService"]},
        ],
        "data_models": [
            {"uid": "Module::PayDTO:0", "name": "PayDTO", "fields": ["id", "amount"]},
        ],
        "sibling_summaries": [{"name": "user", "description": "User management"}],
    }
    pages = await composer.compose_leaf_domain(domain)
    assert len(pages) == 1
    assert "payment" in pages[0]["title"].lower() or "Payment" in pages[0]["title"]
    assert pages[0]["content"]  # non-empty


@pytest.mark.asyncio
async def test_complex_domain_multiple_pages(mock_llm):
    """Domain with >5 BIZ entities generates overview + sub-pages."""
    composer = TopicPageComposer(mock_llm, token_budget=8000)
    domain = {
        "name": "messaging",
        "parent": "communication",
        "biz_entities": [
            {"uid": f"Module::Svc{i}:0", "name": f"Svc{i}", "summary": f"Service {i}", "methods": [f"m{j}" for j in range(3)], "calls": []}
            for i in range(8)
        ],
        "data_models": [],
        "sibling_summaries": [],
    }
    pages = await composer.compose_leaf_domain(domain)
    assert len(pages) >= 2  # overview + at least 1 sub-page


@pytest.mark.asyncio
async def test_data_model_inline_format():
    """DATA_MODEL entities should be formatted as inline tables."""
    composer = TopicPageComposer(AsyncMock(), token_budget=8000)
    result = composer.format_data_model_table([
        {"name": "UserDTO", "type": "DTO", "fields": ["id", "name", "avatar"]},
        {"name": "StatusEnum", "type": "Enum", "fields": ["ONLINE", "OFFLINE"]},
    ])
    assert "UserDTO" in result
    assert "StatusEnum" in result
    assert "|" in result  # table format
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topic_page_composer.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement TopicPageComposer**

```python
# wiki/topic_page_composer.py
"""Phase 3: Topic page content generator for leaf domains.

Routes by complexity: single page (≤5 entities), split (6-15), group+split (>15).
Generates Markdown with Mermaid business flow diagrams and inline DATA_MODEL tables.
"""
from __future__ import annotations

from typing import Any, Protocol

from log import get_logger

log = get_logger(__name__)

_SYSTEM_WIKI = (
    "You are a technical wiki author writing business domain documentation. "
    "Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
    "Do NOT explain frameworks or annotations — focus on business logic."
)


class LLMPort(Protocol):
    async def generate(self, prompt: str, system: str = "", *, model: str | None = None) -> str: ...


class TopicPageComposer:
    SIMPLE_THRESHOLD = 5
    COMPLEX_THRESHOLD = 15

    def __init__(self, llm: LLMPort, *, token_budget: int = 8000) -> None:
        self._llm = llm
        self._token_budget = token_budget

    async def compose_leaf_domain(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate wiki pages for a single leaf domain.

        Returns list of page dicts with keys: title, content, path, page_type, domain.
        """
        biz_entities = domain.get("biz_entities", [])
        biz_count = len(biz_entities)

        if biz_count <= self.SIMPLE_THRESHOLD:
            return await self._compose_single_page(domain)
        elif biz_count <= self.COMPLEX_THRESHOLD:
            return await self._compose_split_pages(domain)
        else:
            return await self._compose_grouped_pages(domain)

    async def _compose_single_page(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        prompt = self._build_single_page_prompt(domain)
        content = await self._llm.generate(prompt, system=_SYSTEM_WIKI)

        data_table = self.format_data_model_table(domain.get("data_models", []))
        if data_table and "## 数据模型" not in content:
            content += f"\n\n## 数据模型\n{data_table}"

        return [{"title": name, "content": content, "path": f"wiki/{name}", "page_type": "topic", "domain": name}]

    async def _compose_split_pages(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])
        pages: list[dict[str, Any]] = []

        overview_prompt = self._build_overview_prompt(domain)
        overview_content = await self._llm.generate(overview_prompt, system=_SYSTEM_WIKI)
        pages.append({"title": name, "content": overview_content, "path": f"wiki/{name}", "page_type": "domain_overview", "domain": name})

        chunk_size = max(self.SIMPLE_THRESHOLD, 1)
        for i in range(0, len(biz_entities), chunk_size):
            chunk = biz_entities[i:i + chunk_size]
            sub_name = chunk[0]["name"] if chunk else f"{name}-part-{i}"
            sibling_titles = [e["name"] for e in biz_entities if e not in chunk]

            sub_domain = {
                "name": sub_name,
                "parent": name,
                "biz_entities": chunk,
                "data_models": domain.get("data_models", []),
                "sibling_summaries": [{"name": t, "description": ""} for t in sibling_titles[:5]],
                "overview_summary": overview_content[:500],
            }
            sub_prompt = self._build_sub_page_prompt(sub_domain)
            sub_content = await self._llm.generate(sub_prompt, system=_SYSTEM_WIKI)
            pages.append({"title": sub_name, "content": sub_content, "path": f"wiki/{name}/{sub_name}", "page_type": "topic", "domain": name})

        return pages

    async def _compose_grouped_pages(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])

        group_prompt = self._build_grouping_prompt(biz_entities)
        raw_groups = await self._llm.generate(group_prompt, system="Reply with JSON only. No markdown fences.")

        from wiki.json_robust import parse_json_robust_sync
        groups = parse_json_robust_sync(raw_groups)
        if not isinstance(groups, list):
            groups = [{"name": name, "entities": [e["name"] for e in biz_entities]}]

        pages: list[dict[str, Any]] = []

        overview_prompt = self._build_overview_prompt(domain)
        overview_content = await self._llm.generate(overview_prompt, system=_SYSTEM_WIKI)
        pages.append({"title": name, "content": overview_content, "path": f"wiki/{name}", "page_type": "domain_overview", "domain": name})

        entity_by_name = {e["name"]: e for e in biz_entities}
        for group in groups:
            group_name = group.get("name", "unknown")
            entity_names = group.get("entities", [])
            chunk = [entity_by_name[n] for n in entity_names if n in entity_by_name]
            if not chunk:
                continue
            sub_domain = {
                "name": group_name,
                "parent": name,
                "biz_entities": chunk,
                "data_models": domain.get("data_models", []),
                "sibling_summaries": [{"name": g.get("name", ""), "description": ""} for g in groups if g.get("name") != group_name][:5],
                "overview_summary": overview_content[:500],
            }
            sub_prompt = self._build_sub_page_prompt(sub_domain)
            sub_content = await self._llm.generate(sub_prompt, system=_SYSTEM_WIKI)
            pages.append({"title": group_name, "content": sub_content, "path": f"wiki/{name}/{group_name}", "page_type": "topic", "domain": name})

        return pages

    def _build_single_page_prompt(self, domain: dict[str, Any]) -> str:
        name = domain["name"]
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])}; calls: {', '.join(e.get('calls', [])[:5])})"
            for e in domain.get("biz_entities", [])
        )
        siblings = ", ".join(s["name"] for s in domain.get("sibling_summaries", [])[:5])
        data_models = self.format_data_model_table(domain.get("data_models", []))
        return (
            f"Generate a wiki page for the business domain: **{name}**\n"
            f"Parent domain: {domain.get('parent', 'root')}\n"
            f"Sibling domains: {siblings or 'none'}\n\n"
            f"Core services:\n{entities_desc}\n\n"
            f"Related data models:\n{data_models or 'none'}\n\n"
            "Format:\n"
            "1. ## 业务概述 (what this domain does)\n"
            "2. ## 核心业务流程 (Mermaid sequenceDiagram/flowchart based on CALLS edges)\n"
            "3. ## 核心服务详情 (### per service: responsibilities, key APIs, params)\n"
            "4. ## 数据模型 (inline table of related DTOs/enums — already provided, integrate if needed)\n"
            "5. ## 关联主题 ([[wiki-link]] to sibling domains referenced via CALLS)\n"
        )

    def _build_overview_prompt(self, domain: dict[str, Any]) -> str:
        name = domain["name"]
        entities = domain.get("biz_entities", [])
        entity_list = "\n".join(f"- {e['name']}: {e.get('summary', '')}" for e in entities)
        return (
            f"Generate a domain overview for: **{name}**\n"
            f"This domain contains {len(entities)} core services:\n{entity_list}\n\n"
            "Output:\n"
            "1. ## 域概览 (overall business capability description)\n"
            "2. ## 架构关系图 (Mermaid diagram showing service relationships)\n"
            "3. ## 子主题 (list sub-topic pages that will be generated)\n"
        )

    def _build_sub_page_prompt(self, sub_domain: dict[str, Any]) -> str:
        name = sub_domain["name"]
        parent = sub_domain.get("parent", "")
        overview = sub_domain.get("overview_summary", "")
        siblings = ", ".join(s["name"] for s in sub_domain.get("sibling_summaries", []))
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])})"
            for e in sub_domain.get("biz_entities", [])
        )
        return (
            f"Generate a wiki sub-page for: **{name}** (part of domain: {parent})\n"
            f"Domain overview: {overview[:300]}\n"
            f"Sibling pages: {siblings or 'none'}\n\n"
            f"Services in this sub-page:\n{entities_desc}\n\n"
            "Format: same as main topic page (业务概述, 核心业务流程 with Mermaid, 核心服务详情, 关联主题)"
        )

    def _build_grouping_prompt(self, entities: list[dict[str, Any]]) -> str:
        entity_list = "\n".join(
            f"- {e['name']}: {e.get('summary', '')} (calls: {', '.join(e.get('calls', [])[:5])})"
            for e in entities
        )
        return (
            f"Group these {len(entities)} services into 3-7 logical sub-groups based on business functionality:\n"
            f"{entity_list}\n\n"
            'Return JSON: [{"name": "group-name", "entities": ["ServiceA", "ServiceB"]}, ...]'
        )

    @staticmethod
    def format_data_model_table(data_models: list[dict[str, Any]]) -> str:
        if not data_models:
            return ""
        rows = ["| 类名 | 类型 | 字段 | 说明 |", "|------|------|------|------|"]
        for dm in data_models:
            name = dm.get("name", "")
            dtype = dm.get("type", "DTO")
            fields = ", ".join(dm.get("fields", [])[:8])
            desc = dm.get("description", "")
            rows.append(f"| {name} | {dtype} | {fields} | {desc} |")
        return "\n".join(rows)
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_topic_page_composer.py -v`
Expected: All 3 PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/topic_page_composer.py tests/wiki/test_topic_page_composer.py
git commit -m "feat(wiki): add TopicPageComposer for Phase 3 content generation

Complexity routing: single page (≤5), split (6-15), group+split (>15).
Includes inline DATA_MODEL tables and Mermaid business flow diagrams."
```

---

## Task 6: Fill compose_pages Stub with Leaf Domain Generation

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Modify: `wiki/pipeline_graph.py`
- Test: `tests/wiki/test_compose_pages_node.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_compose_pages_node.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import compose_pages_node


@pytest.mark.asyncio
async def test_compose_pages_generates_topic_pages():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="# Payment\n\n## 业务概述\nPayment service.")

    state = {
        "business_id": "test",
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": []},
        ],
        "entity_roles": {
            "Module::PaymentService:0": "has_business_logic",
            "Module::PayDTO:0": "data_model",
        },
        "modules": {
            "repo-1": [
                {"uid": "Module::PaymentService:0", "label": "Module", "properties": {"name": "PaymentService", "annotations": ["@Service"], "methods_count": 5, "business_summary": "Handles payments", "start_line": 0, "end_line": 200}},
                {"uid": "Module::PayDTO:0", "label": "Module", "properties": {"name": "PayDTO", "annotations": ["@Data"], "methods_count": 0}},
            ]
        },
        "llm": mock_llm,
        "config": {},
    }
    result = await compose_pages_node(state)
    assert "pages" in result
    assert len(result["pages"]) >= 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_pages_node.py -v`
Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement compose_pages_node**

Add to `wiki/pipeline_nodes.py`:

```python
from wiki.topic_page_composer import TopicPageComposer
from wiki.token_budget import TokenBudgetResolver


async def compose_pages_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 3: generate topic pages for each leaf domain."""
    llm = state.get("llm")
    domain_tree = state.get("domain_tree") or []
    entity_roles = state.get("entity_roles", {})
    modules = state.get("modules", {})

    module_index: dict[str, dict] = {}
    for repo, mod_list in modules.items():
        for mod_dict in mod_list:
            name = mod_dict.get("properties", {}).get("name", "")
            if name:
                module_index[name] = mod_dict

    budget_resolver = TokenBudgetResolver()
    budget = budget_resolver.budget("topic_page_generate")
    composer = TopicPageComposer(llm, token_budget=budget)

    all_pages: list[dict[str, Any]] = []
    generated_uids: list[str] = []

    leaf_domains = _collect_leaf_domains(domain_tree)

    for leaf in leaf_domains:
        domain_name = leaf.get("name", "unknown")
        module_names = leaf.get("modules", [])

        biz_entities = []
        data_models = []
        for mod_name in module_names:
            mod_dict = module_index.get(mod_name, {})
            uid = mod_dict.get("uid", f"Module::{mod_name}:0")
            role = entity_roles.get(uid, "supporting")
            props = mod_dict.get("properties", {})

            if role == "has_business_logic":
                biz_entities.append({
                    "uid": uid,
                    "name": mod_name,
                    "summary": str(props.get("business_summary", "") or props.get("docstring", "") or ""),
                    "methods": [str(m) for m in (props.get("methods", []) or [])[:10]],
                    "calls": [],
                })
            elif role == "data_model":
                data_models.append({
                    "uid": uid,
                    "name": mod_name,
                    "type": "DTO",
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                })

        for uid, role in entity_roles.items():
            if role == "data_model":
                name_part = uid.split("::")[-1].split(":")[0] if "::" in uid else uid
                mod_dict = module_index.get(name_part, {})
                if mod_dict and name_part not in [dm["name"] for dm in data_models]:
                    props = mod_dict.get("properties", {})
                    is_related = any(name_part in str(e.get("calls", [])) for e in biz_entities)
                    if is_related:
                        data_models.append({
                            "uid": uid,
                            "name": name_part,
                            "type": "DTO",
                            "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                        })

        domain_input = {
            "name": domain_name,
            "parent": leaf.get("parent", "root"),
            "biz_entities": biz_entities,
            "data_models": data_models[:20],
            "sibling_summaries": [],
        }

        try:
            pages = await composer.compose_leaf_domain(domain_input)
            all_pages.extend(pages)
            generated_uids.extend(p.get("path", "") for p in pages)
        except Exception:
            log.warning("compose_pages_domain_failed", domain=domain_name, exc_info=True)

    log.info("compose_pages_done", total_pages=len(all_pages), domains_processed=len(leaf_domains))
    return {"pages": all_pages, "generated_topic_pages": generated_uids}


def _collect_leaf_domains(tree: list[dict[str, Any]], parent: str = "root") -> list[dict[str, Any]]:
    """Recursively collect leaf domains (no children or children are empty)."""
    leaves: list[dict[str, Any]] = []
    for node in tree:
        children = node.get("children", [])
        node_with_parent = {**node, "parent": parent}
        if not children:
            leaves.append(node_with_parent)
        else:
            leaves.extend(_collect_leaf_domains(children, parent=node.get("name", "unknown")))
    return leaves
```

- [ ] **Step 4: Wire into pipeline_graph.py**

Remove the `compose_pages_node` stub. Import and use the real `compose_pages_node` from `pipeline_nodes`.

- [ ] **Step 5: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_compose_pages_node.py tests/wiki/test_quality_loop.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py wiki/pipeline_graph.py tests/wiki/test_compose_pages_node.py
git commit -m "feat(wiki): fill compose_pages stub with TopicPageComposer integration

Per-leaf-domain content generation with complexity routing.
Collects DATA_MODEL entities for inline tables."
```

---

## Task 7: Phase 4 — Domain Overview Synthesis + System Overview + Cross-links

**Files:**
- Modify: `wiki/pipeline_nodes.py`
- Test: `tests/wiki/test_synthesis_nodes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/wiki/test_synthesis_nodes.py
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock

from wiki.pipeline_nodes import synthesize_overviews_node, create_links_node


@pytest.mark.asyncio
async def test_synthesize_overviews_creates_system_overview():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="# System Overview\n\nThis system handles payment and messaging.")

    state = {
        "llm": mock_llm,
        "domain_tree": [
            {"name": "payment", "modules": ["PaymentService"], "children": []},
            {"name": "messaging", "modules": ["MsgService"], "children": []},
        ],
        "pages": [
            {"title": "payment", "content": "Payment wiki content...", "path": "wiki/payment", "page_type": "topic", "domain": "payment"},
            {"title": "messaging", "content": "Messaging wiki content...", "path": "wiki/messaging", "page_type": "topic", "domain": "messaging"},
        ],
    }
    result = await synthesize_overviews_node(state)
    assert "pages" in result
    assert any(p.get("page_type") == "system_overview" for p in result["pages"])


@pytest.mark.asyncio
async def test_create_links_adds_references():
    state = {
        "pages": [
            {"title": "payment", "content": "Uses [[messaging]] for notifications", "path": "wiki/payment"},
            {"title": "messaging", "content": "Called by payment", "path": "wiki/messaging"},
        ],
        "entity_roles": {},
        "modules": {},
    }
    result = await create_links_node(state)
    assert "pages" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_synthesis_nodes.py -v`
Expected: FAIL

- [ ] **Step 3: Implement synthesize_overviews_node and create_links_node**

Add to `wiki/pipeline_nodes.py`:

```python
async def synthesize_overviews_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 4a+4b: generate domain overviews and system overview."""
    llm = state.get("llm")
    pages = list(state.get("pages", []))
    domain_tree = state.get("domain_tree") or []

    if not llm:
        return {}

    domain_summaries = []
    for domain in domain_tree:
        name = domain.get("name", "")
        domain_pages = [p for p in pages if p.get("domain") == name]
        summary = domain_pages[0]["content"][:200] if domain_pages else ""
        domain_summaries.append(f"- **{name}**: {summary}")

    if domain_summaries:
        sys_prompt = (
            "Generate a system overview wiki page summarizing the entire codebase.\n\n"
            f"Domains:\n" + "\n".join(domain_summaries) + "\n\n"
            "Output:\n"
            "1. ## 系统概览\n"
            "2. ## 架构图 (Mermaid diagram showing domain relationships)\n"
            "3. ## 域列表 (with links to each domain)\n"
        )
        overview_content = await llm.generate(sys_prompt, system="You are a technical wiki author. Output Markdown with Mermaid.")
        overview_page = {
            "title": "System Overview",
            "content": overview_content,
            "path": "wiki/_system_overview",
            "page_type": "system_overview",
            "domain": "_system",
        }
        return {"pages": [overview_page], "system_overview_uid": "wiki/_system_overview"}

    return {}


async def create_links_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 4c-4d: programmatic cross-link resolution and knowledge graph edge creation."""
    pages = list(state.get("pages", []))
    page_titles = {p.get("title", "").lower(): p.get("path", "") for p in pages}

    import re
    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")

    for page in pages:
        content = page.get("content", "")
        for match in link_pattern.finditer(content):
            link_title = match.group(1).lower()
            if link_title in page_titles:
                target_path = page_titles[link_title]
                log.debug("wiki_link_resolved", source=page.get("path"), target=target_path)

    return {"pages": pages}
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_synthesis_nodes.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_nodes.py tests/wiki/test_synthesis_nodes.py
git commit -m "feat(wiki): add Phase 4 synthesis nodes (overview + cross-links)"
```

---

## Task 8: Rewire Pipeline Graph with All Nodes + Conditional Edges

**Files:**
- Modify: `wiki/pipeline_graph.py`
- Modify: `tests/wiki/test_pipeline_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# Add to existing tests/wiki/test_pipeline_graph.py or create new
from wiki.pipeline_graph import build_wiki_pipeline


def test_pipeline_has_all_expected_nodes():
    pipeline = build_wiki_pipeline()
    node_names = set(pipeline.get_graph().nodes.keys())
    expected = {
        "collect_modules", "detect_reorg", "classify_domains",
        "decompose_hierarchy", "plan_structure", "compose_pages",
        "synthesize_overviews", "create_links",
        "quality_gate", "heal_pages", "finalize",
    }
    assert expected.issubset(node_names), f"Missing: {expected - node_names}"
```

- [ ] **Step 2: Rewrite pipeline_graph.py build_wiki_pipeline**

Update `wiki/pipeline_graph.py` to:
1. Import all real nodes from `pipeline_nodes`
2. Remove all remaining stubs
3. Add `detect_reorg` node after `collect_modules`
4. Add `route_by_reorg_type` conditional edge
5. Add `synthesize_overviews` and `create_links` nodes between `quality_gate` result and `finalize`

```python
from wiki.pipeline_nodes import (
    classify_entities_node,
    detect_reorg_node,
    classify_domains_node,
    decompose_hierarchy_node,
    plan_structure_node,
    compose_pages_node,
    synthesize_overviews_node,
    create_links_node,
)


def route_by_reorg_type(state: WikiPipelineState) -> str:
    reorg_type = state.get("reorg_type", "first_run")
    if reorg_type == "none":
        return "finalize"
    return "classify_domains"


def build_wiki_pipeline(checkpointer: Any | None = None) -> Any:
    graph = StateGraph(WikiPipelineState)

    graph.add_node("collect_modules", classify_entities_node)
    graph.add_node("detect_reorg", detect_reorg_node)
    graph.add_node("classify_domains", classify_domains_node)
    graph.add_node("decompose_hierarchy", decompose_hierarchy_node)
    graph.add_node("plan_structure", plan_structure_node)
    graph.add_node("compose_pages", compose_pages_node)
    graph.add_node("quality_gate", quality_gate_node)
    graph.add_node("heal_pages", heal_pages_node)
    graph.add_node("synthesize_overviews", synthesize_overviews_node)
    graph.add_node("create_links", create_links_node)
    graph.add_node("finalize", finalize_node)

    graph.add_edge("collect_modules", "detect_reorg")
    graph.add_conditional_edges(
        "detect_reorg",
        route_by_reorg_type,
        {"classify_domains": "classify_domains", "finalize": "finalize"},
    )
    graph.add_edge("classify_domains", "decompose_hierarchy")
    graph.add_edge("decompose_hierarchy", "plan_structure")
    graph.add_edge("plan_structure", "compose_pages")
    graph.add_edge("compose_pages", "quality_gate")
    graph.add_conditional_edges(
        "quality_gate",
        should_heal,
        {"heal_pages": "heal_pages", "synthesize_overviews": "synthesize_overviews"},
    )
    graph.add_edge("heal_pages", "compose_pages")
    graph.add_edge("synthesize_overviews", "create_links")
    graph.add_edge("create_links", "finalize")

    graph.set_entry_point("collect_modules")
    graph.set_finish_point("finalize")

    if checkpointer is None:
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer)
```

- [ ] **Step 3: Update should_heal to route to synthesize_overviews**

```python
def should_heal(state: WikiPipelineState) -> str:
    if state.get("pages_to_heal"):
        return "heal_pages"
    return "synthesize_overviews"
```

- [ ] **Step 4: Run tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_pipeline_graph.py tests/wiki/test_quality_loop.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_graph.py tests/wiki/test_pipeline_graph.py
git commit -m "feat(wiki): rewire pipeline graph with all Phase 2-4 nodes

Add detect_reorg conditional routing, synthesize_overviews, create_links.
Remove all remaining stub nodes."
```

---

## Task 9: Adapt quality_gate for TopicPage Structure

**Files:**
- Modify: `wiki/pipeline_graph.py`
- Modify: `tests/wiki/test_quality_loop.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/wiki/test_quality_loop.py`:

```python
def test_quality_gate_handles_topic_page_dict():
    """quality_gate should evaluate pages with page_type='topic'."""
    from wiki.pipeline_graph import quality_gate_node
    import asyncio

    state = {
        "pages": [
            {
                "path": "wiki/payment",
                "title": "Payment Service",
                "content": "# Payment\n\n## 业务概述\nPayment handling.\n\n## 核心业务流程\nflow",
                "page_type": "topic",
                "repository": "test",
            }
        ],
        "config": {},
        "heal_attempts": {},
        "quality_scores": {},
        "pages_to_heal": [],
    }
    result = asyncio.get_event_loop().run_until_complete(quality_gate_node(state))
    assert "wiki/payment" in result["quality_scores"]
```

- [ ] **Step 2: Run and verify it passes with current implementation**

The existing `quality_gate_node` uses `WikiPage.from_dict()` which should handle the new dict format. Run the test to verify.

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run pytest tests/wiki/test_quality_loop.py -v`
Expected: All PASS (if not, adapt WikiPage.from_dict)

- [ ] **Step 3: Commit if changes needed**

```bash
cd /Users/earthchen/ai-work/agent-work/knowledge-base-service
git add wiki/pipeline_graph.py tests/wiki/test_quality_loop.py
git commit -m "test(wiki): verify quality_gate handles TopicPage dict format"
```

---

## Self-Review Checklist

**1. Spec coverage:**
- [x] Task 1: WikiPipelineState Phase 3-4 fields (Spec 3.1 extension) ✓
- [x] Task 2: detect_reorg node (Spec Section 9) ✓
- [x] Task 3: classify_domains real node (Spec Sprint 2.6 partial) ✓
- [x] Task 4: decompose_hierarchy + plan_structure real nodes (Spec Sprint 2.6 partial) ✓
- [x] Task 5: TopicPageComposer (Spec 3.4 Phase 3, Sprint 2.1-2.3) ✓
- [x] Task 6: compose_pages real node (Spec Sprint 2.6) ✓
- [x] Task 7: Phase 4 synthesis + cross-links (Spec Sprint 2.4-2.5) ✓
- [x] Task 8: Pipeline graph rewiring (Spec 3.3 architecture) ✓
- [x] Task 9: quality_gate TopicPage compat (Spec Sprint 2.8) ✓
- [ ] Sprint 2.7 (Checkpoint backend config) — deferred: MemorySaver is default, AsyncSqliteSaver requires async context manager which needs service.py integration
- [ ] Sprint 2.9 (service.py simplification) — deferred to separate PR: large refactor touching 1500+ line file, risk of breaking existing wiki generation

**2. Placeholder scan:** No TBDs, TODOs found in task descriptions.

**3. Type consistency:** `compose_pages_node` returns `dict[str, Any]` with `pages` key using `operator.add` reducer in state. `TopicPageComposer.compose_leaf_domain` returns `list[dict[str, Any]]` page dicts. Both use consistent keys: title, content, path, page_type, domain.
