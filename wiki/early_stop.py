"""Smart early stop detection for explore phase.

Detects when consecutive rounds produce no meaningful new information
and signals the explore loop to terminate early.
"""
from __future__ import annotations

import json


class EarlyStopDetector:
    """Detect consecutive empty/useless rounds in the explore loop."""

    def __init__(self, max_empty_rounds: int = 2) -> None:
        self._max_empty = max_empty_rounds
        self._consecutive_empty = 0

    def should_stop(self, round_results: list[str]) -> bool:
        """Check if this round produced meaningful new information.

        A result is considered empty/useless if:
        - It starts with "[EMPTY_RESULT]"
        - It looks like an error JSON (contains "error" key)
        - The round_results list is empty
        """
        meaningful = [
            r for r in round_results
            if not r.startswith("[EMPTY_RESULT]") and not self._is_error(r)
        ]
        if not meaningful:
            self._consecutive_empty += 1
        else:
            self._consecutive_empty = 0
        return self._consecutive_empty >= self._max_empty

    def reset(self) -> None:
        self._consecutive_empty = 0

    @staticmethod
    def _is_error(result: str) -> bool:
        try:
            data = json.loads(result)
            return isinstance(data, dict) and "error" in data
        except (json.JSONDecodeError, TypeError):
            return False
