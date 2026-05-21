# Wiki 树形目录结构增强 — TDD 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable parent-domain LLM overviews, agent-directed topic splitting, and NavigationContext population for the wiki generation pipeline.

**Architecture:** Activate existing `summarize_leaves_node` + `compose_parent_pages_node` in LangGraph pipeline for parent domains; add `plan_topics()` LLM call between explore and write phases in `DomainDocAgent` for semantic topic splitting; populate `NavigationContext` fields in `create_links_node`.

**Tech Stack:** Python 3.12+, LangGraph, pytest + pytest-asyncio, AsyncMock

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `wiki/pipeline_graph.py` | LangGraph StateGraph definition | Modify: add 2 nodes + adjust edges |
| `wiki/pipeline_nodes.py` | Re-export hub | Verify: already exports needed symbols |
| `wiki/nodes/aggregate.py` | Parent page synthesis nodes | Modify: fix path convention, language param, cross-domain stats |
| `wiki/prompts.py` | System prompts | Modify: improve SYSTEM_WIKI_PARENT_OVERVIEW |
| `wiki/agent_prompts.py` | Agent system prompts | Modify: add SYSTEM_TOPIC_PLANNER prompt |
| `wiki/domain_doc_agent.py` | DomainDocAgent + _maybe_split | Modify: add `_plan_topics()`, `_write_with_outline()`, enhance `_maybe_split()` |
| `wiki/page_agent.py` | WorkingMemory dataclass | Modify: add `topic_outline` field |
| `wiki/nodes/links.py` | Wikilink resolution | Modify: add NavigationContext population |
| `tests/wiki/test_pipeline_graph_v2.py` | Pipeline node tests | Modify: update node assertions |
| `tests/wiki/test_compose_parents.py` | Parent compose tests | Modify: update path assertions |
| `tests/wiki/test_plan_topics.py` | Topic planning tests | Create |
| `tests/wiki/test_navigation_context.py` | Navigation population tests | Create |

---

## Phase 1: 管线节点激活 — 父域 Overview 生成

### Task 1: Pipeline Graph — 接入 summarize_leaves + compose_parent_pages 节点

**Files:**
- Modify: `wiki/pipeline_graph.py:20-32` (imports), `wiki/pipeline_graph.py:41-56` (_NODE_PHASE_MAP), `wiki/pipeline_graph.py:328-333` (graph edges)
- Test: `tests/wiki/test_pipeline_graph_v2.py`

- [ ] **Step 1: Write the failing test — pipeline has new nodes**

```python
# tests/wiki/test_pipeline_graph_v2.py — update existing test
def test_pipeline_has_new_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "graph_decompose" in node_names
    assert "assign_canonical_keys" in node_names
    assert "generate_titles" in node_names
    assert "compose_domain_agents" in node_names
    assert "summarize_leaves" in node_names
    assert "compose_parent_pages" in node_names


def test_pipeline_removed_old_nodes():
    pipeline = build_wiki_pipeline(checkpointer=False)
    node_names = set(pipeline.nodes.keys())
    assert "classify_domains" in node_names
    assert "decompose_hierarchy" not in node_names
    assert "plan_topic_structure" not in node_names
    assert "compose_leaf_pages" not in node_names
    assert "synthesize_overviews" not in node_names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_pipeline_graph_v2.py -v`
Expected: FAIL — `"summarize_leaves" in node_names` fails

- [ ] **Step 3: Add imports and _NODE_PHASE_MAP entries in pipeline_graph.py**

In `wiki/pipeline_graph.py`, add imports:

```python
from wiki.pipeline_nodes import (
    assign_canonical_keys_node,
    classify_entities_node,
    compose_domain_agents_node,
    compose_leaf_modules_node,
    compose_parent_pages_node,   # NEW
    create_links_node,
    detect_reorg_node,
    generate_titles_node,
    graph_decompose_node,
    heal_pages_node,
    persist_classification_node,
    set_review_status_node,
    summarize_leaves_node,       # NEW
)
```

Add to `_NODE_PHASE_MAP`:

```python
    "compose_domain_agents": ("compose_domain_agents", 0.30),
    "summarize_leaves": ("summarize_leaves", 0.55),          # NEW
    "compose_parent_pages": ("compose_parent_pages", 0.60),  # NEW
    "quality_gate": ("quality_gate", 0.70),
```

- [ ] **Step 4: Add nodes and edges in build_wiki_pipeline()**

Replace the edge `compose_domain_agents → quality_gate` with:

```python
    graph.add_node(
        "summarize_leaves",
        _with_progress("summarize_leaves", summarize_leaves_node),
    )
    graph.add_node(
        "compose_parent_pages",
        _with_progress("compose_parent_pages", compose_parent_pages_node),
    )
    graph.add_edge("compose_domain_agents", "summarize_leaves")
    graph.add_edge("summarize_leaves", "compose_parent_pages")
    graph.add_edge("compose_parent_pages", "quality_gate")
```

