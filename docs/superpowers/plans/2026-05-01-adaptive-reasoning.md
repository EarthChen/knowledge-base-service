# Adaptive Reasoning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace unused cot_generator.py with a 3-level ReasoningLevel system (NONE/GUIDED/MULTI_STEP) that automatically adapts reasoning depth based on domain complexity.

**Architecture:** New `wiki/reasoning.py` module provides `select_reasoning_level()` driven by `DomainComplexityScorer`. `GuidedPromptEnhancer` injects reasoning steps into prompts. `MultiStepReasoner` performs plan-then-generate for HIGH complexity domains. `TopicPageComposer` integrates `MultiStepReasoner` internally.

**Tech Stack:** Python 3.11+, pytest, structlog, existing LLMPort Protocol

---

## File Map

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `wiki/reasoning.py` | ReasoningLevel, TaskType, select_reasoning_level, GuidedPromptEnhancer, MultiStepReasoner |
| Create | `tests/wiki/test_reasoning.py` | Unit tests for reasoning module |
| Modify | `wiki/context.py:24-32` | Add `reasoning_effort` to LLMPort Protocol |
| Modify | `wiki/topic_page_composer.py` | Accept `reasoning_level`, use MultiStepReasoner for MULTI_STEP |
| Modify | `wiki/pipeline_nodes.py` | Integrate select_reasoning_level into compose/heal/classify/overview |
| Modify | `config.py:177-183` | Replace `cot_*` fields with `reasoning_effort` |
| Modify | `services/service_registry.py:192-194` | Update /health endpoint |
| Delete | `wiki/cot_generator.py` | Replaced by reasoning.py |
| Delete | `tests/wiki/test_cot_generator.py` | Tests for deleted module |
| Modify | `dashboard/src/components/settings/sections/WikiGenerationSection.tsx:93-108` | Remove CoT config UI |
| Modify | `dashboard/src/api/types.ts:205-207` | Remove cot_* types |
| Modify | `dashboard/src/components/settings/systemConfigConstants.ts:41-43,123` | Remove cot_* constants |
| Modify | `dashboard/src/components/settings/configFieldLabels.ts:33` | Remove cot_* label |
| Modify | `dashboard/src/pages/panels/GeneralSettingsPanel.tsx:122-144` | Remove CoT display |

---

### Task 1: Create `wiki/reasoning.py` — Core Module

**Files:**
- Create: `wiki/reasoning.py`
- Create: `tests/wiki/test_reasoning.py`

- [ ] **Step 1: Write test for select_reasoning_level**

