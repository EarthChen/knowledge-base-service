from __future__ import annotations

import time
import pytest
from unittest.mock import AsyncMock, MagicMock


class _FakeResult:
    def __init__(self, data):
        self.data = data


class _FakeGraph:
    def __init__(self, responses):
        self._responses = list(responses)
        self._call_idx = 0
        self.queries = []

    async def execute_query(self, cypher, params=None):
        self.queries.append((cypher, params or {}))
        if self._call_idx < len(self._responses):
            r = self._responses[self._call_idx]
            self._call_idx += 1
            return r
        return _FakeResult([])


@pytest.mark.asyncio
async def test_noop_when_disabled():
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    cfg = MagicMock()
    cfg.feedback_regen_enabled = False
    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(graph=MagicMock(), wiki_config=cfg, enqueue_regenerate=enqueue)
    result = await loop.on_feedback("page1", "b1", "down")
    assert result["action"] == "noop"
    enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_skip_non_down():
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    cfg = MagicMock()
    cfg.feedback_regen_enabled = True
    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(graph=MagicMock(), wiki_config=cfg, enqueue_regenerate=enqueue)
    result = await loop.on_feedback("page1", "b1", "up")
    assert result["action"] == "recorded"
    assert result.get("regenerate") is False


@pytest.mark.asyncio
async def test_critical_immediate_regen():
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    cfg = MagicMock()
    cfg.feedback_regen_enabled = True
    cfg.feedback_regen_critical_immediate = True
    cfg.feedback_regen_token_multiplier = 1.5
    cfg.feedback_regen_cooldown_hours = 24

    graph = _FakeGraph(
        [
            _FakeResult([{"ts": None}]),  # last regen timestamp
        ]
    )
    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(graph=graph, wiki_config=cfg, enqueue_regenerate=enqueue)
    result = await loop.on_feedback("page1", "b1", "down", severity="critical")
    assert result["action"] == "queued"
    assert result["priority"] == "high"
    enqueue.assert_called_once()


@pytest.mark.asyncio
async def test_threshold_regen():
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    cfg = MagicMock()
    cfg.feedback_regen_enabled = True
    cfg.feedback_regen_critical_immediate = True
    cfg.feedback_regen_threshold = 3
    cfg.feedback_regen_batch_token_multiplier = 1.2
    cfg.feedback_regen_cooldown_hours = 24

    graph = _FakeGraph(
        [
            _FakeResult([{"ts": None}]),  # last regen
            _FakeResult([{"c": 3}]),  # negative count >= threshold
        ]
    )
    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(graph=graph, wiki_config=cfg, enqueue_regenerate=enqueue)
    result = await loop.on_feedback("page1", "b1", "down", severity="normal")
    assert result["action"] == "queued"
    assert result["priority"] == "normal"


@pytest.mark.asyncio
async def test_cooldown_blocks():
    from wiki.feedback_loop import FeedbackDrivenRegeneration

    cfg = MagicMock()
    cfg.feedback_regen_enabled = True
    cfg.feedback_regen_cooldown_hours = 24

    graph = _FakeGraph(
        [
            _FakeResult([{"ts": time.time() - 60}]),  # last regen was 60s ago (within cooldown)
        ]
    )
    enqueue = AsyncMock()
    loop = FeedbackDrivenRegeneration(graph=graph, wiki_config=cfg, enqueue_regenerate=enqueue)
    result = await loop.on_feedback("page1", "b1", "down", severity="critical")
    assert result["action"] == "skipped"
    assert "cooldown" in result.get("reason", "")
    enqueue.assert_not_called()
