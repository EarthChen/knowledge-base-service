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
            use_l2_benchmark=False,
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
            use_l2_benchmark=False,
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
            use_l2_benchmark=False,
        )
        plan = planner.plan("Auth", ["Mod1"], ctx, assessment)
        flow = next(s for s in plan.outline if s.name == "核心业务流程")
        tool_names = [q.tool_name for q in flow.queries]
        assert "query_call_chain" in tool_names
        assert "query_callers" in tool_names

    def test_simple_domain_skips_read_code(self):
        from wiki.harness_planner import WikiPagePlanner
        from wiki.harness_router import ComplexityAssessment
        planner = WikiPagePlanner()
        ctx = _FakeCCBContext()
        assessment = ComplexityAssessment(
            level="simple", max_tool_calls=5,
            generation_mode="whole_page", max_repair_rounds=0,
            use_l2_benchmark=False,
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
            use_l2_benchmark=False,
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
            use_l2_benchmark=False,
        )
        cache = {"PaymentDomain": "card data"}
        plan = planner.plan("Auth", ["Mod1"], ctx, assessment, domain_cache=cache)
        assert isinstance(plan.cross_domain_refs, list)
