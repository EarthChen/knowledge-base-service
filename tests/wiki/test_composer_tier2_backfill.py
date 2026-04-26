"""Tier 2 wiki composer backfill of business_summary on the graph."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.models import PageType, SourceLocation, WikiConfig


def _page_data(*, summary: str | None, uid: str) -> PageData:
    node = GraphNode(
        label=NodeLabel.CLASS,
        properties={"name": "Svc", "fqn": "x.Svc", "file": "svc.py"},
        uid=uid,
    )
    loc = SourceLocation("svc.py", 1, 10, "x.Svc", "repo1")
    return PageData(
        node=node,
        edges=[],
        children=[],
        source_location=loc,
        method_locations=[],
        business_summary=summary,
        methods=[],
    )


@pytest.mark.asyncio
async def test_tier2_backfills_summary() -> None:
    llm = MagicMock()
    llm.generate = AsyncMock(
        return_value="First line of LLM overview.\nMore detail here.",
    )
    wiki_store = MagicMock()
    wiki_store.find_related_docs_entities = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.list_wiki_pages_all = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.update_node_property = AsyncMock()

    composer = WikiComposer(
        llm,
        WikiContextBuilder(llm),
        store=None,
        wiki_store=wiki_store,
    )
    cfg = WikiConfig(repository="repo1", mode="full", format="json", language="en")
    page = await composer.compose_page(
        _page_data(summary=None, uid="class:1"),
        PageType.CLASS_DETAIL,
        cfg,
    )

    assert "First line" in page.content
    wiki_store.update_node_property.assert_awaited_once()
    call = wiki_store.update_node_property.await_args
    assert call.args[0] == NodeLabel.CLASS
    assert call.args[1] == "class:1"
    assert call.args[2] == "business_summary"
    assert call.args[3] == "First line of LLM overview."


@pytest.mark.asyncio
async def test_tier1_no_backfill() -> None:
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="should not run")
    wiki_store = MagicMock()
    wiki_store.find_related_docs_entities = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.list_wiki_pages_all = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.update_node_property = AsyncMock()

    composer = WikiComposer(
        llm,
        WikiContextBuilder(llm),
        store=None,
        wiki_store=wiki_store,
    )
    cfg = WikiConfig(repository="repo1", mode="structure", format="json", language="en")
    page = await composer.compose_page(
        _page_data(summary="Already have summary", uid="class:2"),
        PageType.CLASS_DETAIL,
        cfg,
    )

    assert "Already have summary" in page.content
    llm.generate.assert_not_awaited()
    wiki_store.update_node_property.assert_not_awaited()
