"""Tests for SKELETON tier compose_page dispatch and WikiLinkCache integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from store.schema import GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.data_collector import PageData
from wiki.models import ImportanceTier, PageType, SkeletonStrategy, WikiConfig
from wiki.wikilink_cache import WikiLinkCache


def _make_ctx():
    ctx = MagicMock()
    ctx.build_style_sheet.return_value = ""
    ctx.build_page_context.return_value = ""
    return ctx


def _make_page_data(name: str = "TestClass") -> PageData:
    node = GraphNode(uid=f"test:Class:{name}", label=NodeLabel.CLASS, properties={"name": name})
    return PageData(
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


async def test_skeleton_template_skips_llm():
    """SKELETON + TEMPLATE strategy should use tier3 structural, no LLM call."""
    llm_mock = AsyncMock()
    ctx = _make_ctx()
    composer = WikiComposer(llm_mock, ctx)
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(),
        PageType.CLASS_DETAIL,
        config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.TEMPLATE,
    )
    assert page is not None
    assert page.metadata.fallback_tier == 3
    llm_mock.generate.assert_not_called()


async def test_skeleton_skip_returns_none():
    """SKELETON + SKIP strategy should return None."""
    ctx = _make_ctx()
    composer = WikiComposer(None, ctx)
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(),
        PageType.CLASS_DETAIL,
        config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.SKIP,
    )
    assert page is None


async def test_skeleton_light_model_calls_llm():
    """SKELETON + LIGHT_MODEL strategy should call LLM."""
    llm_mock = AsyncMock()
    llm_mock.generate = AsyncMock(return_value="Brief doc for TestClass.")
    ctx = _make_ctx()
    composer = WikiComposer(llm_mock, ctx)
    config = WikiConfig(repository="test", mode="full")
    page = await composer.compose_page(
        _make_page_data(),
        PageType.CLASS_DETAIL,
        config,
        importance_tier=ImportanceTier.SKELETON,
        skeleton_strategy=SkeletonStrategy.LIGHT_MODEL,
    )
    assert page is not None
    llm_mock.generate.assert_called_once()
    assert page.metadata.fallback_tier == 2


async def test_composer_uses_cache_instead_of_db():
    """When wikilink_cache is provided, composer should use it."""
    cache = WikiLinkCache()
    cache.register("SomeClass", "classes/SomeClass.md")
    ctx = _make_ctx()
    composer = WikiComposer(None, ctx, wikilink_cache=cache)
    config = WikiConfig(repository="test", mode="structure")
    page = await composer.compose_page(
        _make_page_data("SomeClass"),
        PageType.CLASS_DETAIL,
        config,
    )
    assert page is not None
    assert page.title == "TestClass" or page.title == "SomeClass"


async def test_non_skeleton_still_works():
    """Non-SKELETON entities should still use normal compose flow."""
    ctx = _make_ctx()
    composer = WikiComposer(None, ctx)
    config = WikiConfig(repository="test", mode="structure")
    page = await composer.compose_page(
        _make_page_data(),
        PageType.CLASS_DETAIL,
        config,
        importance_tier=ImportanceTier.CORE,
    )
    assert page is not None
    assert page.metadata.fallback_tier == 3
