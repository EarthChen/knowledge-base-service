"""Tests for optional bge-m3 query instruction prefix on EmbeddingGenerator."""

from __future__ import annotations

import pytest

from core.config import EmbeddingConfig
from indexer.embedding_generator import EmbeddingGenerator


@pytest.mark.asyncio
async def test_generate_prepends_prefix_for_query_when_configured() -> None:
    """Prefix is applied in generate() when is_query=True (embedding_generator.py:500-501)."""
    prefix = "Represent this sentence for searching relevant passages: "
    gen = EmbeddingGenerator(EmbeddingConfig(query_prefix=prefix))
    captured: list[str] = []

    def capture_encode(texts: list[str]) -> list[list[float]]:
        captured.extend(texts)
        return [[0.1] for _ in texts]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen, "_encode_single_chunk", capture_encode)
        await gen.generate(["user question"], is_query=True)

    assert captured == [f"{prefix}user question"]


@pytest.mark.asyncio
async def test_generate_no_prefix_when_empty() -> None:
    gen = EmbeddingGenerator(EmbeddingConfig(query_prefix=""))
    captured: list[str] = []

    def capture_encode(texts: list[str]) -> list[list[float]]:
        captured.extend(texts)
        return [[0.1] for _ in texts]

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(gen, "_encode_single_chunk", capture_encode)
        await gen.generate(["user question"], is_query=True)

    assert captured == ["user question"]
