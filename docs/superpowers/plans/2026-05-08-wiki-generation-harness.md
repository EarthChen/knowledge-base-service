# Wiki Generation Harness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a WikiGenerationHarness that wraps the existing WikiPageAgent with Plan-Gather-Distill-Generate-Evaluate-Repair pipeline, reducing token consumption by 30-60% while improving quality through adaptive routing, structured context management, and in-loop evaluation.

**Architecture:** Hybrid Harness wrapping existing Agent — new orchestrator layer (WikiGenerationHarness) coordinates Planner (deterministic), existing WikiPageAgent (as Generator), and Evaluator (deterministic L1 + optional LLM L2). Uses tiered context budgets based on domain complexity assessment.

**Tech Stack:** Python 3.11, pytest, asyncio, dataclasses, FalkorDB Cypher queries

**Spec:** `docs/superpowers/specs/2026-05-08-wiki-generation-harness-design.md`

---

## File Structure

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `wiki/harness_router.py` | AdaptiveRouter: complexity assessment + tiered budgets |
| Create | `wiki/harness_facts.py` | GatheredFacts + CONTEXT_BUDGETS + distill logic |
| Create | `wiki/harness_planner.py` | WikiPagePlanner: deterministic query planning |
| Create | `wiki/harness_evaluator.py` | WikiPageEvaluator: L1 deterministic + L2 LLM |
| Create | `wiki/harness_guardrails.py` | GuardRails: duplicate detection, length checks |
| Create | `wiki/domain_summary_cache.py` | DomainSummaryCard: cross-domain memory |
| Create | `wiki/harness.py` | WikiGenerationHarness: orchestrator |
| Modify | `wiki/page_agent.py` | Add repair() method |
| Modify | `wiki/nodes/compose.py` | Integrate Harness + fix repo_path bug |
| Modify | `wiki/agent_config.py` | Add HarnessConfig |
| Create | `tests/wiki/test_harness_router.py` | Router unit tests |
| Create | `tests/wiki/test_harness_facts.py` | Facts + Distill unit tests |
| Create | `tests/wiki/test_harness_planner.py` | Planner unit tests |
| Create | `tests/wiki/test_harness_evaluator.py` | Evaluator unit tests |
| Create | `tests/wiki/test_harness_guardrails.py` | GuardRails unit tests |
| Create | `tests/wiki/test_domain_summary_cache.py` | DomainSummaryCard tests |
| Create | `tests/wiki/test_harness_integration.py` | Integration tests |

---

### Task 1: AdaptiveRouter — Complexity Assessment

**Files:**
- Create: `wiki/harness_router.py`
- Test: `tests/wiki/test_harness_router.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_router.py`:

