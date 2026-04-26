"""WikiPage embeddings: persist-time generation and direct vector search."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import NodeLabel
from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructure, WikiStructureNode
from wiki.search import WikiSearchService
from tests.wiki_config_inject import wiki_service_injection
from wiki.service import WikiService


def _overview_page() -> WikiPage:
    return WikiPage(
        path="README.md",
        title="myrepo",
        page_type=PageType.REPO_OVERVIEW,
        content="# myrepo\nbody text for embedding",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_persist_pages_to_graph_generates_embeddings_after_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    store.set_node_embedding = AsyncMock()

    fake_gen = MagicMock()
    fake_gen.generate_for_docs = AsyncMock(return_value=[[0.1, 0.2, 0.3]])

    def fake_shared(**_kwargs: object) -> MagicMock:
        return fake_gen

    monkeypatch.setattr("indexer.embedding_generator.EmbeddingGenerator.shared", fake_shared)
    monkeypatch.setattr("wiki.service.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.service.set_wiki_page_confidence_scores", AsyncMock())

    graph = AsyncMock()
    svc = WikiService(
        graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store,
        **wiki_service_injection(),
    )

    await svc._persist_pages_to_graph("r1", [_overview_page()])

    store.persist_wiki_pages.assert_awaited_once()
    fake_gen.generate_for_docs.assert_awaited_once()
    store.set_node_embedding.assert_awaited_once()
    uid, label, emb = store.set_node_embedding.await_args.args
    assert uid == "WikiPage:r1:README.md"
    assert label == NodeLabel.WIKI_PAGE
    assert emb == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_persist_pages_skips_embeddings_when_persist_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(side_effect=RuntimeError("down"))
    store.set_node_embedding = AsyncMock()

    fake_gen = MagicMock()
    fake_gen.generate_for_docs = AsyncMock(return_value=[[0.1]])

    monkeypatch.setattr("indexer.embedding_generator.EmbeddingGenerator.shared", lambda **_k: fake_gen)
    monkeypatch.setattr("wiki.service.gather_confidence_inputs", AsyncMock())
    monkeypatch.setattr("wiki.service.set_wiki_page_confidence_scores", AsyncMock())

    graph = AsyncMock()
    svc = WikiService(
        graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store,
        **wiki_service_injection(),
    )

    await svc._persist_pages_to_graph("r1", [_overview_page()])

    fake_gen.generate_for_docs.assert_not_called()
    store.set_node_embedding.assert_not_called()


@pytest.mark.asyncio
async def test_search_semantic_uses_direct_wikipage_vector_when_embedding_gen() -> None:
    wiki_node = MagicMock()
    wiki_node.properties = {
        "path": "modules/a.md",
        "title": "Mod A",
        "content": "full content here",
    }
    graph = AsyncMock()
    graph.execute_query = AsyncMock(
        return_value=MagicMock(
            data=[
                {"node": wiki_node, "score": 0.92},
            ]
        )
    )
    vector = AsyncMock()
    vector.search_all = AsyncMock(return_value=[])
    fts = AsyncMock()

    emb = MagicMock()
    emb.generate_for_query = AsyncMock(return_value=[[0.5] * 4])

    svc = WikiSearchService(graph, vector, fts, embedding_gen=emb)
    resp = await svc.search("repo1", "auth flow", mode="semantic", limit=5)

    emb.generate_for_query.assert_awaited_once()
    cy_args = graph.execute_query.await_args
    assert cy_args is not None
    cypher = cy_args.args[0]
    assert "db.idx.vector.queryNodes" in cypher
    assert "WikiPage" in cypher
    params = cy_args.args[1]
    assert params["repository"] == "repo1"
    assert params["vec"] == [0.5] * 4
    vector.search_all.assert_not_called()
    assert len(resp.results) >= 1
    assert resp.results[0].page_path == "modules/a.md"
    assert resp.results[0].title == "Mod A"


@pytest.mark.asyncio
async def test_search_semantic_falls_back_to_code_vector_when_no_embedding_gen() -> None:
    graph = AsyncMock()
    graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    vector = AsyncMock()
    vector.search_all = AsyncMock(
        return_value=[{"page_path": "classes/Foo.md", "title": "Foo", "score": 0.8}]
    )
    fts = AsyncMock()

    svc = WikiSearchService(graph, vector, fts)
    resp = await svc.search("repo1", "query", mode="semantic", limit=5)

    vector.search_all.assert_awaited()
    graph.execute_query.assert_not_awaited()
    assert resp.results and resp.results[0].page_path == "classes/Foo.md"
