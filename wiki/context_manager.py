"""Context trimming for explore phase messages.

Replaces the hard message reset (>30 msgs → discard all) with gradual
compression of old tool results while preserving recent rounds fully.
"""
from __future__ import annotations


class ContextManager:
    """Trim explore messages to fit context budget."""

    def __init__(
        self,
        max_context_chars: int = 60000,
        keep_recent_rounds: int = 3,
    ) -> None:
        self._max_chars = max_context_chars
        self._keep_recent = keep_recent_rounds

    def trim(self, messages: list[dict]) -> list[dict]:
        """Trim messages if total chars exceed 80% of max budget.

        Strategy:
        - Always keep system prompt (messages[0])
        - Always keep most recent N round-trips fully
        - Compress older tool results to head+tail summary
        """
        total_chars = self._total_chars(messages)
        if total_chars <= self._max_chars * 0.8:
            return messages

        boundary = self._find_recent_boundary(messages)
        trimmed: list[dict] = [messages[0]]

        for msg in messages[1:boundary]:
            if msg.get("role") == "tool":
                content = msg.get("content") or ""
                trimmed.append({
                    **msg,
                    "content": self._compress(content),
                })
            else:
                trimmed.append(msg)

        trimmed.extend(messages[boundary:])
        return trimmed

    def _find_recent_boundary(self, messages: list[dict]) -> int:
        """Find boundary index: count by assistant messages (= one reasoning round)."""
        round_count = 0
        for i in range(len(messages) - 1, 0, -1):
            if messages[i].get("role") == "assistant":
                round_count += 1
                if round_count >= self._keep_recent:
                    return i
        return 1

    def _compress(self, content: str) -> str:
        if len(content) <= 500:
            return content
        return content[:200] + "\n...[compressed]...\n" + content[-200:]

    @staticmethod
    def _total_chars(messages: list[dict]) -> int:
        return sum(len(m.get("content") or "") for m in messages)
