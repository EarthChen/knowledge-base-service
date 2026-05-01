# Design Spec: Phase 2 — Adaptive Reasoning (CoT & Self-Adaptive Inference)

> **Status**: Draft  
> **Created**: 2026-05-01  
> **Approach**: 方案 A — 3 级 ReasoningLevel + reasoning_effort 正交维度  
> **Source**: `DEEP_ANALYSIS` Phase 2, `PROPOSAL_20260501_011112_adaptive_cot_pipeline.md`

---

## 1. Problem Statement

Current wiki generation uses a fixed single-shot prompt strategy for all tasks regardless of complexity. The existing `cot_generator.py` implements a two-step CoT flow but is **unused** by the LangGraph pipeline (`cot_enabled=False`, no imports from pipeline nodes).

**Result**: HIGH complexity domains get the same shallow reasoning as LOW domains, producing "API listing" content instead of insightful architecture documentation.

## 2. Design Goals

1. **Automatic reasoning depth selection** based on domain complexity — no user intervention needed
2. **Replace** `cot_generator.py` with a unified `wiki/reasoning.py` module
3. **Extend LLMPort** with `reasoning_effort` for LLM-native thinking (orthogonal to reasoning level)
4. **Clean up** all dead `cot_*` config, UI, and code

## 3. Architecture

### 3.1 ReasoningLevel Enum (3 values)

```python
class ReasoningLevel(str, Enum):
    NONE = "none"
    GUIDED = "guided"
    MULTI_STEP = "multi_step"
```

| Level | Behavior | LLM Calls | Token Cost |
|-------|----------|-----------|------------|
| NONE | Direct prompt, single call | 1 | Baseline |
| GUIDED | Single call, prompt includes structured reasoning steps ("Before writing, analyze: ...") | 1 | ~1.1x |
| MULTI_STEP | Multiple calls: Step 1 analyze/plan → Step 2 generate from analysis | 2+ | ~2x |

### 3.2 TaskType Enum

```python
class TaskType(str, Enum):
    CLASSIFY = "classify"
    COMPOSE = "compose"
    HEAL = "heal"
    OVERVIEW = "overview"
```

### 3.3 Default Strategy Table

| Task | LOW | MEDIUM | HIGH | Rationale |
|------|-----|--------|------|-----------|
| classify | NONE | GUIDED | GUIDED | Classification is JSON output; GUIDED ceiling is sufficient |
| compose | NONE | GUIDED | MULTI_STEP | HIGH domains need structural planning before writing |
| heal | GUIDED | MULTI_STEP | MULTI_STEP | Always at least guide; MEDIUM+ use TargetedHealer pattern |
| overview | GUIDED | GUIDED | MULTI_STEP | Overview always needs structure; HIGH needs cross-domain analysis |

**This table is internal-only.** Users cannot configure it. Complexity is auto-detected via `DomainComplexityScorer`.

### 3.4 reasoning_effort (Orthogonal Dimension)

`reasoning_effort` is a separate LLM-level parameter that controls the provider's native thinking capability:

```python
class LLMPort(Protocol):
    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        reasoning_effort: str | None = None,  # NEW: 'low'|'medium'|'high'|None
    ) -> str: ...
```

- Can be combined with ANY ReasoningLevel
- Provider adapter maps to specific parameters (Claude → thinking_budget, GPT → reasoning_effort)
- When provider doesn't support it, silently ignored
- Configured globally via `AppWikiFlags.reasoning_effort` (config file/env var only, no Dashboard UI)

## 4. Module Design

### 4.1 New: `wiki/reasoning.py`

```python
"""Adaptive reasoning level selection and multi-step reasoning execution."""
from __future__ import annotations

from enum import Enum
from typing import Any

from wiki.domain_complexity import DomainComplexity


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


class GuidedPromptEnhancer:
    """Inject structured reasoning guidance into prompts for GUIDED level.

    Scope: classify, overview, and heal prompts only.
    compose GUIDED is handled by TopicPageComposer's built-in "Before writing, analyze..." prompts.
    """

    def enhance_classify_prompt(self, prompt: str) -> str:
        """Add dependency analysis step before classification."""
        guidance = (
            "Before classifying, analyze:\n"
            "1. Which modules share data models or call each other?\n"
            "2. Which modules serve the same business process?\n"
            "3. Are there modules that seem unrelated but share a common entry point?\n\n"
        )
        return guidance + prompt

    def enhance_overview_prompt(self, prompt: str) -> str:
        """Add cross-domain analysis step before overview generation."""
        guidance = (
            "Before writing the overview, analyze:\n"
            "1. What are the primary business flows across domains?\n"
            "2. Which domains are tightly coupled vs loosely coupled?\n"
            "3. What is the overall system's value proposition?\n\n"
        )
        return guidance + prompt

    def enhance_heal_prompt(self, prompt: str) -> str:
        """Add diagnostic analysis step before heal (for LOW complexity GUIDED mode)."""
        guidance = (
            "Before rewriting, analyze:\n"
            "1. What specific quality issues does this page have?\n"
            "2. Which sections are adequate and should be preserved in spirit?\n"
            "3. What missing information would most improve this page?\n\n"
        )
        return guidance + prompt


class MultiStepReasoner:
    """Execute multi-step reasoning for MULTI_STEP level."""

    _PLAN_SYSTEM = (
        "You are a technical documentation architect. "
        "Output ONLY valid JSON. No markdown fences."
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
            system=system,
            max_tokens=max_tokens,
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
        analysis = await self._analyze_domains(domains_summary, llm, reasoning_effort=reasoning_effort)
        content = await self._generate_overview(
            domains_summary, analysis, llm,
            system=system, max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
        )
        return content

    async def _plan_structure(self, domain: dict, llm: Any, **kw) -> dict:
        """Ask LLM to plan page structure before writing."""
        # Returns: {"sections": [...], "diagrams": [...], "key_flows": [...]}
        ...

    async def _generate_from_plan(self, domain: dict, plan: dict, llm: Any, **kw) -> str:
        """Generate full content based on structural plan."""
        ...

    async def _analyze_domains(self, summary: str, llm: Any, **kw) -> str:
        """Cross-domain relationship analysis."""
        ...

    async def _generate_overview(self, summary: str, analysis: str, llm: Any, **kw) -> str:
        """Generate overview from analysis."""
        ...
```

