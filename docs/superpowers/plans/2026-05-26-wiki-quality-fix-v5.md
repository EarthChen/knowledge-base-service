# Wiki Quality Fix v5 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix 4 wiki quality issues: restore topic page generation (P0), filter infrastructure domains (P1), reject skeleton pages (P1), and enforce term consistency (P2).

**Architecture:** Hook pattern in DocOrchestrator for topic writing; post-clustering filter function for infrastructure domains; banner injection in finalize node for skeletons; dynamic glossary extraction + prompt injection + soft guardrail for term consistency.

**Tech Stack:** Python 3.12, pytest-asyncio, AsyncMock, Pydantic Settings, structlog

---

## File Map

| File | Responsibility | Tasks |
|------|---------------|-------|
| `core/config.py` | Config flags (`enable_topic_pages`, `infrastructure_slug_keywords`, `term_overrides`) | T1, T2, T4 |
| `wiki/agents/doc_orchestrator.py` | `_write_topics()` hook + branch in `generate()` | T1 |
| `wiki/domain_doc_agent.py` | Override `_write_topics()`, store `_topic_outline` | T1 |
| `wiki/nodes/graph_domain_decompose.py` | `_filter_infrastructure_domains()` function | T2 |
| `wiki/nodes/finalize.py` | Skeleton banner injection | T3 |
| `wiki/output_guardrail.py` | `TermConsistencyCheck` | T4 |
| `wiki/agent_prompts.py` | `build_term_glossary_prompt()` helper | T4 |
| `wiki/prompts.py` | Anti-hallucination constraint in parent overview prompt | T4 |
| Tests: `tests/wiki/` | All test files | T1-T4 |

---

### Task 1: F1 — Restore Topic Page Generation (P0)

**Files:**
- Modify: `core/config.py:304-308` (add `enable_topic_pages` flag)
- Modify: `wiki/agents/doc_orchestrator.py:71-115` (add hook + branch)
- Modify: `wiki/domain_doc_agent.py:507-514` (store outline + override hook)
- Test: `tests/wiki/test_topic_generation_restore.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/wiki/test_topic_generation_restore.py`:

