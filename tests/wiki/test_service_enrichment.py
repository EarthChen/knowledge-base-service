"""WikiService integration with async enrichment and enrichment_level metadata."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
)
from wiki.service import WikiService


def _mock_graph() -> AsyncMock:
    g = AsyncMock()
    g.find_modules = AsyncMock(return_value=[])
    g.find_children = AsyncMock(return_value=[])
    g.find_edges = AsyncMock(return_value=[])
    g.find_node_by_fqn = AsyncMock(return_value=None)
    g.find_node_by_path = AsyncMock(
        return_value=MagicMock(
            uid="Module:test:TestModule",
            label=NodeLabel.MODULE,
            properties={"name": "TestModule", "path": "test_module"},
        )
    )
    return g


@pytest.mark.asyncio
async def test_compose_all_pages_sets_base_enrichment() -> None:
    """All composed pages should get enrichment_level=BASE initially."""
    graph = _mock_graph()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
    )
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    pages, _ = await svc._compose_all_pages("test-repo", structure, config, composer)
    for page in pages:
        assert page.metadata.enrichment_level is not None
        assert page.metadata.enrichment_level == EnrichmentLevel.BASE


@pytest.mark.asyncio
async def test_compose_all_pages_runs_enrichment_when_llm_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    graph = _mock_graph()
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Extra\nEnriched block.")
    svc = WikiService(
        graph=graph,
        llm=llm,
        repository_exists=AsyncMock(return_value=True),
    )
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="test_module",
                    title="TestModule",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    composer = WikiComposer(llm=llm, context_builder=WikiContextBuilder(llm), store=graph)

    fake_settings = MagicMock()
    fake_settings.wiki.enrichment_enabled = True
    fake_settings.wiki.enrichment_round1_enabled = True
    fake_settings.wiki.enrichment_round2_enabled = True
    monkeypatch.setattr("wiki.service.get_settings", lambda: fake_settings)

    tiers = {"Module:test:TestModule": ImportanceTier.STANDARD}
    pages, _ = await svc._compose_all_pages(
        "test-repo", structure, config, composer, tiers, None,
    )
    assert len(pages) == 2
    overview = next(p for p in pages if p.page_type == PageType.REPO_OVERVIEW)
    mod_page = next(p for p in pages if p.page_type == PageType.MODULE_OVERVIEW)
    assert overview.metadata.enrichment_level == EnrichmentLevel.BASE
    assert mod_page.metadata.enrichment_level == EnrichmentLevel.ENRICHED
    assert "Enriched block" in mod_page.content


@pytest.mark.asyncio
async def test_persist_pages_includes_enrichment_level(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    fake_gen = MagicMock()
    fake_gen.generate_for_docs = AsyncMock(return_value=[[0.01]])
    monkeypatch.setattr("indexer.embedding_generator.EmbeddingGenerator.shared", lambda **_k: fake_gen)

    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
    )
    page = WikiPage(
        path="a.md",
        title="T",
        page_type=PageType.MODULE_OVERVIEW,
        content="x",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=1,
            edge_count=0,
            enrichment_level=EnrichmentLevel.BASE,
        ),
    )
    await svc._persist_pages_to_graph("repo1", [page])
    _repo, dicts = store.persist_wiki_pages.await_args.args
    assert dicts[0]["enrichment_level"] == EnrichmentLevel.BASE
