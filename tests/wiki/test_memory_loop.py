"""Tests for wiki.memory_loop — MemoryEntry, MemoryLoop."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.wiki_store import WikiStore
from wiki.memory_loop import MemoryEntry, MemoryLoop


def _row() -> list[dict[str, object]]:
    return [
        {
            "uid": "u1",
            "question": "What is X?",
            "answer": "X is Y.",
            "source_pages": json.dumps(["a.md"]),
            "quality_score": 0.8,
            "created_at": "2025-01-01T00:00:00Z",
            "similarity": 0.9,
        }
    ]


@pytest.mark.asyncio
async def test_memory_loop_record_persists() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(
        return_value=MagicMock(data=[{"uid": "WikiQA:bi:abc"}]),
    )
    emb_calls: list[str] = []

    async def embed(t: str) -> list[float]:
        emb_calls.append(t)
        return [0.1, 0.2, 0.3]

    ml = MemoryLoop(WikiStore(base), embed, business_id="biz1")
    uid = await ml.record("Q?", "A.", ["p.md"], business_id="biz1")
    assert uid == "WikiQA:bi:abc"
    base.execute_query.assert_awaited()
    assert emb_calls[0] == "Q?\nA."


@pytest.mark.asyncio
async def test_get_relevant_memories() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=_row()))

    async def embed(_: str) -> list[float]:
        return [1.0, 0.0]

    ml = MemoryLoop(WikiStore(base), embed)
    out = await ml.get_relevant_memories("topic", limit=3, business_id="b")
    assert len(out) == 1
    assert isinstance(out[0], MemoryEntry)
    assert out[0].question == "What is X?"


@pytest.mark.asyncio
async def test_inject_into_generation_appends_block() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(return_value=MagicMock(data=_row()))

    async def embed(_: str) -> list[float]:
        return [1.0]

    ml = MemoryLoop(WikiStore(base), embed)
    text = await ml.inject_into_generation("Page about auth", "my-repo")
    assert "Previous Q&A Knowledge" in text
    assert "What is X?" in text


@pytest.mark.asyncio
async def test_get_relevant_memories_skips_expired_when_tiers_enabled() -> None:
    base = MagicMock()
    base.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {
                    "question": "Q1",
                    "answer": "A1",
                    "source_pages": "[]",
                    "quality_score": 0.9,
                    "created_at": "2026-01-01T00:00:00Z",
                    "memory_status": "expired",
                    "tier": 1,
                    "similarity": 0.99,
                },
                {
                    "question": "Q2",
                    "answer": "A2",
                    "source_pages": "[]",
                    "quality_score": 0.5,
                    "created_at": "2026-01-02T00:00:00Z",
                    "memory_status": "active",
                    "tier": 2,
                    "similarity": 0.5,
                },
            ],
        ),
    )

    async def embed(_: str) -> list[float]:
        return [1.0]

    ml = MemoryLoop(WikiStore(base), embed, memory_tiers_enabled=True)
    out = await ml.get_relevant_memories("t", limit=5)
    assert len(out) == 1
    assert out[0].question == "Q2"