```python
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_outline():
    outline = MagicMock()
    outline.should_split = True
    outline.topics = [
        MagicMock(title="Topic A", modules=["ModA", "ModB"]),
        MagicMock(title="Topic B", modules=["ModC", "ModD"]),
    ]
    return outline


class TestOrchestratorWriteTopicsHook:
    @pytest.mark.asyncio
    async def test_write_topics_default_returns_none(self):
        """Default _write_topics hook returns None (no topic writing)."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        agent = MagicMock()
        orch = DocOrchestrator.__new__(DocOrchestrator)
        result = await orch._write_topics(None, "", MagicMock(), [])
        assert result is None

    @pytest.mark.asyncio
    async def test_orchestrator_calls_write_topics_when_plan_exists(self):
        """When plan_topics returns topics, _write_topics is called."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        orch = DocOrchestrator.__new__(DocOrchestrator)
        orch._name = "test"
        orch._max_iterations = 1
        orch._agent = MagicMock()
        orch.iteration_history = []

        fake_pages = [{"title": "Overview", "page_type": "domain_overview"}]
        orch._write_topics = AsyncMock(return_value=fake_pages)
        orch.plan_topics = AsyncMock(return_value=["topic1", "topic2"])
        orch.explore = AsyncMock(return_value=MagicMock())
        orch.get_phase_timeout = MagicMock(return_value=None)

        memory = MagicMock()
        memory.topic_outline = None
        orch._agent.create_memory = MagicMock(return_value=memory)

        result = await orch.generate(["ModA", "ModB"], "baseline")
        orch._write_topics.assert_awaited_once()
        assert result == fake_pages

    @pytest.mark.asyncio
    async def test_orchestrator_fallback_when_no_plan(self):
        """When plan_topics returns None, single-body write loop is used."""
        from wiki.agents.doc_orchestrator import DocOrchestrator

        orch = DocOrchestrator.__new__(DocOrchestrator)
        orch._name = "test"
        orch._max_iterations = 1
        orch._agent = MagicMock()
        orch.iteration_history = []
        orch._write_system_prompt = "sys"
        orch._build_write_prompt = MagicMock(return_value="prompt")

        orch._write_topics = AsyncMock(return_value=None)
        orch.plan_topics = AsyncMock(return_value=None)
        orch.explore = AsyncMock(return_value=MagicMock())
        orch.get_phase_timeout = MagicMock(return_value=None)
        orch._verify_code_blocks = AsyncMock(side_effect=lambda c, m: c)
        orch.evaluate = AsyncMock(return_value=MagicMock(uncovered_modules=[]))
        orch.run_guardrails = AsyncMock(return_value=None)
        orch.build_iteration_trace = MagicMock()
        orch.is_acceptable = MagicMock(return_value=True)
        orch.post_process = MagicMock(return_value=[{"title": "Single"}])

        memory = MagicMock()
        orch._agent.create_memory = MagicMock(return_value=memory)
        orch._agent.run_generation = AsyncMock(return_value="content")

        result = await orch.generate(["ModA"], "baseline")
        orch._agent.run_generation.assert_awaited_once()
        assert result == [{"title": "Single"}]


class TestDomainDocAgentWriteTopics:
    @pytest.mark.asyncio
    async def test_write_topics_calls_write_with_outline(self, mock_outline):
        """DomainDocAgent._write_topics calls _write_with_outline with stored outline."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_outline = mock_outline
        agent._write_with_outline = AsyncMock(return_value=[
            {"title": "Overview", "page_type": "domain_overview"},
            {"title": "Topic A", "page_type": "topic"},
        ])

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = True
            result = await agent._write_topics(
                mock_outline.topics, "baseline", MagicMock(), ["ModA", "ModB"]
            )

        assert result is not None
        assert len(result) == 2
        agent._write_with_outline.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_write_topics_disabled_by_config(self, mock_outline):
        """When enable_topic_pages=False, returns None."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_outline = mock_outline

        with patch("wiki.domain_doc_agent.get_settings") as mock_settings:
            mock_settings.return_value.wiki.enable_topic_pages = False
            result = await agent._write_topics(
                mock_outline.topics, "baseline", MagicMock(), ["ModA"]
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_plan_topics_stores_outline(self):
        """plan_topics() stores full DomainTopicOutline in _topic_outline."""
        from wiki.domain_doc_agent import DomainDocAgent

        agent = DomainDocAgent.__new__(DomainDocAgent)
        agent._topic_split_done = False

        outline = MagicMock()
        outline.should_split = True
        outline.topics = [MagicMock(), MagicMock(), MagicMock()]
        agent._plan_topics = AsyncMock(return_value=outline)

        result = await agent.plan_topics(MagicMock(), ["A", "B", "C", "D", "E", "F"])

        assert result is not None
        assert agent._topic_outline is outline
        assert agent._topic_split_done is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_topic_generation_restore.py -v`
Expected: Multiple FAIL — `_write_topics` attribute not found, `_topic_outline` not stored, `enable_topic_pages` config missing.

- [ ] **Step 3: Add `enable_topic_pages` config flag**

In `core/config.py`, after line 308 (`topic_split_quality_check`), add:

```python
    enable_topic_pages: bool = Field(
        default=True, description="Enable topic page generation in Orchestrator path"
    )
```

- [ ] **Step 4: Add `_write_topics()` hook to DocOrchestrator**

In `wiki/agents/doc_orchestrator.py`, add default hook method (after `plan_topics` method, before private helpers):

```python
    async def _write_topics(
        self,
        topic_plan: list[Any] | None,
        baseline_context: str,
        memory: Any,
        module_names: list[str],
    ) -> list[dict[str, Any]] | None:
        return None
```

In the `generate()` method, after `topic_plan = await self.plan_topics(...)` block (line ~73), insert the topic-writing branch:

