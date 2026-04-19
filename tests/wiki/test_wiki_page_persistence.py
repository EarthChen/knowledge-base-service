"""WikiPage graph persistence (A3): FalkorDBStore.persist_wiki_pages and WikiService integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import FalkorDBStore, QueryResultWrapper
from wiki.models import PageType, WikiPage, WikiPageMetadata, WikiStructure, WikiStructureNode
from wiki.service import WikiService


def _page() -> WikiPage:
    return WikiPage(
        path="README.md",
        title="myrepo",
        page_type=PageType.REPO_OVERVIEW,
        content="# myrepo\n",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_persist_wiki_pages_empty_returns_zero_without_query() -> None:
    store = FalkorDBStore.__new__(FalkorDBStore)
    store.execute_query = AsyncMock()
    n = await FalkorDBStore.persist_wiki_pages(store, "repo1", [])
    assert n == 0
    store.execute_query.assert_not_awaited()


@pytest.mark.asyncio
async def test_persist_wiki_pages_unwind_merge_returns_count() -> None:
    store = FalkorDBStore.__new__(FalkorDBStore)
    store.execute_query = AsyncMock(
        return_value=QueryResultWrapper(data=[{"cnt": 2}], raw=[[2]]),
    )
    pages = [
        {
            "path": "README.md",
            "title": "R",
            "content": "body",
            "page_type": "repo_overview",
            "generated_at": "2026-01-01T00:00:00+00:00",
        },
        {
            "path": "mod.md",
            "title": "M",
            "content": "m",
            "page_type": "module_overview",
            "generated_at": "2026-01-01T00:00:00+00:00",
        },
    ]
    n = await FalkorDBStore.persist_wiki_pages(store, "repo1", pages)
    assert n == 2
    store.execute_query.assert_awaited_once()
    call = store.execute_query.await_args
    assert call is not None
    cypher, params = call.args[0], call.args[1]
    assert "UNWIND" in cypher and "WikiPage" in cypher and "MERGE" in cypher
    assert "batch" in params
    batch = params["batch"]
    assert len(batch) == 2
    assert batch[0]["uid"] == "WikiPage:repo1:README.md"
    assert batch[0]["repository"] == "repo1"
    assert batch[1]["uid"] == "WikiPage:repo1:mod.md"


@pytest.mark.asyncio
async def test_wiki_service_generate_calls_persist_wiki_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(return_value=1)
    graph = AsyncMock()
    svc = WikiService(graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store)

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_page()], False))
    svc._composer_for = MagicMock()

    await svc.generate("r1", "repo", "structure", "json")

    store.persist_wiki_pages.assert_awaited_once()
    assert store.persist_wiki_pages.await_args is not None
    repo_arg, dicts = store.persist_wiki_pages.await_args.args
    assert repo_arg == "r1"
    assert len(dicts) == 1
    assert dicts[0]["path"] == "README.md"
    assert dicts[0]["page_type"] == "repo_overview"
    assert dicts[0]["title"] == "myrepo"
    assert "generated_at" in dicts[0]


@pytest.mark.asyncio
async def test_wiki_service_persist_failure_does_not_fail_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MagicMock()
    store.persist_wiki_pages = AsyncMock(side_effect=RuntimeError("graph down"))
    graph = AsyncMock()
    svc = WikiService(graph=graph, llm=None, repository_exists=AsyncMock(return_value=True), store=store)

    root = WikiStructureNode(
        path="README.md",
        title="r1",
        page_type=PageType.REPO_OVERVIEW,
        children=[],
    )
    structure = WikiStructure(repository="r1", root=root, total_pages=1)
    svc._planner.plan = AsyncMock(return_value=structure)
    svc._compose_all_pages = AsyncMock(return_value=([_page()], False))
    svc._composer_for = MagicMock()

    out = await svc.generate("r1", "repo", "structure", "json")
    assert "pages" in out or "content" in out
