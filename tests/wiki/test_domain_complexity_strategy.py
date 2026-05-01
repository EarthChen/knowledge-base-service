from __future__ import annotations

import pytest

from wiki.domain_complexity import DomainComplexity, DomainComplexityScorer


def test_high_complexity_recommends_reasoning() -> None:
    scorer = DomainComplexityScorer(low_threshold=10.0, high_threshold=30.0)
    domain = {
        "biz_entities": [
            {"methods": list(range(20)), "calls": list(range(15)), "loc": 2000}
            for _ in range(10)
        ]
    }
    m = scorer.score(domain)
    assert m.complexity == DomainComplexity.HIGH
    assert m.recommended_strategy.model_task_type == "reasoning"
    assert m.recommended_strategy.max_reasoning_depth == 7


def test_low_complexity_recommends_generation() -> None:
    scorer = DomainComplexityScorer()
    domain = {"biz_entities": [{"methods": ["a"], "calls": [], "loc": 50}]}
    m = scorer.score(domain)
    assert m.complexity == DomainComplexity.LOW
    assert m.recommended_strategy.model_task_type == "generation"
    assert m.recommended_strategy.page_structure == "flat"
