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
    assert calc.budget_for_snippets(3) == 500 + 3 * 100  # 800


def test_budget_for_snippets_large_domain_capped():
    calc = TokenBudgetCalculator()
    assert calc.budget_for_snippets(100) == 3000  # capped


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