Remove the old edge:
```python
    # DELETE: graph.add_edge("compose_domain_agents", "quality_gate")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_pipeline_graph_v2.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/pipeline_graph.py tests/wiki/test_pipeline_graph_v2.py
git commit -m "feat(pipeline): wire summarize_leaves + compose_parent_pages nodes"
```

---

### Task 2: compose_parent_pages_node 路径约定修复

**Files:**
- Modify: `wiki/nodes/aggregate.py:206-224` (path + metadata)
- Test: `tests/wiki/test_compose_parents.py`

- [ ] **Step 1: Write the failing test — parent pages use /__domains__/ path**

```python
# tests/wiki/test_compose_parents.py — add new test
@pytest.mark.asyncio
async def test_compose_parent_pages_uses_domain_path_convention():
    """Parent overview pages must use /__domains__/{slug}/_overview path."""
    llm = AsyncMock()
    llm.complete_json = AsyncMock(return_value={
        "title": "家族核心运营",
        "content": "## 业务概述\n家族系统...\n## 子域架构\n...",
        "executive_summary": "家族核心运营总览",
        "page_type": "domain_overview",
    })
    state = {
        "domain_tree": [
            {
                "name": "family-core-operations",
                "display_name": "家族核心运营",
                "modules": [],
                "children": [
                    {"name": "family-interaction", "modules": ["FamilyService"], "children": []},
                    {"name": "family-task", "modules": ["TaskService"], "children": []},
                ],
            },
        ],
        "leaf_summaries": {
            "family-interaction": {"summary_text": "家族互动", "module_count": 1},
            "family-task": {"summary_text": "家族任务", "module_count": 1},
        },
        "modules": {},
        "entity_roles": {},
    }
    config = {"configurable": {"llm": llm}}
    result = await compose_parent_pages_node(state, config)
    pages = result.get("pages", [])
    assert len(pages) == 1
    assert pages[0]["path"] == "/__domains__/family-core-operations/_overview"
    assert pages[0].get("business_domain") == "family-core-operations"
    assert pages[0]["title"] == "家族核心运营"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_compose_parents.py::test_compose_parent_pages_uses_domain_path_convention -v`
Expected: FAIL — path is `wiki/family-core-operations` not `/__domains__/...`

- [ ] **Step 3: Fix path convention in aggregate.py**

In `wiki/nodes/aggregate.py`, modify `compose_parent_pages_node` (around line 214-224):

```python
            try:
                if not isinstance(parsed, dict):
                    log.warning("compose_parent_pages_bad_json", domain=parent_name)
                    continue
                from wiki.path_conventions import domain_overview_path

                title = parsed.get("title") or parent_domain.get("display_name") or parent_name
                content = cleanup_context_gaps(parsed.get("content", ""))
                exec_summary = parsed.get("executive_summary", "")
                page_type_val = parsed.get("page_type") or "domain_overview"
                page_type = str(page_type_val)
                page_dict: dict[str, Any] = {
                    "path": domain_overview_path(parent_name),
                    "title": title,
                    "content": content,
                    "page_type": page_type,
                    "domain": parent_name,
                    "business_domain": parent_name,
                    "metadata": {"executive_summary": exec_summary},
                }
                all_parent_pages.append(page_dict)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_compose_parents.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/nodes/aggregate.py tests/wiki/test_compose_parents.py
git commit -m "fix(aggregate): parent pages use /__domains__/ path convention"
```

---

### Task 3: compose_parent_pages_node Prompt 改进

**Files:**
- Modify: `wiki/prompts.py:30-38` (SYSTEM_WIKI_PARENT_OVERVIEW)
- Modify: `wiki/nodes/aggregate.py:153-168` (user prompt construction)

- [ ] **Step 1: Update SYSTEM_WIKI_PARENT_OVERVIEW prompt**

In `wiki/prompts.py`, replace `SYSTEM_WIKI_PARENT_OVERVIEW`:

```python
SYSTEM_WIKI_PARENT_OVERVIEW = (
    "You are a senior technical writer creating a domain overview page. "
    "Your role is to SYNTHESIZE sub-domain information into a coherent narrative "
    "that explains how these sub-domains form a complete business capability.\n\n"
    "Output requirements:\n"
    "1. Title: Use the domain's display name\n"
    "2. Structure your content with these sections:\n"
    "   - ## 业务概述: Domain's purpose and position in the system (2-3 paragraphs)\n"
    "   - ## 子域架构: How sub-domains relate, with a Mermaid flowchart\n"
    "   - ## 数据流: Key data flows between sub-domains (Mermaid sequence diagram)\n"
    "   - ## 核心接口: Key interfaces referenced from code\n"
    "3. Do NOT just list sub-domains; explain the STORY of how they work together\n"
    "4. Include at least one Mermaid diagram showing sub-domain interactions\n"
    "5. Output valid JSON only."
)
```

- [ ] **Step 2: Update user prompt in compose_parent_pages_node to include cross-domain call stats**

In `wiki/nodes/aggregate.py`, modify the prompt construction (around line 153-168):

