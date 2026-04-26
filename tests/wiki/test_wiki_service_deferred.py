"""WikiService integration with deferred graph enrichment."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructure, WikiStructureNode
from tests.wiki_config_inject import wiki_service_injection
from wiki.service import WikiService


def _overview_page() -> WikiPage:
    return WikiPage(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        content="# r1\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_generate_calls_deferred_enrichment() -> None:
    deferred = MagicMock()
    deferred.enrich_remaining = AsyncMock(return_value=3)
    deferred.refresh_stale_embeddings = AsyncMock(return_value=2)

    graph = AsyncMock()
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        deferred_enrichment=deferred,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_overview_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    deferred.enrich_remaining.assert_awaited_once_with("r1")
    deferred.refresh_stale_embeddings.assert_awaited_once_with("r1")


@pytest.mark.asyncio
async def test_generate_calls_enrich_before_compose() -> None:
    order: list[str] = []

    deferred = MagicMock()

    async def enrich_side(repo: str) -> int:
        order.append("enrich")
        return 0

    deferred.enrich_remaining = AsyncMock(side_effect=enrich_side)
    deferred.refresh_stale_embeddings = AsyncMock(
        side_effect=lambda repo: order.append("refresh") or 0,
    )

    graph = AsyncMock()
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        deferred_enrichment=deferred,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)

    async def compose_side(*_a: object, **_k: object) -> tuple[list[WikiPage], bool]:
        order.append("compose")
        return ([_overview_page()], False)

    svc._compose_all_pages = AsyncMock(side_effect=compose_side)
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    assert order == ["enrich", "compose", "refresh"]


@pytest.mark.asyncio
async def test_generate_without_deferred() -> None:
    graph = AsyncMock()
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)

    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        **wiki_service_injection(),
    )

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_overview_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    svc._compose_all_pages.assert_awaited_once()
