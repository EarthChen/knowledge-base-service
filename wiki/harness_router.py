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
        "max_chars_per_section": 6000,
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
    use_l2_benchmark: bool
    use_l3_llm_judge: bool = False

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
                use_l2_benchmark=True,
            )
        elif module_count <= self.simple_threshold and edge_count < 5:
            return ComplexityAssessment(
                level="simple",
                max_tool_calls=5,
                generation_mode="whole_page",
                max_repair_rounds=0,
                use_l2_benchmark=False,
            )
        else:
            return ComplexityAssessment(
                level="moderate",
                max_tool_calls=10,
                generation_mode="whole_page",
                max_repair_rounds=1,
                use_l2_benchmark=False,
            )
