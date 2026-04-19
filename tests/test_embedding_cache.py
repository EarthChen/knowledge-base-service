"""Tests for query embedding LRU cache on EmbeddingGenerator."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from config import EmbeddingConfig
from indexer.embedding_generator import QUERY_EMBEDDING_CACHE_SIZE, EmbeddingGenerator


@pytest.mark.asyncio
async def test_same_query_returns_cached_embedding_vector() -> None:
    gen = EmbeddingGenerator(EmbeddingConfig())
    vec = [0.1, 0.2, 0.3]
    mock_generate = AsyncMock(return_value=[vec])

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen, "generate", mock_generate)
        out1 = await gen.generate_for_query(["same query"])
        out2 = await gen.generate_for_query(["same query"])

    assert out1[0] is out2[0]
    assert mock_generate.await_count == 1


@pytest.mark.asyncio
async def test_query_cache_respects_max_size() -> None:
    gen = EmbeddingGenerator(EmbeddingConfig())
    counter = {"n": 0}

    async def fake_generate(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        out: list[list[float]] = []
        for _ in texts:
            counter["n"] += 1
            out.append([float(counter["n"])])
        return out

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen, "generate", fake_generate)

        for i in range(QUERY_EMBEDDING_CACHE_SIZE):
            await gen.generate_for_query([f"unique-{i}"])

        first_key = "unique-0"
        assert first_key in gen._query_embedding_cache

        await gen.generate_for_query([f"unique-{QUERY_EMBEDDING_CACHE_SIZE}"])

        assert first_key not in gen._query_embedding_cache