```python
                # Collect cross-domain call statistics (if available from state)
                domain_mapping = state.get("domain_mapping", {})
                cross_domain_stats = ""
                if domain_mapping and len(child_names) > 1:
                    stats_lines = []
                    for cn in child_names:
                        targets = [other for other in child_names if other != cn]
                        if targets:
                            stats_lines.append(f"- {cn} → {', '.join(targets[:3])}")
                    if stats_lines:
                        cross_domain_stats = (
                            "\n## Cross-Domain Relationships\n"
                            + "\n".join(stats_lines)
                        )

                prompt = (
                    f'Create a domain overview page for "{parent_domain.get("display_name") or parent_name}".\n\n'
                    "## Sub-domain Summaries\n"
                    f"{child_summaries_text}\n\n"
                    "## Key Code Interfaces\n"
                    f"{snippet_text}\n"
                    f"{cross_domain_stats}\n\n"
                    'Return ONLY valid JSON (no markdown fences) with keys: "title", '
                    '"content", "executive_summary", "page_type".\n'
                    "executive_summary should be 150-300 chars capturing the domain's core purpose."
                )
```

- [ ] **Step 3: Run existing tests to verify no regressions**

Run: `uv run pytest tests/wiki/test_compose_parents.py tests/wiki/test_summarize_leaves.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add wiki/prompts.py wiki/nodes/aggregate.py
git commit -m "improve(prompts): enhance parent overview prompt with structure guidance"
```

---

## Phase 2: Agent Topic 规划

### Task 4: WorkingMemory — 增加 topic_outline 字段

**Files:**
- Modify: `wiki/page_agent.py:202-213` (WorkingMemory dataclass)
- Test: `tests/wiki/test_plan_topics.py` (create)

- [ ] **Step 1: Write the failing test — WorkingMemory has topic_outline field**

```python
# tests/wiki/test_plan_topics.py — create new file
from __future__ import annotations

import pytest
from dataclasses import dataclass, field

from wiki.page_agent import WorkingMemory


def test_working_memory_has_topic_outline():
    wm = WorkingMemory()
    assert wm.topic_outline is None


def test_working_memory_topic_outline_assignment():
    from wiki.domain_doc_agent import TopicPlan, DomainTopicOutline

    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="任务系统", modules=["TaskService", "RewardHandler"], description="任务管理"),
            TopicPlan(title="成员管理", modules=["MemberService"], description="成员管理"),
        ],
    )
    wm = WorkingMemory()
    wm.topic_outline = outline
    assert wm.topic_outline.should_split is True
    assert len(wm.topic_outline.topics) == 2
    assert wm.topic_outline.topics[0].title == "任务系统"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_plan_topics.py::test_working_memory_has_topic_outline -v`
Expected: FAIL — `WorkingMemory` has no `topic_outline` attribute

- [ ] **Step 3: Add topic_outline field to WorkingMemory**

In `wiki/page_agent.py`, add to `WorkingMemory` dataclass (after line 212):

```python
@dataclass
class WorkingMemory:
    discovered_call_chains: list[str] = field(default_factory=list)
    discovered_implementations: list[str] = field(default_factory=list)
    discovered_callers: list[str] = field(default_factory=list)
    code_snippets: list[str] = field(default_factory=list)
    resolved_gaps: list[str] = field(default_factory=list)
    wiki_references: list[str] = field(default_factory=list)
    search_findings: list[str] = field(default_factory=list)
    discovered_entity_uids: set[str] = field(default_factory=set)
    _tool_contributed_chars: int = 0
    relevant_modules: set[str] = field(default_factory=set)
    topic_outline: Any | None = None  # DomainTopicOutline when set

    MAX_TOTAL_CHARS = 200_000
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/wiki/test_plan_topics.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_plan_topics.py
git commit -m "feat(agent): add topic_outline field to WorkingMemory"
```

---

### Task 5: TopicPlan / DomainTopicOutline 数据类 + plan_topics() 方法

**Files:**
- Modify: `wiki/domain_doc_agent.py` (add dataclasses + _plan_topics method)
- Modify: `wiki/agent_prompts.py` (add SYSTEM_TOPIC_PLANNER)
- Test: `tests/wiki/test_plan_topics.py`

- [ ] **Step 1: Write the failing tests for _plan_topics()**

