from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BudgetSnapshot:
    total_chars: int
    estimated_tokens: int
    model_limit: int
    usage_ratio: float
    recommended_level: int  # 0-4
    clearable_tool_chars: int


class TokenBudgetManager:
    """Estimates token consumption and recommends compression level."""

    LEVEL_THRESHOLDS = {
        1: 0.50,
        2: 0.65,
        3: 0.75,
        4: 0.95,
    }

    def __init__(
        self,
        model_context_limit: int = 128_000,
        chars_per_token: float = 3.5,
        reserve_for_output: int = 4_000,
    ):
        self._limit = model_context_limit - reserve_for_output
        self._cpt = chars_per_token

    def snapshot(self, messages: list[dict]) -> BudgetSnapshot:
        total_chars = sum(len(m.get("content") or "") for m in messages)
        estimated_tokens = int(total_chars / self._cpt) if self._cpt > 0 else 0
        usage_ratio = estimated_tokens / self._limit if self._limit > 0 else 0.0
        clearable = self.count_clearable_tool_chars(messages, keep_recent_n=3)

        level = 0
        for lvl in sorted(self.LEVEL_THRESHOLDS):
            if usage_ratio >= self.LEVEL_THRESHOLDS[lvl]:
                level = lvl

        return BudgetSnapshot(
            total_chars=total_chars,
            estimated_tokens=estimated_tokens,
            model_limit=self._limit,
            usage_ratio=round(usage_ratio, 4),
            recommended_level=level,
            clearable_tool_chars=clearable,
        )

    def count_clearable_tool_chars(self, messages: list[dict], keep_recent_n: int = 3) -> int:
        tool_indices = [i for i, m in enumerate(messages) if m.get("role") == "tool"]
        if len(tool_indices) <= keep_recent_n:
            return 0
        clearable_indices = tool_indices[:-keep_recent_n]
        return sum(len(messages[i].get("content") or "") for i in clearable_indices)
