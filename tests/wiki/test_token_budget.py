import math

from wiki.token_budget import TokenBudgetCalculator, TokenBudgetResolver


class TestTokenBudgetResolver:
    def test_default_ratios(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.budget("decomposition") == 30_000
        assert r.budget("ask_general") == 8_100
        assert r.budget("ask_flow") == 12_000
        assert r.budget("compact") == 3_900
        assert r.budget("assembly") == 8_100

    def test_ceiling_cap(self):
        r = TokenBudgetResolver(base=30_000, ceiling=8_000)
        assert r.budget("decomposition") <= 6_400  # 8000 * 0.8
        assert r.budget("ask_flow") <= 6_400

    def test_small_model_scaling(self):
        r = TokenBudgetResolver(base=6_000)
        assert r.budget("decomposition") == 6_000
        assert r.budget("ask_flow") == 2_400
        assert r.budget("compact") == 780

    def test_unknown_component_uses_default_ratio(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.budget("unknown") == 8_100  # 0.27 ratio

    def test_ask_budget_shortcut(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.ask_budget("flow") == 12_000
        assert r.ask_budget("general") == 8_100
        assert r.ask_budget(None) == 8_100

    def test_floor_prevents_zero(self):
        r = TokenBudgetResolver(base=100)
        assert r.budget("compact") >= 512


class TestAutoDerivation:
    """When base is None, derive it from ceiling (context window)."""

    def test_128k_model(self):
        r = TokenBudgetResolver(ceiling=128_000)
        assert 28_000 <= r._base <= 32_000

    def test_8k_model_uses_floor(self):
        r = TokenBudgetResolver(ceiling=8_000)
        assert r._base == 4_000

    def test_200k_model(self):
        r = TokenBudgetResolver(ceiling=200_000)
        assert r._base == 46_000

    def test_1m_model_uses_cap(self):
        r = TokenBudgetResolver(ceiling=1_000_000)
        assert r._base == 60_000

    def test_no_base_no_ceiling_fallback(self):
        r = TokenBudgetResolver()
        assert r._base == 30_000

    def test_explicit_base_ignores_auto(self):
        r = TokenBudgetResolver(base=50_000, ceiling=128_000)
        assert r._base == 50_000


def test_pipeline_component_ratios():
    """New pipeline components should have budget ratios."""
    r = TokenBudgetResolver(base=30_000)
    assert r.budget("domain_classify") == 15_000
    assert r.budget("domain_merge") == 6_000
    assert r.budget("domain_tree_plan") == 4_500
    assert r.budget("topic_page_generate") == 18_000
    assert r.budget("domain_overview") == 9_000
    assert r.budget("system_overview") == 7_500
    assert r.budget("entity_group") == 6_000


def test_resolver_from_config():
    from core.config import get_settings
    from wiki.token_budget import TokenBudgetResolver

    settings = get_settings()
    r = TokenBudgetResolver(
        base=settings.wiki.default_llm_budget,
        ceiling=getattr(settings.llm, "max_context_tokens", 128_000),
    )
    assert r.budget("decomposition") == 30_000
    assert r.budget("decomposition") <= int(128_000 * 0.8)


def test_available_input_default():
    calc = TokenBudgetCalculator()
    assert calc.available_input == 128_000 - 4_096 - 2_000


def test_available_input_custom_window():
    calc = TokenBudgetCalculator(context_window=32_000)
    assert calc.available_input == 32_000 - 4_096 - 2_000


def test_budget_for_snippets_small_domain():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(3) == 500 + int(300 * math.log2(4))


def test_budget_for_snippets_large_domain_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(100) < 6000  # logarithmic, below old linear cap


def test_budget_for_snippets_logarithmic():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(1) == 500 + int(300 * math.log2(2))  # 800
    assert calc.budget_for_snippets(5) == 500 + int(300 * math.log2(6))  # ~1275
    assert calc.budget_for_snippets(55) < 6000  # was 6000 with old formula
    assert calc.budget_for_snippets(100) < calc.budget_for_snippets(200)  # still growing
    assert calc.budget_for_snippets(50_000_000) == 8000  # cap


def test_budget_for_parent_summaries():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_parent_summaries(3) == 900


def test_budget_for_parent_summaries_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_parent_summaries(20) == 5000


def test_budget_for_system_overview():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_system_overview(10) == 2000


def test_budget_for_system_overview_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_system_overview(50) == 8000


class TestCrossComponentTracking:
    """Task 17: Cross-component budget tracking."""

    def test_initial_consumed_is_empty(self):
        r = TokenBudgetResolver(base=30_000)
        assert r._consumed == {}

    def test_claim_returns_requested_when_budget_available(self):
        r = TokenBudgetResolver(base=30_000)
        # decomposition has ratio 1.0 → 30_000 budget
        assert r.claim("decomposition", 1000) == 1000

    def test_claim_caps_at_remaining_budget(self):
        r = TokenBudgetResolver(base=30_000)
        # compact has ratio 0.13 → 3_900 budget
        r.claim("compact", 3000)
        remaining = r.remaining("compact")
        assert r.claim("compact", remaining + 500) == remaining

    def test_claim_deducts_from_remaining(self):
        r = TokenBudgetResolver(base=30_000)
        budget = r.budget("assembly")  # 8100
        r.claim("assembly", 2000)
        assert r.remaining("assembly") == budget - 2000
        r.claim("assembly", 1000)
        assert r.remaining("assembly") == budget - 3000

    def test_remaining_returns_full_budget_initially(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.remaining("topic_page_generate") == r.budget("topic_page_generate")

    def test_components_track_independently(self):
        r = TokenBudgetResolver(base=30_000)
        r.claim("compact", 1000)
        assert r.remaining("compact") == r.budget("compact") - 1000
        # Other component unaffected
        assert r.remaining("assembly") == r.budget("assembly")

    def test_claim_zero_returns_zero(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.claim("compact", 0) == 0

    def test_remaining_unknown_component_returns_budget(self):
        r = TokenBudgetResolver(base=30_000)
        assert r.remaining("unknown_component") == r.budget("unknown_component")

    def test_drain_budget_entirely(self):
        r = TokenBudgetResolver(base=30_000)
        budget = r.budget("compact")
        r.claim("compact", budget)
        assert r.remaining("compact") == 0
        assert r.claim("compact", 100) == 0


def test_budget_for_snippets_at_old_cap_boundary():
    """Logarithmic formula grows slower than old linear 100/module."""
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(30) < 500 + 30 * 100


def test_budget_for_snippets_mid_range():
    """Verify logarithmic budget stays below old linear cap for large domains."""
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(55) < 6000
    assert calc.budget_for_snippets(56) < 6000
