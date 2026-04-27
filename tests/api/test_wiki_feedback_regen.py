from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest


def test_feedback_loop_exists_in_module():
    """Verify feedback loop module can be imported."""
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    assert FeedbackDrivenRegeneration is not None


@pytest.mark.asyncio
async def test_feedback_regen_on_down_vote():
    """Integration: on_feedback returns a meaningful result."""
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    class _FakeResult:
        def __init__(self, data):
            self.data = data

    class _FakeGraph:
        async def execute_query(self, cypher, params=None):
            if "last_feedback_regen_at" in cypher:
                return _FakeResult([{"ts": None}])
            if "count(f)" in cypher:
                return _FakeResult([{"c": 3}])
            return _FakeResult([])

    cfg = MagicMock()
    cfg.feedback_regen_enabled = True
    cfg.feedback_regen_threshold = 3
    cfg.feedback_regen_batch_token_multiplier = 1.2
    cfg.feedback_regen_cooldown_hours = 24
    cfg.feedback_regen_critical_immediate = True

    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(
        graph=_FakeGraph(), wiki_config=cfg, enqueue_regenerate=enqueue
    )
    result = await loop.on_feedback("p1", "b1", "down")
    assert result["action"] == "queued"
