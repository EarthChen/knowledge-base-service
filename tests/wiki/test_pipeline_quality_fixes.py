"""Tests for wiki content quality pipeline fixes."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import PageData
from wiki.models import PageType, SourceLocation, WikiConfig
from wiki.service import WikiService


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


def test_generate_business_wiki_default_mode_is_full() -> None:
    sig = inspect.signature(WikiService.generate_business_wiki)
    mode_param = sig.parameters["mode"]
    assert mode_param.default == "full", (
        f"generate_business_wiki mode default should be 'full', got '{mode_param.default}'"
    )


@pytest.mark.asyncio
async def test_full_mode_calls_llm_even_with_business_summary() -> None:
    """When mode='full' and LLM is available, tier-2 should be used
    even if business_summary already exists (the backfill trap fix)."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="Rich LLM-generated content about Svc.")
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
        _page_data(summary="Short cached summary", uid="class:trap"),
        PageType.CLASS_DETAIL,
        cfg,
    )

    llm.generate.assert_awaited_once()
    assert "Rich LLM-generated content" in page.content
    assert page.metadata.fallback_tier == 2
    wiki_store.update_node_property.assert_not_awaited()


@pytest.mark.asyncio
async def test_structure_mode_prefers_business_summary_over_template() -> None:
    """In structure mode, business_summary should be used as description
    (better than template), without calling LLM."""
    llm = MagicMock()
    llm.generate = AsyncMock(return_value="Should not run")
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
        _page_data(summary="Business summary for structure mode", uid="class:struct"),
        PageType.CLASS_DETAIL,
        cfg,
    )

    llm.generate.assert_not_awaited()
    assert "Business summary for structure mode" in page.content
    assert page.metadata.fallback_tier == 1


@pytest.mark.asyncio
async def test_no_llm_falls_back_to_business_summary() -> None:
    """When LLM is None but business_summary exists, tier-1 should be used."""
    wiki_store = MagicMock()
    wiki_store.find_related_docs_entities = AsyncMock(return_value=MagicMock(data=[]))
    wiki_store.list_wiki_pages_all = AsyncMock(return_value=MagicMock(data=[]))

    composer = WikiComposer(
        None,  # no LLM
        WikiContextBuilder(None),
        store=None,
        wiki_store=wiki_store,
    )
    cfg = WikiConfig(repository="repo1", mode="full", format="json", language="en")
    page = await composer.compose_page(
        _page_data(summary="Fallback summary", uid="class:nollm"),
        PageType.CLASS_DETAIL,
        cfg,
    )

    assert "Fallback summary" in page.content
    assert page.metadata.fallback_tier == 1
