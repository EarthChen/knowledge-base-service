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
        modules = [f"Mod{i}" for i in range(8)]
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
