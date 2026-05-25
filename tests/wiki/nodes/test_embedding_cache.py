"""Tests for pipeline embedding cache reuse across decomposition steps."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.domain_semantic_clusterer import DomainSemanticClusterer
from wiki.nodes.graph_domain_decompose import (
    _embedding_clustering,
    _embedding_text_hash,
    _merge_domains_by_embedding,
)


@pytest.mark.asyncio
async def test_embedding_clustering_populates_cache(monkeypatch):
    biz_modules = [("r1", "ModA"), ("r1", "ModB")]
    module_paths = {"ModA": "src/a/ModA.java", "ModB": "src/b/ModB.java"}
    module_summaries: dict = {}

    mock_generator = MagicMock()
    mock_generator.generate = AsyncMock(return_value=[[1.0, 0.0], [0.0, 1.0]])
    monkeypatch.setattr("core.config.get_settings", lambda: MagicMock(embedding=MagicMock()))
    monkeypatch.setattr(
        "indexer.embedding_generator.EmbeddingGenerator.shared",
        lambda _config: mock_generator,
    )

    embedding_cache: dict[str, list[float]] = {}
    communities, embeddings = await _embedding_clustering(
        biz_modules,
        [],
        module_paths,
        module_summaries,
        embedding_cache=embedding_cache,
    )

    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries, module_paths,
    )
    assert len(communities) >= 1
    assert embeddings is not None
    assert mock_generator.generate.await_count == 1
    assert len(embedding_cache) == len(texts)
    for text in texts:
        assert _embedding_text_hash(text) in embedding_cache


@pytest.mark.asyncio
async def test_merge_reuses_embedding_cache(monkeypatch):
    biz_modules = [("r1", "ModA"), ("r1", "ModB")]
    module_paths = {"ModA": "src/a/ModA.java", "ModB": "src/b/ModB.java"}
    module_summaries: dict = {}
    texts = DomainSemanticClusterer.build_embedding_texts(
        biz_modules, module_summaries, module_paths,
    )

    generate_calls: list[list[str]] = []

    async def track_generate(batch):
        generate_calls.append(list(batch))
        return [[float(i), 0.0] for i in range(len(batch))]

    mock_generator = MagicMock()
    mock_generator.generate = AsyncMock(side_effect=track_generate)
    monkeypatch.setattr("core.config.get_settings", lambda: MagicMock(embedding=MagicMock()))
    monkeypatch.setattr(
        "indexer.embedding_generator.EmbeddingGenerator.shared",
        lambda _config: mock_generator,
    )

    embedding_cache: dict[str, list[float]] = {}
    await _embedding_clustering(
        biz_modules,
        [],
        module_paths,
        module_summaries,
        embedding_cache=embedding_cache,
    )
    assert len(generate_calls) == 1
    assert len(embedding_cache) == len(texts)

    domain_mapping = {
        "d1": [("r1", "ModA")],
        "d2": [("r1", "ModB")],
        "d3": [("r1", "ModC")],
    }
    domain_display = {
        "d1": texts[0],
        "d2": texts[1],
        "d3": "unique payment domain label",
    }

    await _merge_domains_by_embedding(
        domain_mapping,
        domain_display,
        similarity_threshold=0.99,
        embedding_cache=embedding_cache,
    )

    assert len(generate_calls) == 2
    assert generate_calls[1] == ["unique payment domain label"]
    assert _embedding_text_hash(texts[0]) in embedding_cache
    assert _embedding_text_hash(texts[1]) in embedding_cache