```python
        topic_plan = await self.plan_topics(memory, module_names)
        if topic_plan is not None and hasattr(memory, "topic_outline"):
            memory.topic_outline = topic_plan

        if topic_plan is not None:
            pages = await self._write_topics(
                topic_plan, baseline_context, memory, module_names,
            )
            if pages is not None:
                return pages

        content = ""
        for iteration in range(self._max_iterations):
```

- [ ] **Step 5: Store `_topic_outline` in DomainDocAgent.plan_topics()**

In `wiki/domain_doc_agent.py`, modify `plan_topics()` (around line 507-514):

```python
    async def plan_topics(self, memory: Any, module_names: list[str]) -> list[Any] | None:
        if len(module_names) <= 5:
            return None
        outline = await self._plan_topics(module_names, memory)
        if outline.should_split and len(outline.topics) > 1:
            self._topic_split_done = True
            self._topic_outline = outline
            return outline.topics
        return None
```

- [ ] **Step 6: Override `_write_topics()` in DomainDocAgent**

Add new method in `wiki/domain_doc_agent.py` (after `plan_topics` method):

```python
    async def _write_topics(
        self,
        topic_plan: list[Any] | None,
        baseline_context: str,
        memory: Any,
        module_names: list[str],
    ) -> list[dict[str, Any]] | None:
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

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_topic_generation_restore.py -v`
Expected: All PASS

- [ ] **Step 8: Run existing tests to verify no regressions**

Run: `uv run pytest tests/wiki/nodes/test_finalize_node.py tests/wiki/nodes/test_domain_compose.py tests/wiki/test_domain_agent_code_verify.py -x`
Expected: All PASS

---

### Task 2: F2 — Infrastructure Domain Filtering (P1)

**Files:**
- Modify: `core/config.py:311-316` (add `infrastructure_slug_keywords`)
- Modify: `wiki/nodes/graph_domain_decompose.py` (add `_filter_infrastructure_domains`)
- Test: `tests/wiki/test_infrastructure_domain_filter.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/wiki/test_infrastructure_domain_filter.py`:

```python
from __future__ import annotations

import pytest


class TestFilterInfrastructureDomains:
    def test_single_class_domain_merged(self):
        """Domain with exactly 1 PascalCase module is merged into largest neighbor."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "family-core-operations": [("repo", "FamilyCoreService"), ("repo", "FamilyDao")],
            "backdoorserviceimpl": [("repo", "BackDoorServiceImpl")],
        }
        display_names = {
            "family-core-operations": "家族核心运营",
            "backdoorserviceimpl": "后门运维",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, []
        )
        assert "backdoorserviceimpl" not in result_mapping
        assert "family-core-operations" in result_mapping
        assert len(result_mapping["family-core-operations"]) == 3

    def test_infrastructure_keyword_filtered(self):
        """Domain slug containing infrastructure keyword is filtered."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "user-profile": [("repo", "UserService"), ("repo", "ProfileDao")],
            "datasourceconfiguration": [("repo", "DataSourceConfiguration")],
        }
        display_names = {
            "user-profile": "用户资料",
            "datasourceconfiguration": "数据源配置",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert "datasourceconfiguration" not in result_mapping
        assert "user-profile" in result_mapping

    def test_legitimate_domain_preserved(self):
        """Normal multi-module business domain is never filtered."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "family-core-operations": [("repo", "FamilyCoreService"), ("repo", "FamilyDao")],
            "intimacy-relations": [("repo", "IntimacyService"), ("repo", "IntimacyDao")],
        }
        display_names = {
            "family-core-operations": "家族核心运营",
            "intimacy-relations": "亲密度关系",
        }
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert len(result_mapping) == 2

    def test_multi_module_domain_not_filtered_by_keyword(self):
        """Multi-module domain is NOT filtered even if slug matches keyword."""
        from wiki.nodes.graph_domain_decompose import _filter_infrastructure_domains

        domain_mapping = {
            "app-configuration-management": [("r", "ConfigA"), ("r", "ConfigB"), ("r", "ConfigC")],
        }
        display_names = {"app-configuration-management": "配置管理"}
        result_mapping, result_names = _filter_infrastructure_domains(
            domain_mapping, display_names, ["configuration"]
        )
        assert "app-configuration-management" in result_mapping
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_infrastructure_domain_filter.py -v`
Expected: FAIL — `_filter_infrastructure_domains` not found.

