from wiki.token_budget import TokenBudgetResolver


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
