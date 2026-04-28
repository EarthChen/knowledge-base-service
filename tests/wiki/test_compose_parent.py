import pytest
from unittest.mock import AsyncMock, MagicMock

from store.schema import GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import ImportanceTier, PageType, WikiConfig, WikiPageSummary

pytestmark = pytest.mark.asyncio


async def test_compose_parent_uses_child_summaries():
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="Module overview based on children.")
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(llm, ctx)
    node = GraphNode(uid="test:Module:api", label=NodeLabel.MODULE, properties={"name": "api", "path": "src/api"})
    page_data = PageData(
        node=node,
        edges=[],
        children=[],
        source_location=MagicMock(),
        method_locations=[],
        business_summary=None,
        methods=[],
        code_snippets=[],
        related_chunks=[],
    )
    config = WikiConfig(repository="test", mode="full")
    child_summaries = [
        WikiPageSummary("uid:Class:A", "ClassA", "classes/A.md", "Handles authentication", ImportanceTier.CORE, PageType.CLASS_DETAIL),
        WikiPageSummary("uid:Class:B", "ClassB", "classes/B.md", "Manages sessions", ImportanceTier.STANDARD, PageType.CLASS_DETAIL),
    ]

    page = await composer.compose_parent_page(page_data, PageType.MODULE_OVERVIEW, config, child_summaries)
    assert page is not None
    assert page.page_type == PageType.MODULE_OVERVIEW
    llm.generate.assert_called_once()
    prompt_arg = llm.generate.call_args[0][0]
    assert "ClassA" in prompt_arg
    assert "ClassB" in prompt_arg


async def test_compose_parent_no_llm_uses_structural_fallback():
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(None, ctx)
    node = GraphNode(uid="test:Module:api", label=NodeLabel.MODULE, properties={"name": "api", "path": "src/api"})
    page_data = PageData(
        node=node,
        edges=[],
        children=[],
        source_location=MagicMock(),
        method_locations=[],
        business_summary=None,
        methods=[],
        code_snippets=[],
        related_chunks=[],
    )
    config = WikiConfig(repository="test", mode="full")
    child_summaries = [
        WikiPageSummary("uid:Class:A", "ClassA", "classes/A.md", "Handles auth", ImportanceTier.CORE, PageType.CLASS_DETAIL),
    ]
    page = await composer.compose_parent_page(page_data, PageType.MODULE_OVERVIEW, config, child_summaries)
    assert page is not None
    assert page.metadata.fallback_tier == 3


async def test_compose_parent_empty_summaries_uses_fallback():
    llm = AsyncMock()
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""

    composer = WikiComposer(llm, ctx)
    node = GraphNode(uid="test:Module:api", label=NodeLabel.MODULE, properties={"name": "api", "path": "src/api"})
    page_data = PageData(
        node=node,
        edges=[],
        children=[],
        source_location=MagicMock(),
        method_locations=[],
        business_summary=None,
        methods=[],
        code_snippets=[],
        related_chunks=[],
    )
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_parent_page(page_data, PageType.MODULE_OVERVIEW, config, [])
    assert page.metadata.fallback_tier == 3
    llm.generate.assert_not_called()