- [ ] **Step 3: Add `infrastructure_slug_keywords` config**

In `core/config.py`, after `domain_budget_max` field (line ~313), add:

```python
    infrastructure_slug_keywords: list[str] = Field(
        default=["configuration", "typehandler", "aspect", "package-info", "wrapper"],
        description="Slug keywords that mark a single-module domain as infrastructure (merged into nearby domain)",
    )
```

- [ ] **Step 4: Implement `_filter_infrastructure_domains()`**

In `wiki/nodes/graph_domain_decompose.py`, add function (near other domain cleanup functions like `_cleanup_collision_slugs`):

```python
import re

_PASCAL_CASE_RE = re.compile(r"^[A-Z][a-zA-Z0-9]+$")


def _filter_infrastructure_domains(
    domain_mapping: dict[str, list[tuple[str, str]]],
    domain_display_names: dict[str, str],
    infrastructure_keywords: list[str],
) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
    """Filter infrastructure domains by merging them into the largest remaining domain.

    Rules:
    1. Single-module domain where module name is PascalCase → infrastructure
    2. Slug contains any infrastructure keyword AND module count ≤ 2 → infrastructure
    """
    if not domain_mapping:
        return domain_mapping, domain_display_names

    infra_slugs: set[str] = set()
    for slug, modules in domain_mapping.items():
        if len(modules) == 1:
            _, name = modules[0]
            if _PASCAL_CASE_RE.match(name):
                infra_slugs.add(slug)
                continue
        if len(modules) <= 2 and infrastructure_keywords:
            slug_lower = slug.lower()
            if any(kw in slug_lower for kw in infrastructure_keywords):
                infra_slugs.add(slug)

    if not infra_slugs:
        return domain_mapping, domain_display_names

    remaining = {s: m for s, m in domain_mapping.items() if s not in infra_slugs}
    if not remaining:
        return domain_mapping, domain_display_names

    largest_slug = max(remaining, key=lambda s: len(remaining[s]))

    for slug in infra_slugs:
        remaining[largest_slug].extend(domain_mapping[slug])

    remaining_names = {s: n for s, n in domain_display_names.items() if s not in infra_slugs}
    return remaining, remaining_names
```

- [ ] **Step 5: Wire filter into domain decompose pipeline**

In `wiki/nodes/graph_domain_decompose.py`, in the main decomposition function, after `_cleanup_collision_slugs()` call and before `_enforce_domain_budget()`, add:

```python
from core.config import get_settings

wiki_cfg = get_settings().wiki
domain_mapping, domain_display_names = _filter_infrastructure_domains(
    domain_mapping, domain_display_names, wiki_cfg.infrastructure_slug_keywords,
)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_infrastructure_domain_filter.py -v`
Expected: All PASS

- [ ] **Step 7: Run existing decompose tests**

Run: `uv run pytest tests/wiki/nodes/test_graph_domain_decompose.py -x`
Expected: All PASS

---

### Task 3: F5 — Skeleton Page Rejection Gate (P1)

**Files:**
- Modify: `wiki/nodes/finalize.py:146-188` (add skeleton banner)
- Test: `tests/wiki/test_finalize_skeleton_banner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/wiki/test_finalize_skeleton_banner.py`:

