from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.memory_loop import MemoryLoop


def _search_result(rows: list[dict[str, object]]) -> MagicMock:
    return MagicMock(data=rows)


@pytest.mark.asyncio
async def test_get_relevant_memories_records_access():
    """After retrieving memories, access should be tracked (M-02, M-06)."""
    store_mock = MagicMock()
    store_mock.search_wiki_qa = AsyncMock(
        return_value=_search_result(
            [
                {
                    "uid": "qa-123",
                    "question": "Q?",
                    "answer": "A.",
                    "source_pages": "[]",
                    "quality_score": 0.8,
                    "created_at": "2025-01-01T00:00:00Z",
                    "similarity": 0.9,
                }
            ]
        )
    )
    store_mock.increment_wiki_qa_access = AsyncMock()

    async def embed(_: str) -> list[float]:
        return [1.0]

    loop = MemoryLoop(store_mock, embed)
    entries = await loop.get_relevant_memories("test topic", limit=5)

    assert len(entries) == 1
    store_mock.increment_wiki_qa_access.assert_called_once()
    call_kwargs = store_mock.increment_wiki_qa_access.call_args.kwargs
    assert call_kwargs["uid"] == "qa-123"
    assert "at_iso" in call_kwargs


@pytest.mark.asyncio
async def test_access_tracking_skips_entries_without_uid():
    """Entries without uid should not cause tracking errors."""
    store_mock = MagicMock()
    store_mock.search_wiki_qa = AsyncMock(
        return_value=_search_result(
            [
                {
                    "uid": "",
                    "question": "Q1?",
                    "answer": "A1.",
                    "source_pages": "[]",
                    "quality_score": 0.8,
                    "created_at": "2025-01-01T00:00:00Z",
                    "similarity": 0.9,
                },
                {
                    "uid": "qa-456",
                    "question": "Q2?",
                    "answer": "A2.",
                    "source_pages": "[]",
                    "quality_score": 0.8,
                    "created_at": "2025-01-01T00:00:00Z",
                    "similarity": 0.8,
                },
            ]
        )
    )
    store_mock.increment_wiki_qa_access = AsyncMock()

    async def embed(_: str) -> list[float]:
        return [1.0]

    loop = MemoryLoop(store_mock, embed)
    entries = await loop.get_relevant_memories("test topic", limit=5)

    assert len(entries) == 2
    store_mock.increment_wiki_qa_access.assert_called_once()
    assert store_mock.increment_wiki_qa_access.call_args.kwargs["uid"] == "qa-456"