```python
# tests/wiki/test_plan_topics.py — append to existing file
from unittest.mock import AsyncMock, MagicMock

from wiki.domain_doc_agent import (
    DomainDocAgent,
    DomainTopicOutline,
    TopicPlan,
    _parse_topic_outline,
)


def test_parse_topic_outline_valid_json():
    raw = '{"should_split": true, "topics": [{"title": "A", "modules": ["M1"], "description": "d1"}]}'
    outline = _parse_topic_outline(raw)
    assert outline is not None
    assert outline.should_split is True
    assert len(outline.topics) == 1
    assert outline.topics[0].title == "A"
    assert outline.topics[0].modules == ["M1"]


def test_parse_topic_outline_invalid_json():
    outline = _parse_topic_outline("not json at all")
    assert outline is None


def test_parse_topic_outline_missing_fields():
    raw = '{"should_split": true}'
    outline = _parse_topic_outline(raw)
    assert outline is None


def test_parse_topic_outline_small_domain_skip():
    """Domains with ≤5 modules should not split."""
    raw = '{"should_split": false, "topics": [{"title": "All", "modules": ["A","B","C"], "description": "all"}]}'
    outline = _parse_topic_outline(raw)
    assert outline is not None
    assert outline.should_split is False


@pytest.mark.asyncio
async def test_plan_topics_small_domain_skips_llm():
    """Domains with ≤5 modules skip the LLM call entirely."""
    llm = AsyncMock()
    agent = DomainDocAgent(
        domain_name="small-domain",
        llm=llm,
        graph_store=MagicMock(),
    )
    module_names = ["ModA", "ModB", "ModC"]
    memory = WorkingMemory()
    outline = await agent._plan_topics(module_names, memory)
    assert outline.should_split is False
    assert len(outline.topics) == 1
    assert set(outline.topics[0].modules) == {"ModA", "ModB", "ModC"}
    llm.complete_json.assert_not_called()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_plan_topics.py -v`
Expected: FAIL — `_parse_topic_outline` and `_plan_topics` don't exist

- [ ] **Step 3: Add TopicPlan/DomainTopicOutline dataclasses and _parse_topic_outline**

In `wiki/domain_doc_agent.py`, add after the existing imports (around line 30):

```python
@dataclass
class TopicPlan:
    title: str
    modules: list[str]
    description: str = ""


@dataclass
class DomainTopicOutline:
    should_split: bool
    topics: list[TopicPlan]


def _parse_topic_outline(raw: str) -> DomainTopicOutline | None:
    """Parse LLM output into a DomainTopicOutline. Returns None on failure."""
    from wiki.json_robust import parse_json_robust_sync

    parsed = parse_json_robust_sync(raw)
    if not isinstance(parsed, dict):
        return None
    should_split = parsed.get("should_split")
    topics_raw = parsed.get("topics")
    if should_split is None or not isinstance(topics_raw, list):
        return None
    topics = []
    for t in topics_raw:
        if not isinstance(t, dict):
            continue
        title = t.get("title", "")
        modules = t.get("modules", [])
        if not title or not isinstance(modules, list):
            continue
        topics.append(TopicPlan(
            title=str(title),
            modules=[str(m) for m in modules],
            description=str(t.get("description", "")),
        ))
    if not topics:
        return None
    return DomainTopicOutline(should_split=bool(should_split), topics=topics)
```

- [ ] **Step 4: Add SYSTEM_TOPIC_PLANNER prompt**

In `wiki/agent_prompts.py`, add at the end:

```python
SYSTEM_TOPIC_PLANNER = """\
You are a technical documentation architect. Based on the module analysis below,
plan a set of cohesive topic pages for a business domain.

Rules:
- Each topic should cover 3-8 functionally related modules
- Topic titles must reflect business capability (e.g. "家族任务系统"), not technical suffixes
- Every module must be assigned to exactly one topic
- Maximum 6 topics to avoid fragmentation
- If the domain has ≤5 modules, set should_split=false and create a single topic containing all modules

Return ONLY valid JSON (no markdown fences):
{
  "should_split": boolean,
  "topics": [
    {"title": "...", "modules": ["ModA", "ModB"], "description": "one sentence"}
  ]
}
"""
```

- [ ] **Step 5: Add _plan_topics method to DomainDocAgent**

In `wiki/domain_doc_agent.py`, add method to `DomainDocAgent` class:

```python
    async def _plan_topics(
        self,
        module_names: list[str],
        memory: WorkingMemory,
    ) -> DomainTopicOutline:
        """Plan topic structure via single LLM call after explore phase."""
        if len(module_names) <= 5:
            return DomainTopicOutline(
                should_split=False,
                topics=[TopicPlan(
                    title=self.domain_display_name,
                    modules=list(module_names),
                    description=f"{self.domain_display_name} overview",
                )],
            )

        from wiki.agent_prompts import SYSTEM_TOPIC_PLANNER

        module_list = "\n".join(f"- {m}" for m in module_names)
        call_info = "\n".join(memory.discovered_call_chains[:20]) if memory.discovered_call_chains else "No call chain data available."

        user_prompt = (
            f"## Domain: {self.domain_display_name}\n\n"
            f"## Module List ({len(module_names)} modules)\n{module_list}\n\n"
            f"## Key Call Relationships\n{call_info}\n"
        )
        messages = [
            {"role": "system", "content": SYSTEM_TOPIC_PLANNER},
            {"role": "user", "content": user_prompt},
        ]

        try:
            llm = self._page_agent._llm
            if hasattr(llm, "complete_json"):
                result = await llm.complete_json(messages, {}, max_tokens=2000)
                if isinstance(result, dict):
                    import json
                    raw = json.dumps(result, ensure_ascii=False)
                else:
                    raw = str(result)
            else:
                raw = await llm.generate(user_prompt, system=SYSTEM_TOPIC_PLANNER, max_tokens=2000)
                raw = str(raw)
            outline = _parse_topic_outline(raw)
            if outline:
                log.info("plan_topics_success", domain=self.domain_name, topics=len(outline.topics))
                return outline
        except Exception:
            log.warning("plan_topics_failed", domain=self.domain_name, exc_info=True)

        return DomainTopicOutline(
            should_split=False,
            topics=[TopicPlan(
                title=self.domain_display_name,
                modules=list(module_names),
                description=f"{self.domain_display_name} overview",
            )],
        )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_plan_topics.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add wiki/domain_doc_agent.py wiki/agent_prompts.py tests/wiki/test_plan_topics.py
git commit -m "feat(agent): add topic planning via _plan_topics() LLM call"
```