```python
from __future__ import annotations

import pytest


_SKELETON_BANNER = "> ⚠️ 本域文档待完善，内容可能不完整。"


class TestSkeletonBannerInjection:
    @pytest.mark.asyncio
    async def test_skeleton_page_gets_banner(self):
        """Page < 2000 chars of type domain_overview gets warning banner prepended."""
        from wiki.nodes.finalize import finalize_node

        short_content = "# Test Domain\n\n## 概述\n\nShort.\n\n## 核心业务流程\n\n## 依赖关系\n"
        state = {
            "pages": [
                {
                    "title": "Test",
                    "path": "/__domains__/test/_overview",
                    "page_type": "domain_overview",
                    "content": short_content,
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_normal_page_no_banner(self):
        """Page >= 2000 chars does NOT get banner."""
        from wiki.nodes.finalize import finalize_node

        long_content = "# Normal Domain\n\n## 概述\n\n" + ("这是一段中文内容。" * 200)
        state = {
            "pages": [
                {
                    "title": "Normal",
                    "path": "/__domains__/normal/_overview",
                    "page_type": "domain_overview",
                    "content": long_content,
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert not page["content"].startswith(_SKELETON_BANNER)

    @pytest.mark.asyncio
    async def test_topic_page_no_banner(self):
        """Short topic pages do NOT get banner (only domain_overview)."""
        from wiki.nodes.finalize import finalize_node

        state = {
            "pages": [
                {
                    "title": "Topic",
                    "path": "/__domains__/test/topic-a",
                    "page_type": "topic",
                    "content": "# Short Topic\n\nBrief.",
                }
            ]
        }
        result = await finalize_node(state)
        page = result["pages"][0]
        assert not page["content"].startswith(_SKELETON_BANNER)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_finalize_skeleton_banner.py -v`
Expected: FAIL — skeleton pages do not get banner.

- [ ] **Step 3: Implement skeleton banner injection in finalize**

In `wiki/nodes/finalize.py`, modify the `finalize_node` function. After the `content = _remove_invalid_wikilinks(...)` line (around line 171), add skeleton detection:

```python
            content = _remove_invalid_wikilinks(content, valid_targets)

            if (
                page.get("page_type") == "domain_overview"
                and len(content) < 2000
            ):
                banner = "> ⚠️ 本域文档待完善，内容可能不完整。\n\n"
                content = banner + content
                log.warning(
                    "skeleton_page_detected",
                    page_path=page.get("path"),
                    content_len=len(content),
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_finalize_skeleton_banner.py -v`
Expected: All PASS

- [ ] **Step 5: Run existing finalize tests**

Run: `uv run pytest tests/wiki/nodes/test_finalize_node.py -x`
Expected: All PASS

---

### Task 4: F4 — Term Consistency + Parent Anti-Hallucination (P2)

**Files:**
- Modify: `core/config.py` (add `term_overrides`)
- Modify: `wiki/agent_prompts.py` (add `build_term_glossary_prompt`)
- Modify: `wiki/output_guardrail.py` (add `TermConsistencyCheck`)
- Modify: `wiki/prompts.py` (add anti-hallucination constraint)
- Test: `tests/wiki/test_term_consistency.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/wiki/test_term_consistency.py`:

```python
from __future__ import annotations

import pytest


class TestBuildTermGlossaryPrompt:
    def test_builds_glossary_section(self):
        """Glossary dict produces formatted prompt section."""
        from wiki.agent_prompts import build_term_glossary_prompt

        glossary = {"closed-friend": "挚友", "family": "家族", "intimacy": "亲密度"}
        result = build_term_glossary_prompt(glossary)
        assert "挚友" in result
        assert "家族" in result
        assert "亲密度" in result
        assert "术语约束" in result

    def test_empty_glossary_returns_empty(self):
        """Empty glossary produces empty string."""
        from wiki.agent_prompts import build_term_glossary_prompt

        result = build_term_glossary_prompt({})
        assert result == ""


class TestTermConsistencyCheck:
    @pytest.mark.asyncio
    async def test_detects_mismatch(self):
        """Detects when English term appears without Chinese equivalent."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "这是一篇关于 closed friend 关系管理的文档。"
        glossary = {"closed-friend": "挚友", "closed friend": "挚友"}
        result = await check.evaluate(content, {"term_glossary": glossary})
        assert result.has_violations

    @pytest.mark.asyncio
    async def test_passes_when_consistent(self):
        """No violation when Chinese term is used correctly."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "这是一篇关于挚友关系管理的文档。closed friend 对应的中文是挚友。"
        glossary = {"closed friend": "挚友"}
        result = await check.evaluate(content, {"term_glossary": glossary})
        assert not result.has_violations

    @pytest.mark.asyncio
    async def test_empty_glossary_passes(self):
        """Empty glossary always passes."""
        from wiki.output_guardrail import TermConsistencyCheck

        check = TermConsistencyCheck()
        content = "任意内容"
        result = await check.evaluate(content, {"term_glossary": {}})
        assert not result.has_violations


class TestTermOverrideConfig:
    def test_term_overrides_in_config(self):
        """term_overrides field exists in AppWikiFlags."""
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert hasattr(flags, "term_overrides")
        assert isinstance(flags.term_overrides, dict)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/wiki/test_term_consistency.py -v`
