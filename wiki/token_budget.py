from __future__ import annotations


class TokenBudgetResolver:
    """Derives per-component token budgets from a single base value.

    Each component's budget = base * ratio, capped at ceiling * 0.8.
    A floor of 512 prevents degenerate budgets on very small base values.

    If *base* is ``None`` (or 0), it is auto-derived from *ceiling* using
    ``CONTEXT_BUDGET_RATIO`` so that the user only needs to configure the
    model's context window size.
    """

    RATIOS: dict[str, float] = {
        "decomposition": 1.0,
        "ask_concept": 0.33,
        "ask_flow": 0.40,
        "ask_relation": 0.27,
        "ask_impact": 0.33,
        "ask_general": 0.27,
        "compact": 0.13,
        "assembly": 0.27,
    }
    _FLOOR = 512
    CONTEXT_BUDGET_RATIO = 0.23
    _AUTO_BUDGET_FLOOR = 4_000
    _AUTO_BUDGET_CAP = 60_000

    def __init__(self, base: int | None = None, ceiling: int | None = None):
        if not base and ceiling:
            base = max(
                self._AUTO_BUDGET_FLOOR,
                min(int(ceiling * self.CONTEXT_BUDGET_RATIO), self._AUTO_BUDGET_CAP),
            )
        elif not base:
            base = 30_000
        self._base = base
        self._ceiling = int(ceiling * 0.8) if ceiling else None

    def budget(self, component: str) -> int:
        ratio = self.RATIOS.get(component, 0.27)
        raw = int(self._base * ratio)
        raw = max(raw, self._FLOOR)
        if self._ceiling:
            return min(raw, self._ceiling)
        return raw

    def ask_budget(self, question_type: str | None = None) -> int:
        key = f"ask_{question_type or 'general'}"
        return self.budget(key)