```python
"""Tests for AdaptiveRouter complexity assessment."""
import pytest
from dataclasses import dataclass, field


@dataclass
class _FakeCCBContext:
    cross_domain_calls: list = field(default_factory=list)
    module_summaries: list = field(default_factory=list)


class TestAdaptiveRouter:
    def test_simple_domain_few_modules(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter()
        ctx = _FakeCCBContext(cross_domain_calls=[], module_summaries=[])
        result = router.assess(["ModA", "ModB", "ModC"], ctx)
        assert result.level == "simple"
        assert result.max_tool_calls == 5
        assert result.generation_mode == "whole_page"
        assert result.max_repair_rounds == 0
        assert result.use_llm_judge is False

    def test_moderate_domain_mid_modules(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter()
        ctx = _FakeCCBContext(
            cross_domain_calls=[{"src": "A", "dst": "B"}] * 8,
            module_summaries=[{"methods": ["m1", "m2"]}] * 10,
        )
        modules = [f"Mod{i}" for i in range(10)]
        result = router.assess(modules, ctx)
        assert result.level == "moderate"
        assert result.max_tool_calls == 10
        assert result.generation_mode == "whole_page"
        assert result.max_repair_rounds == 1

    def test_complex_domain_many_modules(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter()
        ctx = _FakeCCBContext(
            cross_domain_calls=[{"src": "A", "dst": "B"}] * 25,
            module_summaries=[{"methods": ["m1"]}] * 20,
        )
        modules = [f"Mod{i}" for i in range(20)]
        result = router.assess(modules, ctx)
        assert result.level == "complex"
        assert result.max_tool_calls == 15
        assert result.generation_mode == "sectional"
        assert result.max_repair_rounds == 2
        assert result.use_llm_judge is True

    def test_high_edge_density_forces_complex(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter()
        ctx = _FakeCCBContext(
            cross_domain_calls=[{"src": "A", "dst": "B"}] * 25,
            module_summaries=[],
        )
        modules = [f"Mod{i}" for i in range(8)]  # moderate count but high edges
        result = router.assess(modules, ctx)
        assert result.level == "complex"

    def test_none_context_defaults_simple(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter()
        result = router.assess(["ModA", "ModB"], None)
        assert result.level == "simple"

    def test_custom_thresholds(self):
        from wiki.harness_router import AdaptiveRouter
        router = AdaptiveRouter(simple_threshold=3, complex_threshold=8)
        ctx = _FakeCCBContext(cross_domain_calls=[], module_summaries=[])
        result = router.assess([f"Mod{i}" for i in range(5)], ctx)
        assert result.level == "moderate"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_router.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL (ModuleNotFoundError: No module named 'wiki.harness_router')

- [x] **Step 3: Write minimal implementation**

Create `wiki/harness_router.py`:

```python
"""Adaptive complexity routing for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


CONTEXT_BUDGETS: dict[str, dict[str, int | None]] = {
    "simple": {
        "max_chars_per_section": 1500,
        "distill_total": 6000,
        "coherence_pass": None,
        "repair_input": 3000,
        "eval_input": 1500,
    },
    "moderate": {
        "max_chars_per_section": 3000,
        "distill_total": 12000,
        "coherence_pass": None,
        "repair_input": 4000,
        "eval_input": 2000,
    },
    "complex": {
        "max_chars_per_section": 5000,
        "distill_total": 20000,
        "coherence_pass": 8000,
        "repair_input": 6000,
        "eval_input": 3000,
    },
}


@dataclass
class ComplexityAssessment:
    level: Literal["simple", "moderate", "complex"]
    max_tool_calls: int
    generation_mode: Literal["whole_page", "sectional"]
    max_repair_rounds: int
    use_llm_judge: bool

    @property
    def budget(self) -> dict[str, int | None]:
        return CONTEXT_BUDGETS[self.level]


class AdaptiveRouter:
    def __init__(self, simple_threshold: int = 5, complex_threshold: int = 15):
        self.simple_threshold = simple_threshold
        self.complex_threshold = complex_threshold

    def assess(self, modules: list[str], ccb_context) -> ComplexityAssessment:
        module_count = len(modules)
        edge_count = 0
        if ccb_context is not None:
            calls = getattr(ccb_context, "cross_domain_calls", None)
            edge_count = len(calls) if calls else 0

        if module_count > self.complex_threshold or edge_count > 20:
            return ComplexityAssessment(
                level="complex",
                max_tool_calls=15,
                generation_mode="sectional",
                max_repair_rounds=2,
                use_llm_judge=True,
            )
        elif module_count <= self.simple_threshold and edge_count < 5:
            return ComplexityAssessment(
                level="simple",
                max_tool_calls=5,
                generation_mode="whole_page",
                max_repair_rounds=0,
                use_llm_judge=False,
            )
        else:
            return ComplexityAssessment(
                level="moderate",
                max_tool_calls=10,
                generation_mode="whole_page",
                max_repair_rounds=1,
                use_llm_judge=False,
            )
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_router.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 6 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/harness_router.py tests/wiki/test_harness_router.py
git commit -m "feat: add AdaptiveRouter for wiki generation complexity assessment"
```

---

### Task 2: GatheredFacts + Distill Logic

**Files:**
- Create: `wiki/harness_facts.py`
- Test: `tests/wiki/test_harness_facts.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_facts.py`:

```python
"""Tests for GatheredFacts and tiered distill logic."""
import pytest


class TestGatheredFacts:
    def test_add_fact(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "ModuleA: handles user auth")
        assert "概述" in facts.facts
        assert len(facts.facts["概述"]) == 1
        assert facts.total_chars > 0

    def test_distill_simple_budget(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "A" * 2000)
        facts.add("核心业务流程", "query_call_chain", "B" * 2000)
        result = facts.distill(complexity_level="simple")
        assert "## 概述" in result
        assert "## 核心业务流程" in result
        # simple budget: max_chars_per_section=1500, so truncated
        assert "[...truncated]" in result

    def test_distill_complex_budget_no_truncation(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "A" * 3000)
        result = facts.distill(complexity_level="complex")
        # complex budget: max_chars_per_section=5000, so 3000 fits
        assert "[...truncated]" not in result

    def test_distill_injects_domain_summaries(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "query_module_detail", "test content")
        summaries = ["Domain: Auth\nModules: UserService\nSummary: handles login"]
        result = facts.distill(complexity_level="moderate", domain_summaries=summaries)
        assert "相关域参考" in result
        assert "Auth" in result

    def test_distill_empty_facts(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        result = facts.distill(complexity_level="moderate")
        assert result == ""

    def test_multiple_facts_per_section_combined(self):
        from wiki.harness_facts import GatheredFacts
        facts = GatheredFacts()
        facts.add("概述", "tool1", "fact1")
        facts.add("概述", "tool2", "fact2")
        result = facts.distill(complexity_level="moderate")
        assert "fact1" in result
        assert "fact2" in result
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_facts.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL (ModuleNotFoundError)

- [x] **Step 3: Write minimal implementation**

Create `wiki/harness_facts.py`:

```python
"""Gathered facts storage and tiered distill logic for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass, field

from wiki.harness_router import CONTEXT_BUDGETS


@dataclass
class Fact:
    source: str
    content: str
    section: str
    char_count: int = 0


@dataclass
class GatheredFacts:
    facts: dict[str, list[Fact]] = field(default_factory=dict)
    total_chars: int = 0

    def add(self, section: str, source: str, content: str) -> None:
        if section not in self.facts:
            self.facts[section] = []
        fact = Fact(source=source, content=content, section=section, char_count=len(content))
        self.facts[section].append(fact)
        self.total_chars += len(content)

    def distill(
        self,
        complexity_level: str = "moderate",
        domain_summaries: list[str] | None = None,
    ) -> str:
        """Distill gathered facts into generation context using tiered budgets."""
        if not self.facts:
            return ""

        budget = CONTEXT_BUDGETS[complexity_level]
        max_chars = budget["max_chars_per_section"]

        sections: list[str] = []
        for section_name, fact_list in self.facts.items():
            combined = "\n".join(f.content for f in fact_list)
            if len(combined) > max_chars:
                combined = combined[:max_chars] + "\n[...truncated]"
            sections.append(f"## {section_name}\n{combined}")

        result = "\n\n".join(sections)

        if domain_summaries:
            cross_ref = "\n".join(domain_summaries)
            result = f"## 相关域参考\n{cross_ref}\n\n{result}"

        return result
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_facts.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 6 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/harness_facts.py tests/wiki/test_harness_facts.py
git commit -m "feat: add GatheredFacts with tiered distill budgets"
```

---

### Task 3: WikiPagePlanner — Deterministic Query Planning

**Files:**
- Create: `wiki/harness_planner.py`
- Test: `tests/wiki/test_harness_planner.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_planner.py`:

```python
"""Tests for WikiPagePlanner deterministic query planning."""
import pytest
from dataclasses import dataclass, field


@dataclass
class _FakeCCBContext:
    cross_domain_calls: list = field(default_factory=list)
    module_summaries: list = field(default_factory=list)


