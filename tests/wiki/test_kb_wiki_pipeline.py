"""Tests for MCP ``WikiPipeline`` wiring via :class:`WikiPipelineAdapter`."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

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
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None)
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
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None)
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
    adapter = WikiPipelineAdapter(wiki_service=wiki, search=search, ask=None)
    body = await adapter.ask_about_code("r1", "why?", None, None)
    assert "LLM" in body["content"] or "language model" in body["content"].lower()
    assert body["sources"] == []