### 4.2 Modify: `wiki/context.py`

Add `reasoning_effort: str | None = None` to `LLMPort.generate` Protocol.

### 4.3 Modify: `wiki/pipeline_nodes.py`

**compose_pages_node** — in `_compose_single_leaf_domain`:
```python
level = select_reasoning_level(TaskType.COMPOSE, complexity)
composer = TopicPageComposer(llm, token_budget=budget, reasoning_level=level)
pages = await composer.compose_leaf_domain(domain)
# TopicPageComposer internally routes: NONE→direct, GUIDED→existing prompts, MULTI_STEP→MultiStepReasoner
```

**heal_pages_node**: Already uses TargetedHealer (which is MULTI_STEP). For GUIDED mode (LOW complexity), skip TargetedHealer and use enhanced prompt for full regen.

**classify_domains_node**: For GUIDED, use `GuidedPromptEnhancer.enhance_classify_prompt()`.

**synthesize_overviews_node**: For MULTI_STEP, use `MultiStepReasoner.plan_and_overview()`.

### 4.4 Modify: `config.py`

```python
class AppWikiFlags:
    # DELETE: cot_enabled, cot_analysis_model, cot_generation_model
    reasoning_effort: str | None = None  # 'low'|'medium'|'high'|None
```

### 4.5 Delete

| File | Reason |
|------|--------|
| `wiki/cot_generator.py` | Replaced by `wiki/reasoning.py` |
| `tests/wiki/test_cot_generator.py` | Tests for deleted module |
| Dashboard CoT config UI elements | Dead code after config removal |
| `cot_enabled`/`cot_*_model` in config | Replaced by `reasoning_effort` |

## 5. Integration with Existing Code

### 5.1 TopicPageComposer Integration (IMPORTANT)

`MultiStepReasoner` is integrated **inside** `TopicPageComposer`, NOT as a parallel alternative. TopicPageComposer retains ownership of split/grouped structure decisions.

- NONE: `compose_leaf_domain()` → `concise=True` for LOW complexity (unchanged)
- GUIDED: `compose_leaf_domain()` → existing "Before writing, analyze..." prompts (unchanged)
- MULTI_STEP: `compose_leaf_domain()` → internally uses `MultiStepReasoner.plan_and_compose()` for **single page content generation**, while TopicPageComposer still manages split/grouped page structure

TopicPageComposer constructor accepts optional `reasoning_level: ReasoningLevel | None = None`. When MULTI_STEP, `_compose_single_page` / sub-page generation calls use `MultiStepReasoner` instead of direct `llm.generate()`.

### 5.2 TargetedHealer Integration

- TargetedHealer is inherently MULTI_STEP (diagnose → patch)
- For heal ReasoningLevel.GUIDED: Use enhanced heal prompt (full regen with reasoning guidance)
- For heal ReasoningLevel.MULTI_STEP: Use TargetedHealer (existing behavior for MEDIUM/HIGH)

### 5.3 DomainComplexityScorer

No changes needed. Existing `raw_score` formula and LOW/MEDIUM/HIGH thresholds (10/30) drive ReasoningLevel selection automatically.

## 6. Testing Plan

- [ ] `test_reasoning.py`: `select_reasoning_level` returns correct level for all task×complexity combinations
- [ ] `test_reasoning.py`: `GuidedPromptEnhancer` injects guidance text
- [ ] `test_reasoning.py`: `MultiStepReasoner.plan_and_compose` performs 2 LLM calls
- [ ] `test_reasoning.py`: `MultiStepReasoner` fallback on plan parse failure
- [ ] `test_pipeline_e2e.py`: Pipeline with MULTI_STEP compose produces valid pages
- [ ] `test_pipeline_e2e.py`: Pipeline with GUIDED classify includes analysis prompt
- [ ] Existing tests remain green (NONE path unchanged)

## 7. Success Criteria

- [ ] HIGH complexity domains produce structurally richer wiki pages (plan → content)
- [ ] Strategy selection is fully automatic (no user config needed)
- [ ] All dead `cot_*` code removed
- [ ] LLMPort extended with `reasoning_effort` (backward compatible via `None` default)
- [ ] Existing tests pass with no regressions
- [ ] New tests cover all 3 reasoning levels
