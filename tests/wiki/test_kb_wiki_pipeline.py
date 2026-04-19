"""Tests for MCP ``WikiPipeline`` wiring via :class:`WikiPipelineAdapter`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.falkordb_store import QueryResultWrapper
from wiki.kb_wiki_pipeline import WikiPipelineAdapter
from wiki.mcp_tools import WikiPipeline
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.search import SearchResponse
from wiki.service import WikiService


def _minimal_page(path: str = "README.md") -> WikiPage:
    return WikiPage(
        path=path,
        title="T",
        page_type=PageType.REPO_OVERVIEW,
        content="# T",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )


@pytest.mark.asyncio
async def test_wiki_pipeline_adapter_isinstance_wiki_pipeline() -> None:
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock(
        return_value={
            "pages": [_minimal_page().to_dict()],
            "structure": {
                "repository": "r1",
                "root": {
                    "path": "README.md",
                    "title": "r1",
                    "page_type": PageType.REPO_OVERVIEW.value,
                    "children": [],
                },
                "total_pages": 1,
            },
        },
    )
    search = MagicMock()
    search.search = AsyncMock(
        return_value=SearchResponse(
            results=[],
            query_expansion={"original": "q", "expanded_queries": [], "terms": []},
            total=0,
        ),
    )
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=None)
    assert isinstance(adapter, WikiPipeline)


@pytest.mark.asyncio
async def test_wiki_pipeline_adapter_generate_delegates() -> None:
    page = _minimal_page()
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock(
        return_value={
            "pages": [page.to_dict()],
            "structure": {},
        },
    )
    search = MagicMock()
    search.search = AsyncMock()
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=None)
    out = await adapter.generate_wiki("r1", "repo", "structure")
    assert len(out) == 1
    assert out[0].path == "README.md"
    wiki.generate.assert_awaited_once_with("r1", "repo", "structure", "json")


@pytest.mark.asyncio
async def test_wiki_pipeline_adapter_ask_without_llm_returns_message() -> None:
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock(return_value={"pages": [], "structure": {}})
    search = MagicMock()
    search.search = AsyncMock()
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=None)
    body = await adapter.ask_about_code("r1", "why?", None, None)
    assert "LLM" in body["content"] or "language model" in body["content"].lower()
    assert body["sources"] == []


def _graph_node_props(**kwargs: object) -> MagicMock:
    n = MagicMock()
    n.properties = dict(kwargs)
    return n


@pytest.mark.asyncio
async def test_get_wiki_page_reads_from_graph_repo_scope() -> None:
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock()
    search = MagicMock()
    search.search = AsyncMock()
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=QueryResultWrapper(
            data=[
                {
                    "wp": _graph_node_props(
                        uid="WikiPage:r1:README.md",
                        repository="r1",
                        path="README.md",
                        title="r1",
                        content="# r1\n",
                        page_type="repo_overview",
                        generated_at="t0",
                    ),
                },
            ],
            raw=[],
        ),
    )
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=store)
    page = await adapter.get_wiki_page("r1", "repo")
    assert page is not None
    assert page.path == "README.md"
    assert page.page_type == PageType.REPO_OVERVIEW
    assert page.content == "# r1\n"
    wiki.generate.assert_not_called()
    store.execute_query.assert_awaited()


@pytest.mark.asyncio
async def test_get_wiki_page_returns_none_when_missing() -> None:
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock()
    search = MagicMock()
    search.search = AsyncMock()
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=QueryResultWrapper(data=[], raw=[]))
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=store)
    assert await adapter.get_wiki_page("r1", "repo") is None
    wiki.generate.assert_not_called()


@pytest.mark.asyncio
async def test_list_wiki_pages_reads_from_graph() -> None:
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock()
    search = MagicMock()
    search.search = AsyncMock()
    store = MagicMock()
    store.execute_query = AsyncMock(
        return_value=QueryResultWrapper(
            data=[
                {"path": "README.md", "title": "r1", "page_type": "repo_overview"},
                {"path": "a.md", "title": "A", "page_type": "module_overview"},
            ],
            raw=[],
        ),
    )
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=store)
    out = await adapter.list_wiki_pages("r1", None)
    assert out["repository"] == "r1"
    assert out["total_pages"] == 2
    assert out["tree"]["path"] == "README.md"
    assert len(out["tree"]["children"]) == 1
    assert out["tree"]["children"][0]["path"] == "a.md"
    wiki.generate.assert_not_called()


@pytest.mark.asyncio
async def test_generate_wiki_still_calls_wiki_service_generate() -> None:
    page = _minimal_page()
    wiki = MagicMock(spec=WikiService)
    wiki.generate = AsyncMock(
        return_value={
            "pages": [page.to_dict()],
            "structure": {},
        },
    )
    search = MagicMock()
    search.search = AsyncMock()
    store = MagicMock()
    store.execute_query = AsyncMock()
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None, store=store)
    out = await adapter.generate_wiki("r1", "repo", "structure")
    assert len(out) == 1
    wiki.generate.assert_awaited_once_with("r1", "repo", "structure", "json")
