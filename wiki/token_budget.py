from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class TokenBudgetCalculator:
    context_window: int = 128_000
    reserved_output: int = 4_096
    reserved_system: int = 2_000

    @property
    def available_input(self) -> int:
        return self.context_window - self.reserved_output - self.reserved_system

    def budget_for_snippets(self, module_count: int) -> int:
        return min(500 + int(300 * math.log2(max(module_count, 1) + 1)), 8000)

    def budget_for_parent_summaries(self, child_count: int) -> int:
        return min(child_count * 300, 5000)

    def budget_for_system_overview(self, domain_count: int) -> int:
        return min(domain_count * 200, 8000)


# Fallback max_tokens when no budget_resolver is injected (matches legacy hardcoded values).
STAGE_FALLBACK_TOKENS: dict[str, int] = {
    "topic_plan": 2000,
    "arch_classify": 500,
    "module_title": 200,
    "title_generation": 200,
    "leaf_compose": 2000,
}

STAGE_TO_COMPONENT: dict[str, str] = {
    "topic_plan": "domain_tree_plan",
    "arch_classify": "domain_classify",
    "module_title": "entity_group",
    "title_generation": "entity_group",
    "leaf_compose": "topic_page_generate",
}


def resolve_max_tokens(
    budget_resolver: TokenBudgetResolver | None,
    stage: str,
    *,
    tier: str | None = None,
    default: int = 2000,
) -> int:
    """Resolve max_tokens for an LLM call; fall back to legacy hardcoded values."""
    if budget_resolver is None:
        return STAGE_FALLBACK_TOKENS.get(stage, default)
    return budget_resolver.resolve(stage, tier=tier)


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
        "domain_classify": 0.50,
        "domain_merge": 0.20,
        "domain_tree_plan": 0.15,
        "topic_page_generate": 0.60,
        "domain_overview": 0.30,
        "system_overview": 0.25,
        "entity_group": 0.20,
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
        self._consumed: dict[str, int] = {}

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

    def claim(self, component: str, requested: int) -> int:
        """Claim tokens from a component's budget. Returns the amount granted (capped at remaining)."""
        granted = min(requested, self.remaining(component))
        self._consumed[component] = self._consumed.get(component, 0) + granted
        return granted

    def remaining(self, component: str) -> int:
        """Return the remaining unclaimed budget for a component."""
        return self.budget(component) - self._consumed.get(component, 0)

    def resolve(self, stage: str, *, tier: str | None = None) -> int:
        """Map a pipeline stage to a token budget, optionally scaled by importance tier."""
        component = STAGE_TO_COMPONENT.get(stage, stage)
        value = self.budget(component)
        if tier == "core":
            value = int(value * 1.1)
        elif tier == "skeleton":
            value = int(value * 0.8)
        return max(value, self._FLOOR)
