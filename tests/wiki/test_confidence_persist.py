"""Persistence of confidence scores after wiki page MERGE and SOURCE_ENTITY batch."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.confidence_scorer import ConfidenceInputs
from wiki.models import PageType, WikiPage, WikiPageMetadata
from tests.wiki_config_inject import inject_wiki_embedding
from wiki.service import WikiService


def _page(path: str = "README.md") -> WikiPage:
    return WikiPage(
        path=path,
        title="t",
        page_type=PageType.REPO_OVERVIEW,
        content="# x\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_persist_graph_writes_confidence_after_source_entity_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    store.execute_query = AsyncMock()
    set_scores = AsyncMock()
    fixed_inputs = ConfidenceInputs(3, 0, 1, 0, 5, 0)
    gather = AsyncMock(return_value=fixed_inputs)
    monkeypatch.setattr("wiki.persistence.set_wiki_page_confidence_scores", set_scores)
    monkeypatch.setattr("wiki.persistence.gather_confidence_inputs", gather)
    fake_gen = MagicMock()
    fake_gen.generate_for_docs = AsyncMock(return_value=[[0.1, 0.2]])
    monkeypatch.setattr("indexer.embedding_generator.EmbeddingGenerator.shared", lambda **_k: fake_gen)

    wcfg, emb = inject_wiki_embedding()
    wiki_cfg = wcfg.model_copy(update={"confidence_scoring_enabled": True})
    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        wiki_config=wiki_cfg,
        embedding_config=emb,
    )

    await svc._persist_pages_to_graph("r1", [_page()])

    gather.assert_awaited_once()
    set_scores.assert_awaited_once()
    call = set_scores.await_args
    assert call is not None
    assert call.kwargs.get("repository") == "r1"
    assert call.args[0] is store
    path_scores = call.args[1]
    assert len(path_scores) == 1
    assert path_scores[0][0] == "README.md"
    expected = 0.3 * 1.0 + 0.25 * 1.0 + 0.25 * 0.5 + 0.20 * 1.0
    assert path_scores[0][1] == pytest.approx(expected, rel=1e-5)
