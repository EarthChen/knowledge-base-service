"""Deterministic query planner for Wiki generation harness."""
from __future__ import annotations

from dataclasses import dataclass, field

from wiki.harness_router import CONTEXT_BUDGETS, ComplexityAssessment


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
