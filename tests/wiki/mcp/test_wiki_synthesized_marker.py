"""Wiki MCP responses mark LLM-oriented payloads with synthesized: true."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.mcp_tools import WikiMCPHandler
from wiki.models import PageType, WikiPage, WikiPageMetadata


@pytest.mark.asyncio
async def test_get_wiki_page_adds_synthesized_true() -> None:
    pipeline = AsyncMock()
    page = WikiPage(
        path="modules/foo",
        title="T",
        page_type=PageType.MODULE_OVERVIEW,
        content="body",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=0, edge_count=0),
    )
    pipeline.get_wiki_page = AsyncMock(return_value=page)

    h = WikiMCPHandler(pipeline=pipeline)
    out = await h.handle_get_wiki_page({"repository": "r", "scope": "module:foo"})

    assert out.get("synthesized") is True
    assert "page" in out


@pytest.mark.asyncio
async def test_search_wiki_adds_synthesized_true() -> None:
    pipeline = AsyncMock()
    pipeline.search_wiki = AsyncMock(return_value={"results": [], "total": 0})

    h = WikiMCPHandler(pipeline=pipeline)
    out = await h.handle_search_wiki({"repository": "r", "query": "hello"})

    assert out.get("synthesized") is True
    assert out["total"] == 0