---

### Task 6: DomainDocAgent — _write_with_outline 集成

**Files:**
- Modify: `wiki/domain_doc_agent.py` (add _write_with_outline, integrate into generate_with_iterations)
- Test: `tests/wiki/test_plan_topics.py` (add integration tests)

- [ ] **Step 1: Write the failing test — write_with_outline produces multiple pages**

```python
# tests/wiki/test_plan_topics.py — append
@pytest.mark.asyncio
async def test_write_with_outline_produces_topic_pages():
    """When topic_outline has multiple topics, produce overview + topic pages."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## 业务概述\n家族任务系统概述...")
    agent = DomainDocAgent(
        domain_name="family-tasks",
        domain_display_name="家族任务",
        llm=llm,
        graph_store=MagicMock(),
    )
    outline = DomainTopicOutline(
        should_split=True,
        topics=[
            TopicPlan(title="任务创建", modules=["TaskCreate"], description="创建任务"),
            TopicPlan(title="任务奖励", modules=["RewardService"], description="奖励发放"),
        ],
    )
    memory = WorkingMemory()
    pages = await agent._write_with_outline(outline, "baseline context", memory, ["TaskCreate", "RewardService"])
    assert len(pages) >= 3  # 1 overview + 2 topics
    page_types = [p.get("page_type") for p in pages]
    assert "domain_overview" in page_types
    assert page_types.count("topic") == 2


@pytest.mark.asyncio
async def test_write_with_outline_single_topic_no_split():
    """When outline says should_split=False, produce single page."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="# Small Domain\n内容...")
    agent = DomainDocAgent(
        domain_name="small-domain",
        domain_display_name="小域",
        llm=llm,
        graph_store=MagicMock(),
    )
    outline = DomainTopicOutline(
        should_split=False,
        topics=[TopicPlan(title="小域", modules=["A", "B"], description="all")],
    )
    memory = WorkingMemory()
    pages = await agent._write_with_outline(outline, "context", memory, ["A", "B"])
    assert len(pages) == 1
    assert pages[0]["page_type"] == "domain_overview"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/wiki/test_plan_topics.py::test_write_with_outline_produces_topic_pages -v`
Expected: FAIL — `_write_with_outline` doesn't exist

- [ ] **Step 3: Implement _write_with_outline method**

In `wiki/domain_doc_agent.py`, add to `DomainDocAgent` class:

```python
    async def _write_with_outline(
        self,
        outline: DomainTopicOutline,
        baseline_context: str,
        memory: WorkingMemory,
        module_names: list[str],
    ) -> list[dict[str, Any]]:
        """Write pages according to topic outline."""
        if not outline.should_split or len(outline.topics) <= 1:
            content = await self._page_agent.write(
                self.domain_name, baseline_context, memory,
            )
            return _maybe_split(content, self.domain_name, self.domain_display_name)

        from wiki.path_conventions import domain_overview_path, domain_topic_path

        topic_pages: list[dict[str, Any]] = []
        topic_links: list[str] = []

        for topic in outline.topics:
            topic_module_list = ", ".join(topic.modules)
            topic_context = (
                f"{baseline_context}\n\n"
                f"--- TOPIC SCOPE ---\n"
                f"You are writing the \"{topic.title}\" section.\n"
                f"Focus ONLY on these modules: {topic_module_list}\n"
                f"Description: {topic.description}\n"
            )
            topic_content = await self._page_agent.write(
                self.domain_name, topic_context, memory,
            )
            topic_path = domain_topic_path(self.domain_name, topic.title)
            topic_pages.append({
                "page_type": "topic",
                "title": topic.title,
                "path": topic_path,
                "content": topic_content,
                "diagrams": [],
                "source_locations": [],
                "metadata": {
                    "node_count": len(topic.modules),
                    "edge_count": 0,
                    "generation_mode": "agent",
                },
                "business_domain": self.domain_name,
            })
            topic_links.append(f"- [[{topic.title}]]")

        overview_content = (
            f"# {self.domain_display_name}\n\n"
            + "\n".join(
                f"## {t.title}\n{t.description}\n"
                for t in outline.topics
            )
            + "\n## 章节导航\n\n" + "\n".join(topic_links)
        )
        overview_page = _make_page(overview_content, self.domain_name, self.domain_display_name)

        return [overview_page, *topic_pages]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_plan_topics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_doc_agent.py tests/wiki/test_plan_topics.py
git commit -m "feat(agent): implement _write_with_outline for topic-based writing"
```