class TestWikiPagePlanner:
    def test_plan_generates_all_sections(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import AdaptiveRouter, ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext()
        assessment = ComplexityAssessment(
            level="moderate", max_tool_calls=10,
            generation_mode="whole_page", max_repair_rounds=1,
            use_llm_judge=False,
        )
        plan = planner.plan("UserAuth", ["UserService", "AuthController"], ctx, assessment)
        section_names = [s.name for s in plan.outline]
        assert "概述" in section_names
        assert "核心业务流程" in section_names
        assert "关键实现" in section_names
        assert "依赖关系" in section_names

    def test_plan_has_queries_for_overview(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext()
        assessment = ComplexityAssessment(
            level="moderate", max_tool_calls=10,
            generation_mode="whole_page", max_repair_rounds=1,
            use_llm_judge=False,
        )
        plan = planner.plan("Auth", ["Mod1", "Mod2", "Mod3"], ctx, assessment)
        overview = next(s for s in plan.outline if s.name == "概述")
        assert len(overview.queries) > 0
        assert overview.queries[0].tool_name == "query_module_detail"

    def test_plan_call_chain_query_for_flow_section(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext(cross_domain_calls=[{"src": "A", "dst": "B"}])
        assessment = ComplexityAssessment(
            level="moderate", max_tool_calls=10,
            generation_mode="whole_page", max_repair_rounds=1,
            use_llm_judge=False,
        )
        plan = planner.plan("Auth", ["Mod1"], ctx, assessment)
        flow = next(s for s in plan.outline if s.name == "核心业务流程")
        tool_names = [q.tool_name for q in flow.queries]
        assert "query_call_chain" in tool_names
        assert "query_callers" in tool_names  # has cross_domain_calls

    def test_simple_domain_skips_read_code(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext()
        assessment = ComplexityAssessment(
            level="simple", max_tool_calls=5,
            generation_mode="whole_page", max_repair_rounds=0,
            use_llm_judge=False,
        )
        plan = planner.plan("Small", ["Mod1"], ctx, assessment)
        impl = next(s for s in plan.outline if s.name == "关键实现")
        tool_names = [q.tool_name for q in impl.queries]
        assert "read_code" not in tool_names

    def test_total_queries_computed(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext()
        assessment = ComplexityAssessment(
            level="moderate", max_tool_calls=10,
            generation_mode="whole_page", max_repair_rounds=1,
            use_llm_judge=False,
        )
        plan = planner.plan("Auth", ["Mod1", "Mod2"], ctx, assessment)
        assert plan.total_queries == sum(len(s.queries) for s in plan.outline)
        assert plan.total_queries > 0

    def test_cross_domain_refs_from_cache(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext(cross_domain_calls=[{"caller": "Ext", "callee": "Mod1"}])
        assessment = ComplexityAssessment(
            level="moderate", max_tool_calls=10,
            generation_mode="whole_page", max_repair_rounds=1,
            use_llm_judge=False,
        )
        cache = {"PaymentDomain": "card data"}
        plan = planner.plan("Auth", ["Mod1"], ctx, assessment, domain_cache=cache)
        assert isinstance(plan.cross_domain_refs, list)
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_planner.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL

- [x] **Step 3: Write minimal implementation**

Create `wiki/harness_planner.py`:

```python
"""Deterministic query planner for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass, field

from wiki.harness_router import ComplexityAssessment, CONTEXT_BUDGETS


@dataclass
class PlannedQuery:
    tool_name: str
    params: dict
    target_section: str
    priority: int  # 1=must, 2=recommended, 3=optional


@dataclass
class SectionPlan:
    name: str
    queries: list[PlannedQuery] = field(default_factory=list)
    description: str = ""


@dataclass
class GenerationPlan:
    outline: list[SectionPlan]
    cross_domain_refs: list[str] = field(default_factory=list)
    total_queries: int = 0
    context_budget_tokens: int = 0


class WikiPagePlanner:
    SECTION_TEMPLATES = [
        ("概述", "模块职责、核心类/接口"),
        ("核心业务流程", "调用链、Mermaid sequenceDiagram"),
        ("关键实现", "核心方法实现、设计模式"),
        ("依赖关系", "模块间依赖、接口实现关系"),
    ]

    def plan(
        self,
        domain: str,
        modules: list[str],
        ccb_context,
        assessment: ComplexityAssessment,
        domain_cache: dict | None = None,
    ) -> GenerationPlan:
        sections = []
        for name, desc in self.SECTION_TEMPLATES:
            queries = self._plan_section_queries(name, modules, ccb_context, assessment)
            sections.append(SectionPlan(name=name, queries=queries, description=desc))

        cross_refs = self._identify_cross_domain_refs(ccb_context, domain_cache)
        total_q = sum(len(s.queries) for s in sections)
        budget = CONTEXT_BUDGETS[assessment.level]["distill_total"] or 12000

        return GenerationPlan(
            outline=sections,
            cross_domain_refs=cross_refs,
            total_queries=total_q,
            context_budget_tokens=budget,
        )

    def _plan_section_queries(
        self, section_name: str, modules: list[str],
        ccb_context, assessment: ComplexityAssessment,
    ) -> list[PlannedQuery]:
        queries: list[PlannedQuery] = []
        max_mods = max(1, assessment.max_tool_calls // 4)

        if section_name == "概述":
            for m in modules[:max_mods]:
                queries.append(PlannedQuery(
                    tool_name="query_module_detail",
                    params={"module_name": m},
                    target_section="概述",
                    priority=1,
                ))
        elif section_name == "核心业务流程":
            queries.append(PlannedQuery(
                tool_name="query_call_chain",
                params={"module_names": modules[:10]},
                target_section="核心业务流程",
                priority=1,
            ))
            has_cross = (
                ccb_context is not None
                and getattr(ccb_context, "cross_domain_calls", None)
                and len(ccb_context.cross_domain_calls) > 0
            )
            if has_cross:
                queries.append(PlannedQuery(
                    tool_name="query_callers",
                    params={"module_names": modules[:5]},
                    target_section="核心业务流程",
                    priority=2,
                ))
        elif section_name == "关键实现":
            if assessment.level != "simple":
                queries.append(PlannedQuery(
                    tool_name="read_code",
                    params={"module_names": modules[:3]},
                    target_section="关键实现",
                    priority=2,
                ))
        elif section_name == "依赖关系":
            queries.append(PlannedQuery(
                tool_name="query_domain_dependencies",
                params={"domain_name": modules[0] if modules else ""},
                target_section="依赖关系",
                priority=1,
            ))
            queries.append(PlannedQuery(
                tool_name="query_implementations",
                params={"module_names": modules[:10]},
                target_section="依赖关系",
                priority=2,
            ))
        return queries

    def _identify_cross_domain_refs(
        self, ccb_context, domain_cache: dict | None,
    ) -> list[str]:
        if not domain_cache:
            return []
        return list(domain_cache.keys())
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_planner.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 6 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/harness_planner.py tests/wiki/test_harness_planner.py
git commit -m "feat: add WikiPagePlanner for deterministic query planning"
```

---

### Task 4: WikiPageEvaluator — L1 Deterministic Checks

**Files:**
- Create: `wiki/harness_evaluator.py`
- Test: `tests/wiki/test_harness_evaluator.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_evaluator.py`:

```python
"""Tests for WikiPageEvaluator L1 deterministic checks."""
import pytest
from dataclasses import dataclass


@dataclass
class _FakeAssessment:
    level: str = "moderate"
    use_llm_judge: bool = False


class TestEvaluatorL1:
    def test_good_content_passes(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModuleA 负责用户认证，ModuleB 负责权限校验。

## 核心业务流程
用户通过 ModuleA 进行登录验证，然后 ModuleB 检查权限。

## 关键实现
ModuleA 使用 JWT token，ModuleB 使用 RBAC 模型。

## 依赖关系
ModuleA 依赖 ModuleB 进行权限验证。
""" + "详细内容。" * 100  # ensure > 500 chars
        result = evaluator.evaluate_l1(content, ["ModuleA", "ModuleB"])
        assert result.passed is True
        assert result.score >= 0.7
        assert len(result.issues) == 0

    def test_missing_modules_fails_coverage(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModuleA 负责用户认证。
## 核心业务流程
流程说明。
""" + "填充内容。" * 100
        result = evaluator.evaluate_l1(content, ["ModuleA", "ModuleB", "ModuleC", "ModuleD", "ModuleE"])
        assert any(i.category == "coverage" for i in result.issues)

    def test_missing_overview_fails_structure(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 核心业务流程
ModA calls ModB.
## 关键实现
Details here.
""" + "填充。" * 100
        result = evaluator.evaluate_l1(content, ["ModA", "ModB"])
        assert any(i.category == "structure" for i in result.issues)

    def test_unclosed_fence_fails_format(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = """## 概述
ModA handles auth.
## 核心业务流程
```mermaid
sequenceDiagram
  ModA->>ModB: call
""" + "填充。" * 100  # unclosed fence
        result = evaluator.evaluate_l1(content, ["ModA", "ModB"])
        assert any(i.category == "format" for i in result.issues)

    def test_too_short_fails_length(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = "## 概述\nShort."
        result = evaluator.evaluate_l1(content, ["Mod"])
        assert any(i.category == "length" for i in result.issues)
        assert result.passed is False

    def test_evaluate_dispatches_to_l1_only_when_no_llm_judge(self):
        from wiki.harness_evaluator import WikiPageEvaluator
        evaluator = WikiPageEvaluator()
        content = "## 概述\nModA.\n## 核心业务流程\nflow.\n" + "x" * 600
        assessment = _FakeAssessment(level="simple", use_llm_judge=False)
        result = evaluator.evaluate(content, ["ModA"], assessment)
        assert isinstance(result.score, float)
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_evaluator.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL

- [x] **Step 3: Write minimal implementation**

Create `wiki/harness_evaluator.py`:

```python
"""Wiki page evaluator with L1 deterministic checks and optional L2 LLM judge."""
from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass
class Issue:
    category: str
    severity: str
    message: str
    suggestion: str = ""


@dataclass
class EvalResult:
    score: float
    passed: bool
    issues: list[Issue] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


class WikiPageEvaluator:
    PASS_THRESHOLD = 0.7
    MIN_CHARS = 500
    MAX_CHARS = 15000

    def evaluate(self, content: str, modules: list[str], assessment, llm=None) -> EvalResult:
        result = self.evaluate_l1(content, modules)
        if getattr(assessment, "use_llm_judge", False) and not result.passed and llm:
            result = self.evaluate_l2(content, modules, llm, result)
        return result

    def evaluate_l1(self, content: str, modules: list[str]) -> EvalResult:
        issues: list[Issue] = []
        scores: list[float] = []

        # 1. Module coverage
        if modules:
            mentioned = sum(1 for m in modules if m.lower() in content.lower())
            coverage = mentioned / len(modules)
        else:
            coverage = 1.0
        scores.append(coverage)
        if coverage < 0.8:
            missing = [m for m in modules if m.lower() not in content.lower()]
            issues.append(Issue(
                category="coverage", severity="error",
                message=f"模块覆盖率 {coverage:.0%}, 缺失: {missing[:5]}",
                suggestion="请确保提及所有关键模块",
            ))

        # 2. Structure
        has_overview = bool(re.search(r"^##?\s*(概述|Overview)", content, re.M))
        has_flow = bool(re.search(r"^##?\s*(核心|业务|流程|Core|Flow)", content, re.M))
        struct_score = (int(has_overview) + int(has_flow)) / 2
        scores.append(struct_score)
        if not has_overview:
            issues.append(Issue("structure", "error", "缺少概述段", "添加## 概述"))
        if not has_flow:
            issues.append(Issue("structure", "warning", "缺少业务流程段", "添加## 核心业务流程"))

        # 3. Format
        has_unclosed_fence = content.count("```") % 2 != 0
        has_context_gap = "CONTEXT_GAP" in content
        format_score = 1.0 - (0.3 * int(has_unclosed_fence) + 0.2 * int(has_context_gap))
        scores.append(format_score)
        if has_unclosed_fence:
            issues.append(Issue("format", "error", "未关闭的代码块", "检查```配对"))
        if has_context_gap:
            issues.append(Issue("format", "warning", "存在CONTEXT_GAP标记", "补充缺失信息"))

        # 4. Length
        char_count = len(content)
        if char_count < self.MIN_CHARS:
            length_score = char_count / self.MIN_CHARS
            issues.append(Issue("length", "error", f"内容过短({char_count}字)", "补充更多细节"))
        elif char_count > self.MAX_CHARS:
            length_score = 0.8
            issues.append(Issue("length", "warning", f"内容过长({char_count}字)", "精简冗余"))
        else:
            length_score = 1.0
        scores.append(length_score)

        final_score = sum(scores) / len(scores) if scores else 0.0
        return EvalResult(
            score=final_score,
            passed=final_score >= self.PASS_THRESHOLD,
            issues=issues,
            suggestions=[i.suggestion for i in issues if i.severity == "error"],
        )

    async def evaluate_l2(self, content, modules, llm, l1_result) -> EvalResult:
        """LLM Judge. Implementation details in execution phase."""
        return l1_result
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_evaluator.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 6 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/harness_evaluator.py tests/wiki/test_harness_evaluator.py
git commit -m "feat: add WikiPageEvaluator with L1 deterministic checks"
```

---

### Task 5: GuardRails

**Files:**
- Create: `wiki/harness_guardrails.py`
- Test: `tests/wiki/test_harness_guardrails.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_guardrails.py`:

```python
"""Tests for HarnessGuardRails."""
import pytest


class TestGuardRails:
    def test_first_call_passes(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        assert result is None

    def test_duplicate_call_blocked(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        assert result is not None
        assert result.action == "block"

    def test_different_params_not_duplicate(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod2"})
        assert result is None

    def test_output_too_short_warns(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("short")
        assert len(violations) == 1
        assert violations[0].rule == "too_short"
        assert violations[0].action == "warn"

    def test_output_too_long_truncates(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("x" * 20000)
        assert any(v.rule == "too_long" for v in violations)

    def test_output_normal_no_violations(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("x" * 1000)
        assert len(violations) == 0
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_guardrails.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL

- [x] **Step 3: Write minimal implementation**

Create `wiki/harness_guardrails.py`:

```python
"""Guard rails for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class GuardRailViolation:
    rule: str
    message: str
    action: str  # "warn", "block", "truncate"


class HarnessGuardRails:
    MAX_DUPLICATE_QUERIES = 2
    MIN_OUTPUT_LENGTH = 500
    MAX_OUTPUT_LENGTH = 15000

    def __init__(self) -> None:
        self._query_history: list[str] = []

    def check_tool_call(self, tool_name: str, params: dict) -> GuardRailViolation | None:
        key = f"{tool_name}:{sorted(params.items())}"
        count = self._query_history.count(key)
        if count >= self.MAX_DUPLICATE_QUERIES:
            return GuardRailViolation(
                rule="duplicate_query",
                message=f"Query '{tool_name}' called {count + 1} times with same params",
                action="block",
            )
        self._query_history.append(key)
        return None

    def check_output(self, content: str) -> list[GuardRailViolation]:
        violations: list[GuardRailViolation] = []
        if len(content) < self.MIN_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                rule="too_short",
                message=f"Output {len(content)} chars < {self.MIN_OUTPUT_LENGTH}",
                action="warn",
            ))
        if len(content) > self.MAX_OUTPUT_LENGTH:
            violations.append(GuardRailViolation(
                rule="too_long",
                message=f"Output {len(content)} chars > {self.MAX_OUTPUT_LENGTH}",
                action="truncate",
            ))
        return violations
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_guardrails.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 6 passed

- [x] **Step 5: Commit**

```bash
git add wiki/harness_guardrails.py tests/wiki/test_harness_guardrails.py
git commit -m "feat: add HarnessGuardRails for duplicate and output checks"
```

---

### Task 6: DomainSummaryCache

**Files:**
- Create: `wiki/domain_summary_cache.py`
- Test: `tests/wiki/test_domain_summary_cache.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_domain_summary_cache.py`:

```python
"""Tests for DomainSummaryCard extraction."""
import pytest


class TestDomainSummaryCache:
    def test_extract_card_basic(self):
        from wiki.domain_summary_cache import extract_summary_card
        content = """## 概述
UserService 负责用户注册和登录认证，是系统的核心入口。

## 核心业务流程
用户通过 API 调用 UserService 进行注册。
"""
        card = extract_summary_card("UserAuth", ["UserService", "AuthHelper"], content)
        assert card.domain_name == "UserAuth"
        assert card.module_names == ["UserService", "AuthHelper"]
        assert "用户注册" in card.responsibilities
        assert card.content_hash != ""

    def test_extract_card_no_overview(self):
        from wiki.domain_summary_cache import extract_summary_card
        content = "Some content without overview section."
        card = extract_summary_card("Domain1", ["Mod1"], content)
        assert card.responsibilities == ""

    def test_extract_card_entry_points(self):
        from wiki.domain_summary_cache import extract_summary_card
        card_modules = ["EntryMod", "HelperMod", "UtilMod", "ExtraMod"]
        from wiki.domain_summary_cache import extract_summary_card
        content = "## 概述\nSome overview."
        card = extract_summary_card("Dom", card_modules, content)
        assert len(card.entry_points) <= 3

    def test_card_content_hash_changes_with_content(self):
        from wiki.domain_summary_cache import extract_summary_card
        card1 = extract_summary_card("D", ["M"], "## 概述\nVersion 1")
        card2 = extract_summary_card("D", ["M"], "## 概述\nVersion 2")
        assert card1.content_hash != card2.content_hash
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_domain_summary_cache.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: FAIL

- [x] **Step 3: Write minimal implementation**

Create `wiki/domain_summary_cache.py`:

```python
"""Domain Summary Cache for cross-domain knowledge sharing."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class DomainSummaryCard:
    domain_name: str
    module_names: list[str]
    entry_points: list[str]
    responsibilities: str
    depends_on: list[str] = field(default_factory=list)
    generated_at: str = ""
    content_hash: str = ""


def extract_summary_card(
    domain: str, modules: list[str], content: str,
) -> DomainSummaryCard:
    """Extract a summary card from generated wiki content. Deterministic."""
    overview_match = re.search(
        r"##?\s*概述\s*\n(.*?)(?=\n##|\Z)", content, re.S,
    )
    responsibilities = overview_match.group(1).strip()[:200] if overview_match else ""

    entry_points = modules[:3]

    content_hash = hashlib.md5(content.encode()).hexdigest()

    return DomainSummaryCard(
        domain_name=domain,
        module_names=modules,
        entry_points=entry_points,
        responsibilities=responsibilities,
        depends_on=[],
        generated_at=datetime.now().isoformat(),
        content_hash=content_hash,
    )
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_domain_summary_cache.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: 4 passed

- [x] **Step 5: Commit**

```bash
git add wiki/domain_summary_cache.py tests/wiki/test_domain_summary_cache.py
git commit -m "feat: add DomainSummaryCard for cross-domain knowledge sharing"
```

---

### Task 7: page_agent.py — Add repair() Method

**Files:**
- Modify: `wiki/page_agent.py`
- Test: `tests/wiki/test_harness_repair.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_repair.py`:

```python
"""Tests for WikiPageAgent.repair() method."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock
from dataclasses import dataclass, field


@dataclass
class _FakeEvalResult:
    score: float = 0.5
    passed: bool = False
    issues: list = field(default_factory=lambda: [
        MagicMock(category="coverage", message="模块覆盖率 60%", severity="error"),
    ])
    suggestions: list = field(default_factory=lambda: ["请确保提及所有关键模块"])


def test_repair_method_exists():
    from wiki.page_agent import WikiPageAgent
    assert hasattr(WikiPageAgent, "repair")
    import inspect
    assert inspect.iscoroutinefunction(WikiPageAgent.repair)


def test_repair_returns_improved_content():
    from wiki.page_agent import WikiPageAgent

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="## 概述\n修正后的完整内容" + "x" * 300)

    agent = WikiPageAgent(llm=mock_llm, graph_store=MagicMock())
    eval_result = _FakeEvalResult()

    result = asyncio.run(agent.repair("原始内容" * 50, eval_result))
    assert len(result) > 200
    mock_llm.generate.assert_called_once()


def test_repair_returns_original_if_llm_fails():
    from wiki.page_agent import WikiPageAgent

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(return_value="too short")

    agent = WikiPageAgent(llm=mock_llm, graph_store=MagicMock())
    original = "原始内容" * 50
    eval_result = _FakeEvalResult()

    result = asyncio.run(agent.repair(original, eval_result))
    assert result == original
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_repair.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: FAIL (AttributeError: WikiPageAgent has no attribute 'repair')

- [x] **Step 3: Add repair() to WikiPageAgent**

Add the following method to `wiki/page_agent.py` in the `WikiPageAgent` class (after the `generate` method):

```python
    async def repair(self, content: str, eval_result) -> str:
        """Repair content based on Evaluator feedback. No tool calls — pure LLM rewrite."""
        issues_text = "\n".join(
            f"- [{getattr(i, 'category', '?')}] {getattr(i, 'message', str(i))}"
            for i in (eval_result.issues or [])
        )
        suggestions_text = "\n".join(
            f"- {s}" for s in (eval_result.suggestions or [])
        )

        repair_prompt = (
            "以下 Wiki 页面有质量问题需要修正:\n\n"
            f"## 当前问题\n{issues_text}\n\n"
            f"## 修正建议\n{suggestions_text}\n\n"
            f"## 当前内容\n{content[:4000]}\n\n"
            "请修正上述问题, 输出完整的修正后页面。保持原有正确内容不变, 只修复指出的问题。"
        )

        messages = [{"role": "user", "content": repair_prompt}]
        try:
            response = await self.llm.generate(messages)
            repaired = strip_agent_artifacts(response) if response else ""
            return repaired if len(repaired) > 200 else content
        except Exception:
            return content
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_repair.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: 3 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/page_agent.py tests/wiki/test_harness_repair.py
git commit -m "feat: add repair() method to WikiPageAgent for harness feedback loop"
```

---

### Task 8: HarnessConfig

**Files:**
- Modify: `wiki/agent_config.py`

- [x] **Step 1: Write the failing test**

Add to an existing or new test file:

Create `tests/wiki/test_harness_config.py`:

```python
"""Tests for HarnessConfig."""
import os
import pytest


class TestHarnessConfig:
    def test_default_disabled(self):
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.enabled is False

    def test_enabled_from_env(self, monkeypatch):
        monkeypatch.setenv("WIKI__USE_HARNESS", "true")
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.enabled is True

    def test_custom_thresholds(self, monkeypatch):
        monkeypatch.setenv("WIKI__HARNESS_SIMPLE_THRESHOLD", "3")
        monkeypatch.setenv("WIKI__HARNESS_COMPLEX_THRESHOLD", "20")
        from wiki.agent_config import HarnessConfig
        config = HarnessConfig.from_env()
        assert config.simple_threshold == 3
        assert config.complex_threshold == 20
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_config.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: FAIL (ImportError: cannot import name 'HarnessConfig')

- [x] **Step 3: Add HarnessConfig to agent_config.py**

Add the following to `wiki/agent_config.py`:

```python
@dataclass
class HarnessConfig:
    enabled: bool = False
    max_repair_rounds: int = 2
    simple_threshold: int = 5
    complex_threshold: int = 15
    llm_judge_enabled: bool = True

    @classmethod
    def from_env(cls) -> "HarnessConfig":
        return cls(
            enabled=os.getenv("WIKI__USE_HARNESS", "").lower() in ("true", "1", "yes"),
            max_repair_rounds=int(os.getenv("WIKI__HARNESS_MAX_REPAIR_ROUNDS", "2")),
            simple_threshold=int(os.getenv("WIKI__HARNESS_SIMPLE_THRESHOLD", "5")),
            complex_threshold=int(os.getenv("WIKI__HARNESS_COMPLEX_THRESHOLD", "15")),
            llm_judge_enabled=os.getenv("WIKI__HARNESS_LLM_JUDGE", "true").lower() in ("true", "1"),
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_config.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: 3 passed

- [x] **Step 5: Commit**

```bash
git add wiki/agent_config.py tests/wiki/test_harness_config.py
git commit -m "feat: add HarnessConfig for wiki generation harness settings"
```

---

### Task 9: WikiGenerationHarness — Orchestrator

**Files:**
- Create: `wiki/harness.py`
- Test: `tests/wiki/test_harness_integration.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_integration.py`:

```python
"""Integration tests for WikiGenerationHarness."""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from dataclasses import dataclass, field


@dataclass
class _FakeCCBContext:
    cross_domain_calls: list = field(default_factory=list)
    module_summaries: list = field(default_factory=list)


def _make_mock_agent(content="## 概述\nModA handles auth.\n## 核心业务流程\nModA calls ModB.\n" + "x" * 600):
    agent = AsyncMock()
    agent.generate = AsyncMock(return_value=content)
    agent.repair = AsyncMock(return_value=content)
    return agent


def _make_mock_graph_store():
    gs = AsyncMock()
    gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    return gs


def _make_mock_llm():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="repaired content" + "x" * 600)
    return llm


class TestHarnessRun:
    def test_harness_runs_full_pipeline(self):
        from wiki.harness import WikiGenerationHarness
        agent = _make_mock_agent()
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        result = asyncio.run(harness.run(
            domain="UserAuth", modules=["ModA", "ModB"],
            ccb_context=_FakeCCBContext(),
        ))
        assert len(result) > 0
        agent.generate.assert_called_once()

    def test_harness_simple_domain_no_repair(self):
        from wiki.harness import WikiGenerationHarness
        good_content = "## 概述\nModA does X.\n## 核心业务流程\nModA calls Y.\n" + "detail " * 100
        agent = _make_mock_agent(good_content)
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        result = asyncio.run(harness.run(
            domain="Small", modules=["ModA"],
            ccb_context=_FakeCCBContext(),
        ))
        agent.repair.assert_not_called()  # simple domain, no repair rounds

    def test_harness_updates_domain_cache(self):
        from wiki.harness import WikiGenerationHarness
        agent = _make_mock_agent()
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        asyncio.run(harness.run(
            domain="UserAuth", modules=["ModA"],
            ccb_context=_FakeCCBContext(),
        ))
        assert "UserAuth" in harness.domain_cache

    def test_harness_repair_triggered_on_low_score(self):
        from wiki.harness import WikiGenerationHarness
        bad_content = "short"  # will fail L1 length check
        good_content = "## 概述\nModA does auth.\n## 核心业务流程\nModA flow.\n" + "x" * 600
        agent = AsyncMock()
        agent.generate = AsyncMock(return_value=bad_content)
        agent.repair = AsyncMock(return_value=good_content)
        harness = WikiGenerationHarness(
            agent=agent, graph_store=_make_mock_graph_store(), llm=_make_mock_llm(),
        )
        # Use moderate to get repair rounds = 1
        result = asyncio.run(harness.run(
            domain="Auth", modules=[f"Mod{i}" for i in range(8)],
            ccb_context=_FakeCCBContext(cross_domain_calls=[{"a": "b"}] * 3),
        ))
        agent.repair.assert_called()
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_integration.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: FAIL

- [x] **Step 3: Write WikiGenerationHarness**

Create `wiki/harness.py`:

```python
"""Wiki Generation Harness — Plan-Gather-Distill-Generate-Evaluate-Repair orchestrator."""
from __future__ import annotations

from core.log import get_logger
from wiki.domain_summary_cache import extract_summary_card
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.harness_facts import GatheredFacts
from wiki.harness_guardrails import HarnessGuardRails
from wiki.harness_planner import WikiPagePlanner
from wiki.harness_router import AdaptiveRouter

log = get_logger(__name__)


class WikiGenerationHarness:
    def __init__(self, agent, graph_store, llm, config=None):
        self.agent = agent
        self.graph_store = graph_store
        self.llm = llm
        self.router = AdaptiveRouter()
        self.planner = WikiPagePlanner()
        self.evaluator = WikiPageEvaluator()
        self.domain_cache: dict[str, str] = {}

    async def run(
        self,
        domain: str,
        modules: list[str],
        ccb_context,
        **kwargs,
    ) -> str:
        # 1. Complexity assessment
        assessment = self.router.assess(modules, ccb_context)
        log.info(
            "harness_assess",
            domain=domain,
            level=assessment.level,
            modules=len(modules),
        )

        # 2. Plan
        plan = self.planner.plan(
            domain, modules, ccb_context, assessment,
            domain_cache=self.domain_cache,
        )

        # 3. Gather
        facts = await self._gather(plan)

        # 4. Distill
        domain_summaries = [
            self.domain_cache[d]
            for d in plan.cross_domain_refs
            if d in self.domain_cache
        ]
        distilled = facts.distill(
            complexity_level=assessment.level,
            domain_summaries=domain_summaries if domain_summaries else None,
        )

        # 5. Generate
        baseline = distilled if distilled else None
        content = await self.agent.generate(
            module_names=modules,
            domain_name=domain,
            baseline_context=baseline,
            max_rounds=3 if assessment.level == "simple" else 5,
        )

        # 6. Evaluate + Repair loop
        for round_i in range(assessment.max_repair_rounds + 1):
            eval_result = self.evaluator.evaluate(content, modules, assessment, self.llm)
            if eval_result.passed:
                break
            if round_i < assessment.max_repair_rounds:
                log.info(
                    "harness_repair",
                    domain=domain,
                    round=round_i + 1,
                    score=eval_result.score,
                )
                content = await self.agent.repair(content, eval_result)

        # 7. Update domain cache
        self._update_domain_cache(domain, modules, content)

        return content

    async def _gather(self, plan) -> GatheredFacts:
        """Execute planned queries against graph_store. No LLM involved."""
        facts = GatheredFacts()
        guardrails = HarnessGuardRails()

        for section in plan.outline:
            for query in section.queries:
                violation = guardrails.check_tool_call(query.tool_name, query.params)
                if violation:
                    log.warning("harness_guardrail", rule=violation.rule)
                    continue
                try:
                    result = await self._execute_planned_query(query)
                    if result:
                        facts.add(section.name, query.tool_name, str(result))
                except Exception as e:
                    log.warning("harness_gather_error", tool=query.tool_name, error=str(e))

        return facts

    async def _execute_planned_query(self, query) -> str | None:
        """Execute a single planned query via graph_store."""
        if not self.graph_store:
            return None
        try:
            result = await self.graph_store.execute_query(
                f"MATCH (n) WHERE n.name IN $names RETURN n.name LIMIT 5",
                params={"names": query.params.get("module_names", [query.params.get("module_name", "")])},
            )
            if hasattr(result, "data") and result.data:
                return str(result.data[:5])
        except Exception:
            pass
        return None

    def _update_domain_cache(self, domain: str, modules: list[str], content: str) -> None:
        card = extract_summary_card(domain, modules, content)
        self.domain_cache[domain] = (
            f"Domain: {card.domain_name}\n"
            f"Modules: {', '.join(card.module_names[:10])}\n"
            f"Summary: {card.responsibilities}"
        )
```

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_integration.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 4 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/harness.py tests/wiki/test_harness_integration.py
git commit -m "feat: add WikiGenerationHarness orchestrator with Plan-Gather-Distill-Generate-Evaluate-Repair pipeline"
```

---

### Task 10: Compose.py Integration + repo_path Bug Fix

**Files:**
- Modify: `wiki/nodes/compose.py`
- Test: `tests/wiki/test_harness_compose_integration.py`

- [x] **Step 1: Write the failing test**

Create `tests/wiki/test_harness_compose_integration.py`:

```python
"""Tests for Harness integration in compose.py."""
import inspect
import pytest


def test_compose_imports_harness():
    """compose.py should have WikiGenerationHarness import available."""
    from wiki.nodes import compose
    source = inspect.getsource(compose)
    assert "WikiGenerationHarness" in source or "harness" in source.lower()


def test_compose_passes_repo_path_to_agent():
    """compose.py should pass repo_path when creating WikiPageAgent."""
    from wiki.nodes import compose
    source = inspect.getsource(compose._compose_single_leaf_domain)
    assert "repo_path" in source


def test_harness_config_importable():
    """HarnessConfig should be importable from agent_config."""
    from wiki.agent_config import HarnessConfig
    config = HarnessConfig.from_env()
    assert hasattr(config, "enabled")
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_compose_integration.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: FAIL (at least test_compose_imports_harness and test_compose_passes_repo_path_to_agent)

- [x] **Step 3: Modify compose.py**

In `wiki/nodes/compose.py`, find the agent-driven branch in `_compose_single_leaf_domain` and:
1. Add `repo_path` and `search_service` when creating `WikiPageAgent`
2. Add Harness path as an alternative

The modifications should:
- Import `WikiGenerationHarness` and `HarnessConfig`
- Pass `repo_path=state.get("repo_path")` and `search_service=state.get("search_service")` to WikiPageAgent
- Add conditional: if `HarnessConfig.from_env().enabled`, use Harness; else use existing Agent path

- [x] **Step 4: Run test to verify it passes**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_compose_integration.py -v --no-header --no-cov 2>&1 | tail -10`
Expected: 3 passed

- [x] **Step 5: Run full regression**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -5`
Expected: All tests pass

- [x] **Step 6: Commit**

```bash
git add wiki/nodes/compose.py tests/wiki/test_harness_compose_integration.py
git commit -m "feat: integrate WikiGenerationHarness into compose pipeline + fix repo_path bug"
```

---

### Task 11: Final Integration Smoke Test

**Files:**
- Create: `tests/wiki/test_harness_smoke.py`

- [x] **Step 1: Write smoke test**

Create `tests/wiki/test_harness_smoke.py`:

```python
"""Smoke test: verify all harness components are importable and wired correctly."""
import inspect
import pytest


def test_all_harness_modules_importable():
    from wiki.harness import WikiGenerationHarness
    from wiki.harness_router import AdaptiveRouter, ComplexityAssessment, CONTEXT_BUDGETS
    from wiki.harness_planner import WikiPagePlanner, GenerationPlan, SectionPlan, PlannedQuery
    from wiki.harness_evaluator import WikiPageEvaluator, EvalResult, Issue
    from wiki.harness_facts import GatheredFacts, Fact
    from wiki.harness_guardrails import HarnessGuardRails, GuardRailViolation
    from wiki.domain_summary_cache import DomainSummaryCard, extract_summary_card
    from wiki.agent_config import HarnessConfig
    assert True


def test_harness_has_run_method():
    from wiki.harness import WikiGenerationHarness
    assert hasattr(WikiGenerationHarness, "run")
    assert inspect.iscoroutinefunction(WikiGenerationHarness.run)


def test_context_budgets_all_levels():
    from wiki.harness_router import CONTEXT_BUDGETS
    assert "simple" in CONTEXT_BUDGETS
    assert "moderate" in CONTEXT_BUDGETS
    assert "complex" in CONTEXT_BUDGETS
    for level, budget in CONTEXT_BUDGETS.items():
        assert "max_chars_per_section" in budget
        assert "distill_total" in budget


def test_agent_has_repair():
    from wiki.page_agent import WikiPageAgent
    assert hasattr(WikiPageAgent, "repair")


def test_harness_config_from_env():
    from wiki.agent_config import HarnessConfig
    config = HarnessConfig.from_env()
    assert isinstance(config.enabled, bool)
    assert isinstance(config.max_repair_rounds, int)
```

- [x] **Step 2: Run smoke test**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest tests/wiki/test_harness_smoke.py -v --no-header --no-cov 2>&1 | tail -15`
Expected: 5 passed

- [x] **Step 3: Run full test suite**

Run: `cd /Users/earthchen/ai-work/agent-work/knowledge-base-service && .venv/bin/python -m pytest --no-cov -x -q 2>&1 | tail -10`
Expected: All tests pass

- [x] **Step 4: Commit**

```bash
git add tests/wiki/test_harness_smoke.py
git commit -m "test: add integration smoke test for wiki generation harness"
```