Expected: FAIL — `build_term_glossary_prompt` not found, `TermConsistencyCheck` not found, `term_overrides` not in config.

- [ ] **Step 3: Add `term_overrides` config**

In `core/config.py`, in the `AppWikiFlags` class, after `auto_cleanup_checkpoint` field:

```python
    term_overrides: dict[str, str] = Field(
        default_factory=dict,
        description="Manual term override map {english: chinese}, takes precedence over auto-extracted",
    )
```

- [ ] **Step 4: Add `build_term_glossary_prompt()` in agent_prompts.py**

In `wiki/agent_prompts.py`, add function:

```python
def build_term_glossary_prompt(glossary: dict[str, str]) -> str:
    """Build a term glossary prompt section from a glossary dict."""
    if not glossary:
        return ""
    lines = [f"- {eng} → **{chn}**" for eng, chn in sorted(glossary.items())]
    return (
        "\n--- 术语约束 (Term Glossary) ---\n"
        "以下术语在本项目中有确定的中文表达，请严格使用:\n"
        + "\n".join(lines)
        + "\n---\n"
    )
```

- [ ] **Step 5: Add `TermConsistencyCheck` in output_guardrail.py**

In `wiki/output_guardrail.py`, add class:

```python
from dataclasses import dataclass, field as dc_field


@dataclass
class TermCheckResult:
    has_violations: bool = False
    violations: list[str] = dc_field(default_factory=list)


class TermConsistencyCheck:
    """Soft guardrail: check if English terms appear without their Chinese equivalents."""

    async def evaluate(self, content: str, context: dict[str, Any]) -> TermCheckResult:
        glossary = context.get("term_glossary", {})
        if not glossary:
            return TermCheckResult()

        violations: list[str] = []
        content_lower = content.lower()
        for eng_term, chn_term in glossary.items():
            if eng_term.lower() in content_lower and chn_term not in content:
                violations.append(f"'{eng_term}' found without '{chn_term}'")

        return TermCheckResult(
            has_violations=len(violations) > 0,
            violations=violations,
        )
```

- [ ] **Step 6: Add anti-hallucination constraint to parent overview prompt**

In `wiki/prompts.py`, find the `system_wiki_parent_overview()` function and append to the prompt string:

```python
"\n\n严禁发明代码库中不存在的组件名称、接口名称或事件名称。仅引用子域文档中已确认存在的实体。"
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/wiki/test_term_consistency.py -v`
Expected: All PASS

- [ ] **Step 8: Run full test suite for touched files**

Run: `uv run pytest tests/wiki/test_term_consistency.py tests/wiki/test_language_guardrail.py tests/wiki/nodes/test_finalize_node.py -x`
Expected: All PASS

---

## Self-Review Checklist

- [x] **Spec coverage:** F1 (Task 1), F2 (Task 2), F5 (Task 3), F4 (Task 4), F3 (resolved, no task needed)
- [x] **No placeholders:** All steps have complete code
- [x] **Type consistency:** `_write_topics` signature matches between DocOrchestrator and DomainDocAgent; `_filter_infrastructure_domains` return type is consistent
- [x] **TDD:** Each task starts with failing tests
- [x] **Dependencies:** T1 and T2 are independent. T3 after T1. T4 after T1+T2.