---

### Task 7: DomainDocAgent — 集成 plan_topics 到 generate 流程

**Files:**
- Modify: `wiki/domain_doc_agent.py` (modify post_process / generate_with_iterations to use plan_topics)
- Test: `tests/wiki/test_domain_doc_agent.py` (existing tests should still pass)

- [ ] **Step 1: Modify post_process to use plan_topics when available**

Current signature is `def post_process(self, content: str, module_names: list[str], memory: Any) -> list[dict[str, Any]]`. Since `_write_with_outline` is async, we need to handle it in `generate_with_iterations` instead of `post_process`. Keep `post_process` as the sync fallback when topic_outline is None.

In `wiki/domain_doc_agent.py`, the existing `post_process` stays unchanged. The topic-aware path is handled in `generate_with_iterations` (see Step 2).

- [ ] **Step 2: Integrate _plan_topics call after explore phase in generate_with_iterations**

In `wiki/domain_doc_agent.py`, `generate_with_iterations()` method, after the explore timeout block (around line 318, after the `except (asyncio.TimeoutError, TimeoutError)` block) and before the `if not module_names:` check, add:

```python
        # Topic planning: determine if domain should be split into topic sub-pages
        outline = await self._plan_topics(module_names, memory)
        memory.topic_outline = outline
```

Then modify the early return for empty module_names (line 319-330) and the final post-processing at the end of the method. In both paths where `_maybe_split` is currently called, add a check:

```python
        if memory.topic_outline and memory.topic_outline.should_split and len(memory.topic_outline.topics) > 1:
            pages = await self._write_with_outline(
                memory.topic_outline, baseline_context, memory, module_names,
            )
        else:
            pages = _maybe_split(content, self.domain_name, self.domain_display_name)
```

This ensures the existing write/quality loop still runs for single-page mode, and `_write_with_outline` only triggers when there's a valid multi-topic outline.

- [ ] **Step 3: Run existing domain_doc_agent tests to verify no regressions**

Run: `uv run pytest tests/wiki/test_domain_doc_agent.py -v`
Expected: ALL PASS (existing behavior preserved — small domains get `should_split=False`, LLM mock returns no valid JSON so outline stays as fallback single-topic)

- [ ] **Step 4: Commit**

```bash
git add wiki/domain_doc_agent.py
git commit -m "feat(agent): integrate plan_topics into DomainDocAgent generation flow"
```

---

### Task 8: _maybe_split 增强 — 小 section 合并

**Files:**
- Modify: `wiki/domain_doc_agent.py:92-136` (_maybe_split function)
- Test: `tests/wiki/test_plan_topics.py`

- [ ] **Step 1: Write the failing test — adjacent small sections merge**

```python
# tests/wiki/test_plan_topics.py — append
from wiki.domain_doc_agent import _maybe_split


def test_maybe_split_merges_small_adjacent_sections():
    """Adjacent sections with combined tokens < 1000 should merge."""
    content = (
        "# Domain Overview\nIntro paragraph.\n\n"
        "## Section A\nShort content A.\n\n"
        "## Section B\nShort content B.\n\n"
        "## Section C\nMuch longer content C that has several paragraphs " * 50 + "\n"
    )
    pages = _maybe_split(content, "test-domain", "Test Domain")
    # A+B should merge into one topic (both small), C stays separate
    topic_pages = [p for p in pages if p["page_type"] == "topic"]
    assert len(topic_pages) <= 2  # merged A+B as one, C as another


def test_maybe_split_parent_has_overview_content():
    """Parent page must contain at least some overview content, not just links."""
    content = (
        "## Section A\nContent A.\n\n"
        "## Section B\nContent B.\n\n"
    )
    # Artificially make it exceed MAX_PAGE_TOKENS
    content = content * 100
    pages = _maybe_split(content, "test", "Test")
    parent = pages[0]
    assert parent["page_type"] == "domain_overview"
    # Parent should have more than just links
    assert "## 章节导航" in parent["content"] or len(parent["content"]) > 50
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_plan_topics.py::test_maybe_split_merges_small_adjacent_sections -v`
Expected: FAIL — no merging logic exists

- [ ] **Step 3: Enhance _maybe_split with section merging**

In `wiki/domain_doc_agent.py`, modify `_maybe_split()`:

