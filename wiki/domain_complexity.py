"""Domain complexity scoring for adaptive wiki composition depth."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class DomainComplexity(str, Enum):
    LOW = "low"  # 单页轻量处理
    MEDIUM = "medium"  # 概览+子页标准处理
    HIGH = "high"  # 多轮深度composition


@dataclass
class ComplexityMetrics:
    entity_count: int
    total_methods: int
    total_calls: int
    total_loc: int
    max_entity_methods: int
    raw_score: float
    complexity: DomainComplexity


class DomainComplexityScorer:
    """根据域内实体的多维度指标评估域复杂度。

    借鉴 CodeWiki (ACL 2026) 的动态规划策略，
    根据复杂度动态调整文档生成深度和token预算。
    """

    def __init__(self, *, low_threshold: float = 10.0, high_threshold: float = 30.0) -> None:
        self._low = low_threshold
        self._high = high_threshold

    def score(self, domain: dict[str, Any]) -> ComplexityMetrics:
        entities = domain.get("biz_entities", [])
        entity_count = len(entities)
        total_methods = sum(len(e.get("methods", [])) for e in entities)
        total_calls = sum(len(e.get("calls", [])) for e in entities)
        total_loc = sum(int(e.get("loc", 0) or 0) for e in entities)
        max_entity_methods = max((len(e.get("methods", [])) for e in entities), default=0)

        raw_score = (
            entity_count * 1.0
            + total_methods * 0.3
            + total_calls * 0.2
            + total_loc / 500 * 0.5
            + (1.0 if max_entity_methods > 15 else 0)
        )

        if raw_score > self._high:
            complexity = DomainComplexity.HIGH
        elif raw_score > self._low:
            complexity = DomainComplexity.MEDIUM
        else:
            complexity = DomainComplexity.LOW

        return ComplexityMetrics(
            entity_count=entity_count,
            total_methods=total_methods,
            total_calls=total_calls,
            total_loc=total_loc,
            max_entity_methods=max_entity_methods,
            raw_score=raw_score,
            complexity=complexity,
        )
