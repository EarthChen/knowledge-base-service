"""Verify wiki Phase 3 behavior when no LLM is configured (degradation path)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import GraphNode, NodeLabel
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
from tests.wiki_config_inject import wiki_service_injection
from wiki.service import WikiService


@pytest.mark.asyncio
async def test_no_llm_pages_get_base_enrichment() -> None:
    """Without LLM, all pages should stay at enrichment_level=BASE."""
    graph = AsyncMock()
    graph.find_modules = AsyncMock(return_value=[])
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_all_referrers_batch = AsyncMock(return_value={})
    graph.find_node_by_path = AsyncMock(
        return_value=MagicMock(
            uid="Module:r:mod",
            label=NodeLabel.MODULE,
            properties={"name": "mod", "path": "mod"},
        )
    )
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        **wiki_service_injection(),
    )
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(path="mod", title="mod", page_type=PageType.MODULE_OVERVIEW),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    pages, _ = await svc._compose_all_pages("test-repo", structure, config, composer)
    for page in pages:
        assert page.metadata.enrichment_level == EnrichmentLevel.BASE


@pytest.mark.asyncio
async def test_no_llm_business_domain_all_infrastructure() -> None:
    """Without LLM, BusinessDomainPlanner classifies all modules as infrastructure."""
    from wiki.business_domain_planner import BusinessDomainPlanner

    planner = BusinessDomainPlanner(llm=None)
    modules = [
        GraphNode(uid="Module:r:a", label=NodeLabel.MODULE, properties={"name": "a"}),
        GraphNode(uid="Module:r:b", label=NodeLabel.MODULE, properties={"name": "b"}),
    ]
    result = await planner.classify("repo", modules)
    assert "__infrastructure__" in result
    assert set(result["__infrastructure__"]) == {"a", "b"}


@pytest.mark.asyncio
async def test_no_llm_enrichment_pipeline_not_instantiated(monkeypatch: pytest.MonkeyPatch) -> None:
    """With no LLM, AsyncEnrichmentPipeline must not be constructed."""

    class ForbiddenPipeline:
        def __init__(self, *args: object, **kwargs: object) -> None:
            raise AssertionError("AsyncEnrichmentPipeline must not be built when LLM is unavailable")

    monkeypatch.setattr("wiki.async_enrichment.AsyncEnrichmentPipeline", ForbiddenPipeline)

    graph = AsyncMock()
    graph.find_modules = AsyncMock(return_value=[])
    graph.find_children = AsyncMock(return_value=[])
    graph.find_edges = AsyncMock(return_value=[])
    graph.find_node_by_fqn = AsyncMock(return_value=None)
    graph.find_all_referrers_batch = AsyncMock(return_value={})
    graph.find_node_by_path = AsyncMock(
        return_value=MagicMock(
            uid="Module:r:mod",
            label=NodeLabel.MODULE,
            properties={"name": "mod", "path": "mod"},
        )
    )
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        **wiki_service_injection(),
    )
    structure = WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(path="mod", title="mod", page_type=PageType.MODULE_OVERVIEW),
            ],
        ),
        total_pages=2,
    )
    config = WikiConfig(repository="test-repo", mode="structure", format="json")
    composer = WikiComposer(llm=None, context_builder=WikiContextBuilder(None), store=graph)
    pages, _ = await svc._compose_all_pages("test-repo", structure, config, composer)
    for page in pages:
        assert page.metadata.enrichment_level == EnrichmentLevel.BASE


@pytest.mark.asyncio
async def test_skeleton_tier_skips_enrichment() -> None:
    """Skeleton tier should skip enrichment and never call the LLM."""
    from wiki.async_enrichment import AsyncEnrichmentPipeline

    llm = AsyncMock()
    pipeline = AsyncEnrichmentPipeline(llm)
    page = WikiPage(
        path="test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content="# Test",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0, enrichment_level=EnrichmentLevel.BASE),
    )
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.SKELETON,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.BASE
    llm.generate.assert_not_awaited()