```python
def _maybe_split(
    content: str,
    domain_slug: str,
    domain_display_name: str = "",
) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections into topic sub-pages."""
    display = domain_display_name or domain_slug
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_slug, display)]

    sections = re.split(r"(?=^## )", content, flags=re.MULTILINE)
    sections = [s for s in sections if s]
    if len(sections) <= 1:
        return [_make_page(content, domain_slug, display)]

    from wiki.path_conventions import domain_topic_path

    overview = sections[0] if not sections[0].startswith("## ") else ""
    body_sections = sections[1:] if overview else sections

    # Merge adjacent small sections (combined < 1000 tokens)
    merged: list[str] = []
    buf = ""
    for section in body_sections:
        if buf and (len(buf) + len(section)) // 4 < 1000:
            buf += "\n" + section
        else:
            if buf:
                merged.append(buf)
            buf = section
    if buf:
        merged.append(buf)

    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in merged:
        title_match = re.match(r"^## (.+)", section)
        section_title = title_match.group(1).strip() if title_match else "Untitled"
        topic_path = domain_topic_path(domain_slug, section_title)
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

    if not overview.strip():
        overview = f"# {display}\n\n"
    parent_content = overview + "\n## 章节导航\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_slug, display)

    return [parent_page, *child_pages]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_plan_topics.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add wiki/domain_doc_agent.py tests/wiki/test_plan_topics.py
git commit -m "improve(split): merge small adjacent sections in _maybe_split fallback"
```

---

## Phase 3: 导航元数据

### Task 9: NavigationContext 填充 in create_links_node

**Files:**
- Modify: `wiki/nodes/links.py` (add navigation population)
- Test: `tests/wiki/test_navigation_context.py` (create)

- [ ] **Step 1: Write the failing tests**

```python
# tests/wiki/test_navigation_context.py — create new file
from __future__ import annotations

import pytest
from wiki.nodes.links import create_links_node


@pytest.mark.asyncio
async def test_navigation_context_populated_for_domain_pages():
    """Domain overview pages get parent_path, child_paths, sibling_paths."""
    state = {
        "pages": [
            {
                "path": "/__domains__/parent-domain/_overview",
                "title": "Parent Domain",
                "content": "# Parent\n[[Child A]] [[Child B]]",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/child-a/_overview",
                "title": "Child A",
                "content": "# Child A overview",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/child-b/_overview",
                "title": "Child B",
                "content": "# Child B overview",
                "page_type": "domain_overview",
            },
        ],
        "domain_tree": [
            {
                "name": "parent-domain",
                "display_name": "Parent Domain",
                "modules": [],
                "children": [
                    {"name": "child-a", "display_name": "Child A", "modules": ["ModA"], "children": []},
                    {"name": "child-b", "display_name": "Child B", "modules": ["ModB"], "children": []},
                ],
            },
        ],
    }
    result = await create_links_node(state)

    pages = state["pages"]
    parent_page = next(p for p in pages if p["path"] == "/__domains__/parent-domain/_overview")
    child_a = next(p for p in pages if p["path"] == "/__domains__/child-a/_overview")

    parent_nav = parent_page.get("navigation", {})
    assert "/__domains__/child-a/_overview" in parent_nav.get("child_paths", [])
    assert "/__domains__/child-b/_overview" in parent_nav.get("child_paths", [])
    assert parent_nav.get("parent_path", "") == ""

    child_nav = child_a.get("navigation", {})
    assert child_nav.get("parent_path") == "/__domains__/parent-domain/_overview"
    assert "/__domains__/child-b/_overview" in child_nav.get("sibling_paths", [])


@pytest.mark.asyncio
async def test_navigation_context_topic_pages():
    """Topic pages get parent_path pointing to their domain overview."""
    state = {
        "pages": [
            {
                "path": "/__domains__/my-domain/_overview",
                "title": "My Domain",
                "content": "# My Domain",
                "page_type": "domain_overview",
            },
            {
                "path": "/__domains__/my-domain/topic-a/_topic",
                "title": "Topic A",
                "content": "# Topic A",
                "page_type": "topic",
            },
        ],
        "domain_tree": [
            {
                "name": "my-domain",
                "display_name": "My Domain",
                "modules": ["ModA", "ModB"],
                "children": [],
            },
        ],
    }
    result = await create_links_node(state)

    topic_page = state["pages"][1]
    topic_nav = topic_page.get("navigation", {})
    assert topic_nav.get("parent_path") == "/__domains__/my-domain/_overview"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_navigation_context.py -v`
Expected: FAIL — pages don't have `navigation` field

- [ ] **Step 3: Implement NavigationContext population in create_links_node**

In `wiki/nodes/links.py`, add navigation population after the wikilink resolution:

