from __future__ import annotations

from wiki.context_manager import ContextManager


def _make_messages(n_rounds: int) -> list[dict]:
    """Build messages simulating n agent loop rounds.
    Each round: assistant (reasoning + tool_call) + tool result.
    """
    msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
    for i in range(n_rounds):
        msgs.append({
            "role": "assistant",
            "content": f"thinking round {i}",
            "tool_calls": [{"id": f"t{i}"}],
        })
        msgs.append({"role": "tool", "content": f"result {i}", "tool_call_id": f"t{i}"})
    return msgs


class TestFindRecentBoundary:
    def test_keeps_recent_3_rounds_by_assistant(self):
        msgs = _make_messages(10)
        cm = ContextManager(keep_recent_rounds=3)
        boundary = cm._find_recent_boundary(msgs)
        assert boundary > 1
        kept = [m for m in msgs[boundary:] if m.get("role") == "assistant"]
        assert len([m for m in kept if m.get("content", "").startswith("thinking")]) >= 3

    def test_few_messages_returns_1(self):
        msgs = _make_messages(2)
        cm = ContextManager(keep_recent_rounds=5)
        boundary = cm._find_recent_boundary(msgs)
        assert boundary == 1
