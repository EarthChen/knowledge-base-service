"""Entity importance scoring for tiered wiki generation."""

from __future__ import annotations

import logging
import math
from typing import Any

from wiki.models import ImportanceTier

logger = logging.getLogger(__name__)


class ImportanceScorer:
    """Scores entities by graph metrics and classifies into importance tiers."""

    def __init__(
        self,
        wiki_store: Any,
        core_percentile: int = 80,
        standard_percentile: int = 30,
    ) -> None:
        self._store = wiki_store
        self._core_pct = core_percentile
        self._standard_pct = standard_percentile

    async def score_all(self, repository: str) -> dict[str, ImportanceTier]:
        result = await self._store.score_all_entities(repository)
        if not result or not result.result_set:
            return {}

        scores: dict[str, float] = {}
        for row in result.result_set:
            uid, label, start_line, end_line, in_deg, out_deg, children, subclass_count = row
            code_lines = max(0, int(end_line) - int(start_line))
            has_subclasses = str(label) == "Class" and int(subclass_count) > 0
            scores[str(uid)] = self.compute_score(
                label=str(label),
                in_degree=int(in_deg),
                out_degree=int(out_deg),
                children_count=int(children),
                code_lines=code_lines,
                has_subclasses=has_subclasses,
            )

        return self.classify_by_percentile(scores)

    def compute_score(
        self,
        label: str,
        in_degree: int,
        out_degree: int,
        children_count: int,
        code_lines: int,
        has_subclasses: bool,
    ) -> float:
        score = (
            (in_degree * 3)
            + (out_degree * 1)
            + (children_count * 2)
            + math.log2(code_lines + 1) * 2
        )
        if label == "Module":
            score += 5
        if label == "Class" and has_subclasses:
            score += 3
        return score

    def classify_by_percentile(self, scores: dict[str, float]) -> dict[str, ImportanceTier]:
        if not scores:
            return {}
        sorted_scores = sorted(scores.values())
        n = len(sorted_scores)

        def _rank_index(pct: int) -> int:
            # Nearest-rank style index so small N and task examples behave sensibly.
            return max(0, min(n - 1, math.ceil(n * pct / 100) - 1))

        core_threshold = sorted_scores[_rank_index(self._core_pct)]
        standard_threshold = sorted_scores[_rank_index(self._standard_pct)]

        result: dict[str, ImportanceTier] = {}
        for uid, score in scores.items():
            if score >= core_threshold:
                result[uid] = ImportanceTier.CORE
            elif score >= standard_threshold:
                result[uid] = ImportanceTier.STANDARD
            else:
                result[uid] = ImportanceTier.SKELETON
        return result
