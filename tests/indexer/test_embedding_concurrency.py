"""Tests for separate query/index embedding semaphores."""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from core.config import EmbeddingConfig
from indexer.embedding_generator import EmbeddingGenerator


@pytest.mark.asyncio
async def test_query_and_index_semaphores_are_independent() -> None:
    config = EmbeddingConfig(query_concurrency=2, index_concurrency=1)
    gen = EmbeddingGenerator(config)

    query_sem = gen._get_query_semaphore()
    index_sem = gen._get_index_semaphore()

    assert query_sem is not index_sem
    assert query_sem._value == 2
    assert index_sem._value == 1


@pytest.mark.asyncio
async def test_generate_acquires_index_semaphore_not_query() -> None:
    config = EmbeddingConfig(query_concurrency=2, index_concurrency=1)
    gen = EmbeddingGenerator(config)
    acquired: list[str] = []

    original_index_acquire = gen._get_index_semaphore().acquire
    original_query_acquire = gen._get_query_semaphore().acquire

    async def track_index_acquire() -> None:
        acquired.append("index")
        await original_index_acquire()

    async def track_query_acquire() -> None:
        acquired.append("query")
        await original_query_acquire()

    gen._get_index_semaphore().acquire = track_index_acquire  # type: ignore[method-assign]
    gen._get_query_semaphore().acquire = track_query_acquire  # type: ignore[method-assign]
    gen._encode_single_chunk = MagicMock(return_value=[[0.1, 0.2]])  # type: ignore[method-assign]

    await gen.generate(["index text"], is_query=False)

    assert "index" in acquired
    assert "query" not in acquired


@pytest.mark.asyncio
async def test_generate_for_query_acquires_query_semaphore_not_index() -> None:
    config = EmbeddingConfig(query_concurrency=2, index_concurrency=1)
    gen = EmbeddingGenerator(config)
    acquired: list[str] = []

    original_index_acquire = gen._get_index_semaphore().acquire
    original_query_acquire = gen._get_query_semaphore().acquire

    async def track_index_acquire() -> None:
        acquired.append("index")
        await original_index_acquire()

    async def track_query_acquire() -> None:
        acquired.append("query")
        await original_query_acquire()

    gen._get_index_semaphore().acquire = track_index_acquire  # type: ignore[method-assign]
    gen._get_query_semaphore().acquire = track_query_acquire  # type: ignore[method-assign]
    gen._encode_single_chunk = MagicMock(return_value=[[0.1, 0.2]])  # type: ignore[method-assign]

    await gen.generate_for_query(["search query"])

    assert "query" in acquired
    assert "index" not in acquired


@pytest.mark.asyncio
async def test_http_backend_uses_http_max_concurrency_for_both() -> None:
    config = EmbeddingConfig(
        backend="http",
        http_base_url="http://localhost:9999",
        http_model="test",
        http_max_concurrency=4,
        query_concurrency=2,
        index_concurrency=1,
    )
    gen = EmbeddingGenerator(config)

    query_sem = gen._get_query_semaphore()
    index_sem = gen._get_index_semaphore()

    assert query_sem._value == 4
    assert index_sem._value == 4


@pytest.mark.asyncio
async def test_concurrent_query_embeddings_respect_config() -> None:
    config = EmbeddingConfig(query_concurrency=2, index_concurrency=1, chunk_size=1)
    gen = EmbeddingGenerator(config)

    in_flight = 0
    max_in_flight = 0
    lock = asyncio.Lock()

    async def slow_generate(texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        nonlocal in_flight, max_in_flight
        sem = gen._get_query_semaphore() if is_query else gen._get_index_semaphore()
        async with sem:
            async with lock:
                in_flight += 1
                max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.05)
            async with lock:
                in_flight -= 1
        return [[0.1] * 3 for _ in texts]

    gen.generate = slow_generate  # type: ignore[method-assign]

    await asyncio.gather(*[gen.generate_for_query([f"q-{i}"]) for i in range(4)])
    assert max_in_flight <= 2