```python
async def create_links_node(state: dict[str, Any]) -> dict[str, Any]:
    """Phase 4c-4d: resolve cross-links, populate NavigationContext, prepare link metadata."""
    pages = state.get("pages", [])
    page_titles = {p.get("title", "").lower(): p.get("path", "") for p in pages}
    page_paths = {
        p.get("path", "").rsplit("/", 1)[-1].lower(): p.get("path", "")
        for p in pages
        if p.get("path")
    }

    link_pattern = re.compile(r"\[\[([^\]]+)\]\]")
    resolved_links: dict[str, list[dict[str, str]]] = {}

    for page in pages:
        page_path = page.get("path", "")
        content = page.get("content", "")
        links: list[dict[str, str]] = []

        for match in link_pattern.finditer(content):
            link_text = match.group(1)
            key = link_text.lower()
            target = page_titles.get(key) or page_paths.get(key)
            if target and target != page_path:
                links.append({"from_text": link_text, "target_path": target})
                log.debug("wiki_link_resolved", source=page_path, target=target)

        if links:
            resolved_links[page_path] = links

    # Populate NavigationContext from domain_tree
    _populate_navigation_from_domain_tree(pages, state.get("domain_tree") or [])

    log.info(
        "create_links_done",
        pages_with_links=len(resolved_links),
        total_links=sum(len(v) for v in resolved_links.values()),
    )
    return {"resolved_links": resolved_links}


def _populate_navigation_from_domain_tree(
    pages: list[dict[str, Any]],
    domain_tree: list[dict[str, Any]],
) -> None:
    """Walk domain_tree and populate navigation field on matching pages."""
    from wiki.path_conventions import domain_overview_path

    pages_by_path: dict[str, dict[str, Any]] = {
        p.get("path", ""): p for p in pages if p.get("path")
    }

    def _walk(
        nodes: list[dict[str, Any]],
        parent_path: str,
        breadcrumbs: list[str],
    ) -> None:
        sibling_paths = [
            domain_overview_path(n.get("name", ""))
            for n in nodes
            if domain_overview_path(n.get("name", "")) in pages_by_path
        ]

        for node in nodes:
            name = node.get("name", "")
            if not name:
                continue
            overview_path = domain_overview_path(name)
            page = pages_by_path.get(overview_path)
            children = node.get("children", [])

            child_overview_paths = [
                domain_overview_path(c.get("name", ""))
                for c in children
                if domain_overview_path(c.get("name", "")) in pages_by_path
            ]

            # Find topic pages for this domain
            topic_paths = [
                p_path for p_path, p_data in pages_by_path.items()
                if (
                    p_data.get("page_type") == "topic"
                    and p_path.startswith(f"/__domains__/{name}/")
                )
            ]

            if page is not None:
                current_siblings = [s for s in sibling_paths if s != overview_path]
                page["navigation"] = {
                    "parent_path": parent_path,
                    "parent_title": "",
                    "sibling_paths": current_siblings,
                    "child_paths": child_overview_paths + topic_paths,
                    "related_flow_paths": [],
                    "breadcrumbs": breadcrumbs + [overview_path],
                }

            # Set navigation for topic pages of this domain
            for tp in topic_paths:
                topic_page = pages_by_path.get(tp)
                if topic_page:
                    other_topics = [t for t in topic_paths if t != tp]
                    topic_page["navigation"] = {
                        "parent_path": overview_path,
                        "parent_title": node.get("display_name", name),
                        "sibling_paths": other_topics,
                        "child_paths": [],
                        "related_flow_paths": [],
                        "breadcrumbs": breadcrumbs + [overview_path, tp],
                    }

            if children:
                _walk(
                    children,
                    parent_path=overview_path,
                    breadcrumbs=breadcrumbs + [overview_path],
                )

    _walk(domain_tree, parent_path="", breadcrumbs=[])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_navigation_context.py -v`
Expected: ALL PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `uv run pytest tests/wiki/ -x --timeout=60`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add wiki/nodes/links.py tests/wiki/test_navigation_context.py
git commit -m "feat(navigation): populate NavigationContext from domain_tree in create_links_node"
```

---

## Phase 4: 集成验证

### Task 10: 端到端管线集成测试

**Files:**
- Modify: `tests/wiki/test_pipeline_progress.py` or create integration test

- [ ] **Step 1: Run existing pipeline tests to verify no regressions**

Run: `uv run pytest tests/wiki/test_pipeline_graph_v2.py tests/wiki/test_pipeline_progress.py tests/wiki/test_compose_parents.py tests/wiki/test_summarize_leaves.py -v`
Expected: ALL PASS

- [ ] **Step 2: Run the full test suite**

Run: `uv run pytest -x --timeout=120`
Expected: ALL PASS (no regressions across ~3775 tests)

- [ ] **Step 3: Commit if any test fixes were needed**

```bash
git add -A
git commit -m "fix: resolve integration test regressions from tree structure enhancement"
```

---

## Summary of Changes

| Phase | Task | Files Changed | Tests |
|-------|------|--------------|-------|
| 1 | Pipeline nodes | `pipeline_graph.py` | `test_pipeline_graph_v2.py` |
| 1 | Path convention fix | `nodes/aggregate.py` | `test_compose_parents.py` |
| 1 | Prompt improvement | `prompts.py`, `nodes/aggregate.py` | existing tests |
| 2 | WorkingMemory field | `page_agent.py` | `test_plan_topics.py` |
| 2 | Topic planning | `domain_doc_agent.py`, `agent_prompts.py` | `test_plan_topics.py` |
| 2 | Write with outline | `domain_doc_agent.py` | `test_plan_topics.py` |
| 2 | Integrate into flow | `domain_doc_agent.py` | `test_domain_doc_agent.py` |
| 2 | _maybe_split enhance | `domain_doc_agent.py` | `test_plan_topics.py` |
| 3 | NavigationContext | `nodes/links.py` | `test_navigation_context.py` |
| 4 | Integration verify | — | full suite |
