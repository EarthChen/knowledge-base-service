"""Per-page confidence score (LLM Wiki v2 Phase 2 / SP3)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple


class WeightBundle(NamedTuple):
    w1: float
    w2: float
    w3: float
    w4: float
    w5: float


DEFAULT_WEIGHTS = WeightBundle(0.30, 0.25, 0.25, 0.20, 1.0)


@dataclass(frozen=True)
class ConfidenceInputs:
    source_entity_count: int
    days_since_generated: int
    up_votes: int
    down_votes: int
    inbound_wikilink_count: int
    contradiction_count: int


class ConfidenceScorer:
    def __init__(self, weights: WeightBundle = DEFAULT_WEIGHTS) -> None:
        self._w = weights

    def compute(self, x: ConfidenceInputs) -> float:
        source = min(x.source_entity_count / 3, 1.0)
        fresh = max(1.0 - x.days_since_generated / 90, 0.0)
        total_fb = x.up_votes + x.down_votes + 1
        feedback = x.up_votes / total_fb
        refs = min(x.inbound_wikilink_count / 5, 1.0)
        penalty = x.contradiction_count * 0.15
        raw = (
            self._w.w1 * source
            + self._w.w2 * fresh
            + self._w.w3 * feedback
            + self._w.w4 * refs
            - self._w.w5 * penalty
        )
        return max(0.0, min(1.0, raw))