```python
# tests/wiki/test_reasoning.py
"""Tests for adaptive reasoning level selection and enhancement."""
from __future__ import annotations

import pytest

from wiki.domain_complexity import DomainComplexity
from wiki.reasoning import (
    GuidedPromptEnhancer,
    ReasoningLevel,
    TaskType,
    select_reasoning_level,
)


class TestSelectReasoningLevel:
    def test_compose_low_returns_none(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.LOW) == ReasoningLevel.NONE

    def test_compose_medium_returns_guided(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.MEDIUM) == ReasoningLevel.GUIDED

    def test_compose_high_returns_multi_step(self):
        assert select_reasoning_level(TaskType.COMPOSE, DomainComplexity.HIGH) == ReasoningLevel.MULTI_STEP

    def test_classify_high_returns_guided(self):
        assert select_reasoning_level(TaskType.CLASSIFY, DomainComplexity.HIGH) == ReasoningLevel.GUIDED

    def test_heal_low_returns_guided(self):
        assert select_reasoning_level(TaskType.HEAL, DomainComplexity.LOW) == ReasoningLevel.GUIDED

    def test_heal_medium_returns_multi_step(self):
        assert select_reasoning_level(TaskType.HEAL, DomainComplexity.MEDIUM) == ReasoningLevel.MULTI_STEP

    def test_overview_low_returns_guided(self):
        assert select_reasoning_level(TaskType.OVERVIEW, DomainComplexity.LOW) == ReasoningLevel.GUIDED

    def test_overview_high_returns_multi_step(self):
        assert select_reasoning_level(TaskType.OVERVIEW, DomainComplexity.HIGH) == ReasoningLevel.MULTI_STEP
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py -x -v --no-cov`
Expected: FAIL with ImportError (module doesn't exist yet)

- [ ] **Step 3: Implement ReasoningLevel, TaskType, select_reasoning_level**

```python
# wiki/reasoning.py
"""Adaptive reasoning level selection and multi-step reasoning execution."""
from __future__ import annotations

from enum import Enum
from typing import Any

from log import get_logger
from wiki.domain_complexity import DomainComplexity

log = get_logger(__name__)


class ReasoningLevel(str, Enum):
    NONE = "none"
    GUIDED = "guided"
    MULTI_STEP = "multi_step"


class TaskType(str, Enum):
    CLASSIFY = "classify"
    COMPOSE = "compose"
    HEAL = "heal"
    OVERVIEW = "overview"


_DEFAULT_STRATEGY: dict[TaskType, dict[DomainComplexity, ReasoningLevel]] = {
    TaskType.CLASSIFY: {
        DomainComplexity.LOW: ReasoningLevel.NONE,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.GUIDED,
    },
    TaskType.COMPOSE: {
        DomainComplexity.LOW: ReasoningLevel.NONE,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
    TaskType.HEAL: {
        DomainComplexity.LOW: ReasoningLevel.GUIDED,
        DomainComplexity.MEDIUM: ReasoningLevel.MULTI_STEP,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
    TaskType.OVERVIEW: {
        DomainComplexity.LOW: ReasoningLevel.GUIDED,
        DomainComplexity.MEDIUM: ReasoningLevel.GUIDED,
        DomainComplexity.HIGH: ReasoningLevel.MULTI_STEP,
    },
}


def select_reasoning_level(
    task_type: TaskType,
    complexity: DomainComplexity,
) -> ReasoningLevel:
    """Select reasoning level based on task type and domain complexity."""
    return _DEFAULT_STRATEGY[task_type][complexity]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py::TestSelectReasoningLevel -x -v --no-cov`
Expected: 8 PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/reasoning.py tests/wiki/test_reasoning.py
git commit -m "feat(wiki): add ReasoningLevel enum and select_reasoning_level"
```

---

### Task 2: Implement GuidedPromptEnhancer

**Files:**
- Modify: `wiki/reasoning.py`
- Modify: `tests/wiki/test_reasoning.py`

- [ ] **Step 1: Write tests for GuidedPromptEnhancer**

```python
# Append to tests/wiki/test_reasoning.py

class TestGuidedPromptEnhancer:
    def setup_method(self):
        self.enhancer = GuidedPromptEnhancer()

    def test_enhance_classify_prepends_analysis(self):
        original = "Classify these modules into domains."
        result = self.enhancer.enhance_classify_prompt(original)
        assert "Before classifying, analyze:" in result
        assert result.endswith(original)

    def test_enhance_overview_prepends_analysis(self):
        original = "Generate overview for domain X."
        result = self.enhancer.enhance_overview_prompt(original)
        assert "Before writing the overview, analyze:" in result
        assert result.endswith(original)

    def test_enhance_heal_prepends_diagnostic(self):
        original = "Improve this wiki page."
        result = self.enhancer.enhance_heal_prompt(original)
        assert "Before rewriting, analyze:" in result
        assert result.endswith(original)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py::TestGuidedPromptEnhancer -x -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Implement GuidedPromptEnhancer in wiki/reasoning.py**

Append to `wiki/reasoning.py`:

```python
class GuidedPromptEnhancer:
    """Inject structured reasoning guidance into prompts for GUIDED level.

    Scope: classify, overview, and heal prompts.
    compose GUIDED is handled by TopicPageComposer's built-in prompts.
    """

    def enhance_classify_prompt(self, prompt: str) -> str:
        guidance = (
            "Before classifying, analyze:\n"
            "1. Which modules share data models or call each other?\n"
            "2. Which modules serve the same business process?\n"
            "3. Are there modules that seem unrelated but share a common entry point?\n\n"
        )
        return guidance + prompt

    def enhance_overview_prompt(self, prompt: str) -> str:
        guidance = (
            "Before writing the overview, analyze:\n"
            "1. What are the primary business flows across domains?\n"
            "2. Which domains are tightly coupled vs loosely coupled?\n"
            "3. What is the overall system's value proposition?\n\n"
        )
        return guidance + prompt

    def enhance_heal_prompt(self, prompt: str) -> str:
        guidance = (
            "Before rewriting, analyze:\n"
            "1. What specific quality issues does this page have?\n"
            "2. Which sections are adequate and should be preserved in spirit?\n"
            "3. What missing information would most improve this page?\n\n"
        )
        return guidance + prompt
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py -x -v --no-cov`
Expected: 11 PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/reasoning.py tests/wiki/test_reasoning.py
git commit -m "feat(wiki): add GuidedPromptEnhancer for classify/overview/heal"
```

---

### Task 3: Implement MultiStepReasoner

**Files:**
- Modify: `wiki/reasoning.py`
- Modify: `tests/wiki/test_reasoning.py`

- [ ] **Step 1: Write tests for MultiStepReasoner**

```python
# Append to tests/wiki/test_reasoning.py
import json
from unittest.mock import AsyncMock

from wiki.reasoning import MultiStepReasoner


class TestMultiStepReasoner:
    def setup_method(self):
        self.reasoner = MultiStepReasoner()

    @pytest.mark.asyncio
    async def test_plan_and_compose_makes_two_llm_calls(self):
        llm = AsyncMock()
        plan_json = json.dumps({
            "sections": [
                {"heading": "业务概述", "key_points": ["order processing"]},
                {"heading": "核心流程", "key_points": ["create→pay→ship"]},
            ],
            "diagrams": ["sequenceDiagram showing order flow"],
        })
        llm.generate = AsyncMock(side_effect=[plan_json, "# Order Domain\n\n## 业务概述\nContent..."])
        domain = {"name": "order", "biz_entities": [{"name": "OrderService", "summary": "handles orders", "methods": ["create"], "calls": []}]}

        result = await self.reasoner.plan_and_compose(domain, llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert "Order Domain" in result or "order" in result.lower()

    @pytest.mark.asyncio
    async def test_plan_and_compose_fallback_on_bad_plan(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=["not valid json", "# Fallback Content\nGenerated"])
        domain = {"name": "order", "biz_entities": []}

        result = await self.reasoner.plan_and_compose(domain, llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert "Fallback" in result or len(result) > 0

    @pytest.mark.asyncio
    async def test_plan_and_overview_makes_two_llm_calls(self):
        llm = AsyncMock()
        llm.generate = AsyncMock(side_effect=["Domain A handles payments. Domain B handles orders.", "# System Overview\n..."])
        result = await self.reasoner.plan_and_overview("summary", llm, system="test", max_tokens=4000)

        assert llm.generate.call_count == 2
        assert len(result) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py::TestMultiStepReasoner -x -v --no-cov`
Expected: FAIL

- [ ] **Step 3: Implement MultiStepReasoner**

Append to `wiki/reasoning.py`:

```python
class MultiStepReasoner:
    """Execute multi-step reasoning for MULTI_STEP level."""

    _PLAN_SYSTEM = (
        "You are a technical documentation architect. "
        "Plan the structure of a wiki page. "
        "Output ONLY valid JSON. No markdown fences."
    )

    _ANALYSIS_SYSTEM = (
        "You are a senior architect analyzing cross-domain relationships. "
        "Provide a concise analysis of how domains interact."
    )

    async def plan_and_compose(
        self,
        domain: dict[str, Any],
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        """Step 1: Plan page structure → Step 2: Generate content from plan."""
        plan = await self._plan_structure(domain, llm, reasoning_effort=reasoning_effort)
        content = await self._generate_from_plan(
            domain, plan, llm,
            system=system, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def plan_and_overview(
        self,
        domains_summary: str,
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        """Step 1: Cross-domain analysis → Step 2: Generate overview."""
        analysis = await self._analyze_domains(
            domains_summary, llm, reasoning_effort=reasoning_effort,
        )
        content = await self._generate_overview(
            domains_summary, analysis, llm,
            system=system, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def _plan_structure(
        self, domain: dict[str, Any], llm: Any, **kw: Any,
    ) -> dict[str, Any]:
        name = domain.get("name", "unknown")
        entities = domain.get("biz_entities", [])
        entity_desc = "\n".join(
            f"- {e.get('name', '')}: {e.get('summary', '')} "
            f"(methods: {', '.join(e.get('methods', [])[:8])}; "
            f"calls: {', '.join(e.get('calls', [])[:5])})"
            for e in entities
        )
        prompt = (
            f"Plan the wiki page structure for domain: **{name}**\n\n"
            f"Services:\n{entity_desc}\n\n"
            "Return JSON:\n"
            '{"sections": [{"heading": "## Section Title", "key_points": ["point1", "point2"]}], '
            '"diagrams": ["description of each Mermaid diagram needed"]}\n\n'
            "Rules:\n"
            "- 3-6 sections covering: business overview (WHY), core flow, key services, interactions\n"
            "- At least 1 diagram (sequenceDiagram or flowchart)\n"
            "- Section headings in Chinese"
        )
        gen_kw: dict[str, Any] = {}
        if kw.get("reasoning_effort"):
            gen_kw["reasoning_effort"] = kw["reasoning_effort"]
        raw = await llm.generate(prompt, system=self._PLAN_SYSTEM, **gen_kw)
        try:
            import json
            plan = json.loads(raw.strip().removeprefix("```json").removesuffix("```").strip())
            if isinstance(plan, dict) and "sections" in plan:
                return plan
        except (json.JSONDecodeError, ValueError):
            log.warning("multi_step_plan_parse_failed", domain=name)
        return {"sections": [], "diagrams": []}

    async def _generate_from_plan(
        self,
        domain: dict[str, Any],
        plan: dict[str, Any],
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        name = domain.get("name", "unknown")
        entities = domain.get("biz_entities", [])
        entity_desc = "\n".join(
            f"- {e.get('name', '')}: {e.get('summary', '')}"
            for e in entities
        )

        sections = plan.get("sections", [])
        diagrams = plan.get("diagrams", [])
        if sections:
            import json
            plan_text = f"Planned structure:\n{json.dumps(sections, ensure_ascii=False, indent=2)}"
            diagram_text = f"\nPlanned diagrams:\n" + "\n".join(f"- {d}" for d in diagrams) if diagrams else ""
        else:
            plan_text = ""
            diagram_text = ""

        prompt = (
            f"Write a wiki page for domain: **{name}**\n\n"
            f"Services:\n{entity_desc}\n\n"
            f"{plan_text}{diagram_text}\n\n"
            "Follow the planned structure above. Write each section with depth and business insight.\n"
            "Use Chinese for section headings and business descriptions.\n"
            "Include Mermaid diagrams as planned.\n"
            f"Keep response under {max_tokens} tokens."
        )
        gen_kw: dict[str, Any] = {}
        if reasoning_effort:
            gen_kw["reasoning_effort"] = reasoning_effort
        return await llm.generate(prompt, system=system, max_tokens=max_tokens, **gen_kw)

    async def _analyze_domains(
        self, summary: str, llm: Any, **kw: Any,
    ) -> str:
        prompt = (
            "Analyze the following domain summaries and describe:\n"
            "1. How these domains interact with each other\n"
            "2. Which domains are tightly coupled\n"
            "3. What is the overall system's architecture pattern\n\n"
            f"Domain summaries:\n{summary}"
        )
        gen_kw: dict[str, Any] = {}
        if kw.get("reasoning_effort"):
            gen_kw["reasoning_effort"] = kw["reasoning_effort"]
        return await llm.generate(prompt, system=self._ANALYSIS_SYSTEM, **gen_kw)

    async def _generate_overview(
        self,
        summary: str,
        analysis: str,
        llm: Any,
        *,
        system: str = "",
        max_tokens: int = 8000,
        reasoning_effort: str | None = None,
    ) -> str:
        prompt = (
            "Generate a system architecture overview based on this analysis:\n\n"
            f"Analysis:\n{analysis}\n\n"
            f"Domain details:\n{summary}\n\n"
            "Include a Mermaid architecture diagram showing domain relationships.\n"
            f"Keep response under {max_tokens} tokens."
        )
        gen_kw: dict[str, Any] = {}
        if reasoning_effort:
            gen_kw["reasoning_effort"] = reasoning_effort
        return await llm.generate(prompt, system=system, max_tokens=max_tokens, **gen_kw)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_reasoning.py -x -v --no-cov`
Expected: 14 PASSED

- [ ] **Step 5: Commit**

```bash
git add wiki/reasoning.py tests/wiki/test_reasoning.py
git commit -m "feat(wiki): add MultiStepReasoner for plan-then-generate flow"
```

---

### Task 4: Extend LLMPort with reasoning_effort

**Files:**
- Modify: `wiki/context.py:24-32`

- [ ] **Step 1: Add reasoning_effort to LLMPort Protocol**

In `wiki/context.py`, modify the `LLMPort` Protocol class to add `reasoning_effort`:

```python
class LLMPort(Protocol):
    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,
    ) -> str: ...
```

- [ ] **Step 2: Run existing tests to verify no regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/ -x -q --no-cov 2>&1 | tail -5`
Expected: All pass (Protocol change is backward compatible since `reasoning_effort` has default `None`)

- [ ] **Step 3: Commit**

```bash
git add wiki/context.py
git commit -m "feat(wiki): extend LLMPort Protocol with reasoning_effort parameter"
```

---

### Task 5: Integrate into TopicPageComposer

**Files:**
- Modify: `wiki/topic_page_composer.py`

- [ ] **Step 1: Add reasoning_level parameter to TopicPageComposer**

Modify `TopicPageComposer.__init__` to accept `reasoning_level`:

```python
def __init__(
    self,
    llm: LLMPort,
    *,
    token_budget: int = 8000,
    complexity_scorer: DomainComplexityScorer | None = None,
    reasoning_level: ReasoningLevel | None = None,
) -> None:
    self._llm = llm
    self._token_budget = token_budget
    self._complexity_scorer = complexity_scorer or DomainComplexityScorer()
    self._reasoning_level = reasoning_level
```

Add import at top:
```python
from wiki.reasoning import MultiStepReasoner, ReasoningLevel
```

- [ ] **Step 2: Use MultiStepReasoner in _compose_single_page for MULTI_STEP**

In `_compose_single_page`, add MULTI_STEP branch before the existing `llm.generate` call:

```python
async def _compose_single_page(self, domain: dict[str, Any], complexity: DomainComplexity) -> list[dict[str, Any]]:
    name = domain["name"]
    concise = complexity == DomainComplexity.LOW
    budget = self._effective_token_budget(complexity)

    if self._reasoning_level == ReasoningLevel.MULTI_STEP and not concise:
        reasoner = MultiStepReasoner()
        content = await reasoner.plan_and_compose(
            domain, self._llm, system=SYSTEM_WIKI_AUTHOR, max_tokens=budget,
        )
    else:
        prompt = self._build_single_page_prompt(domain, concise=concise)
        content = await self._llm.generate(prompt, system=SYSTEM_WIKI_AUTHOR, max_tokens=budget)

    data_table = self.format_data_model_table(domain.get("data_models", []))
    if data_table and "## 数据模型" not in content:
        content += f"\n\n## 数据模型\n{data_table}"

    return [{"title": name, "content": content, "path": f"wiki/{name}", "page_type": "topic", "domain": name}]
```

- [ ] **Step 3: Run existing TopicPageComposer tests**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/test_topic_page_composer.py tests/wiki/test_compose_pages_node.py -x -v --no-cov`
Expected: All PASS (existing tests don't pass reasoning_level, so behavior unchanged)

- [ ] **Step 4: Commit**

```bash
git add wiki/topic_page_composer.py
git commit -m "feat(wiki): integrate MultiStepReasoner into TopicPageComposer"
```

---

### Task 6: Integrate into pipeline_nodes.py

**Files:**
- Modify: `wiki/pipeline_nodes.py`

- [ ] **Step 1: Integrate select_reasoning_level into compose_pages_node**

In `_compose_single_leaf_domain` (around line 580-600), where `TopicPageComposer` is instantiated, pass the reasoning level:

```python
from wiki.reasoning import select_reasoning_level, TaskType, ReasoningLevel, GuidedPromptEnhancer

# In _compose_single_leaf_domain, after scoring complexity:
level = select_reasoning_level(TaskType.COMPOSE, metrics.complexity)
composer = TopicPageComposer(llm, token_budget=budget, reasoning_level=level)
```

- [ ] **Step 2: Integrate into classify_domains_node**

In `classify_domains_node`, use `GuidedPromptEnhancer` when domain count suggests MEDIUM+ complexity:

```python
# In classify_domains_node, before calling planner.classify():
enhancer = GuidedPromptEnhancer()
# Pass enhancer to planner or enhance the prompt within the planner call
```

Note: The exact integration point depends on how `CrossRepoBusinessDomainPlanner.classify()` constructs its prompts. Read the planner code to find the right injection point. The enhancer should prepend analysis guidance to the classification prompt when the module count exceeds the LOW threshold (~10 modules).

- [ ] **Step 3: Integrate into heal_pages_node**

In `heal_pages_node`, use reasoning level to decide between GUIDED heal (enhanced prompt) and MULTI_STEP heal (TargetedHealer):

```python
# For each page being healed:
# Determine complexity (use domain context or page length as proxy)
# GUIDED: Use GuidedPromptEnhancer.enhance_heal_prompt() on the full-regen prompt
# MULTI_STEP: Use TargetedHealer (existing behavior, already integrated)
```

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/ -x -q --no-cov 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add wiki/pipeline_nodes.py
git commit -m "feat(wiki): integrate adaptive reasoning into pipeline nodes"
```

---

### Task 7: Delete cot_generator and clean up config

**Files:**
- Delete: `wiki/cot_generator.py`
- Delete: `tests/wiki/test_cot_generator.py`
- Modify: `config.py:177-183`
- Modify: `services/service_registry.py:192-194`

- [ ] **Step 1: Delete cot_generator.py and its test**

```bash
rm wiki/cot_generator.py tests/wiki/test_cot_generator.py
```

- [ ] **Step 2: Replace cot_* config fields with reasoning_effort**

In `config.py`, replace the three `cot_*` fields in `AppWikiFlags`:

```python
# Remove:
#     cot_enabled: bool = False
#     cot_analysis_model: str = ""
#     cot_generation_model: str = ""
# Add:
    reasoning_effort: str | None = None
```

- [ ] **Step 3: Update /health endpoint in service_registry.py**

In `services/service_registry.py:192-194`, replace:

```python
# Remove:
#     "cot_enabled": bool(wiki_cfg.cot_enabled),
#     "cot_analysis_model": wiki_cfg.cot_analysis_model or "",
#     "cot_generation_model": wiki_cfg.cot_generation_model or "",
# Add:
    "reasoning_effort": wiki_cfg.reasoning_effort or "auto",
```

- [ ] **Step 4: Run tests to verify no imports break**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/ tests/services/ -x -q --no-cov 2>&1 | tail -5`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(wiki): delete cot_generator.py, replace cot_* config with reasoning_effort"
```

---

### Task 8: Clean up Dashboard CoT UI

**Files:**
- Modify: `dashboard/src/components/settings/sections/WikiGenerationSection.tsx:93-108`
- Modify: `dashboard/src/api/types.ts:205-207`
- Modify: `dashboard/src/components/settings/systemConfigConstants.ts:41-43,123`
- Modify: `dashboard/src/components/settings/configFieldLabels.ts:33`
- Modify: `dashboard/src/pages/panels/GeneralSettingsPanel.tsx:122-144`

- [ ] **Step 1: Remove cot_* from types.ts**

In `dashboard/src/api/types.ts`, remove lines 205-207:
```typescript
// Remove these three fields from the wiki health type:
//   cot_enabled: boolean;
//   cot_analysis_model: string;
//   cot_generation_model: string;
```

- [ ] **Step 2: Remove CoT config UI from WikiGenerationSection.tsx**

In `dashboard/src/components/settings/sections/WikiGenerationSection.tsx`, remove the three form fields at lines 93-108 (the `ToggleField` for `cot_enabled` and two `TextField`s for `cot_analysis_model`/`cot_generation_model`).

- [ ] **Step 3: Remove cot_* from systemConfigConstants.ts**

In `dashboard/src/components/settings/systemConfigConstants.ts`, remove `"wiki.cot_enabled"`, `"wiki.cot_analysis_model"`, `"wiki.cot_generation_model"` from the config key arrays.

- [ ] **Step 4: Remove cot_* from configFieldLabels.ts**

Remove the `"wiki.cot_enabled": "fieldCotEnabled"` entry.

- [ ] **Step 5: Remove CoT display from GeneralSettingsPanel.tsx**

In `dashboard/src/pages/panels/GeneralSettingsPanel.tsx`, remove the CoT section (lines ~122-144) that displays `health.wiki.cot_enabled`, `cot_analysis_model`, `cot_generation_model`.

- [ ] **Step 6: Run frontend type check**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm run typecheck`
Expected: No type errors

- [ ] **Step 7: Commit**

```bash
git add -A
git commit -m "chore(dashboard): remove dead CoT config UI"
```

---

### Task 9: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run full backend test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && uv run python -m pytest tests/wiki/ -x -q --no-cov 2>&1 | tail -10`
Expected: All pass, including new test_reasoning.py tests

- [ ] **Step 2: Run frontend tests and type check**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service/dashboard && pnpm run typecheck && pnpm run test 2>&1 | tail -10`
Expected: No type errors, all tests pass

- [ ] **Step 3: Verify no remaining cot_* references in production code**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && rg "cot_enabled|cot_generator|CoTWikiGenerator|cot_analysis_model|cot_generation_model" --type py --type ts --type tsx -l`
Expected: Only references in docs/ (proposals, analysis) — no production code references

- [ ] **Step 4: Update DEEP_ANALYSIS doc**

Update `docs/superpowers/DEEP_ANALYSIS_20260501_085742_wiki_gaps_and_bugs.md`:
- Mark T1 (CoT reasoning) as completed
- Mark T2 (adaptive reasoning depth) as completed
- Mark A4 (CoT not integrated) as completed
- Update Phase 2 status to completed
