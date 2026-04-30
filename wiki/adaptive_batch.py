"""Self-adaptive batch sizing for LLM calls."""
from __future__ import annotations


class AdaptiveBatchSizer:
    """Dynamically adjust batch size based on LLM response time.

    Halves the batch on timeout (>90s) or failure.
    Grows by 30% when responses are fast (<30s) and at current batch size.
    """

    def __init__(
        self,
        initial_size: int = 80,
        min_size: int = 20,
        max_size: int = 150,
    ) -> None:
        self._min = min_size
        self._max = max_size
        self._current = max(min_size, min(max_size, initial_size))

    def next_size(self) -> int:
        return self._current

    def record(self, batch_size: int, elapsed_s: float, success: bool) -> None:
        if not success or elapsed_s > 90:
            self._current = max(self._min, self._current // 2)
        elif elapsed_s < 30 and batch_size == self._current:
            self._current = min(self._max, int(self._current * 1.3))
