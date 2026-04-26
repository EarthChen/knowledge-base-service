from unittest.mock import AsyncMock

import pytest

from wiki.async_enrichment import AsyncEnrichmentPipeline
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    WikiPage,
    WikiPageMetadata,
)


def _make_page(content: str = "# Test\n\n## Overview\nTest entity.") -> WikiPage:
    return WikiPage(
        path="classes/Test.md",
        title="Test",
        page_type=PageType.CLASS_DETAIL,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(
            node_count=1,
            edge_count=0,
            enrichment_level=EnrichmentLevel.BASE,
        ),
    )


@pytest.mark.asyncio
async def test_enrichment_round1_for_core():
    """Core entity should receive Round 1 enrichment."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Business Flow Analysis\nHandles user login.")
    pipeline = AsyncEnrichmentPipeline(llm, round2_enabled=False)
    page = _make_page()
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.CORE,
        language="en",
    )
    assert "Business Flow Analysis" in result.content
    assert result.metadata.enrichment_level == EnrichmentLevel.ENRICHED
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrichment_round1_for_standard():
    """Standard entity should receive Round 1 enrichment."""
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Business Flow Analysis\nProcesses orders.")
    pipeline = AsyncEnrichmentPipeline(llm)
    page = _make_page()
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.STANDARD,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.ENRICHED
    llm.generate.assert_awaited_once()


@pytest.mark.asyncio
async def test_enrichment_round2_only_for_core():
    """Round 2 (encyclopedia) should only run for core entities."""
    llm = AsyncMock()
    llm.generate = AsyncMock(
        side_effect=[
            "## Business Flow Analysis\nRound 1 content.",
            "## Usage Examples\nRound 2 content.",
        ]
    )
    pipeline = AsyncEnrichmentPipeline(llm)
    page = _make_page()
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.CORE,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.ENCYCLOPEDIA
    assert llm.generate.await_count == 2


@pytest.mark.asyncio
async def test_no_enrichment_for_skeleton():
    """Skeleton entities should NOT receive any enrichment."""
    llm = AsyncMock()
    pipeline = AsyncEnrichmentPipeline(llm)
    page = _make_page()
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.SKELETON,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.BASE
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrichment_appends_content():
    """Enrichment should append to existing content, not replace."""
    original = "# Test\n\n## Overview\nOriginal content."
    llm = AsyncMock()
    llm.generate = AsyncMock(return_value="## Business Flow Analysis\nNew enrichment.")
    pipeline = AsyncEnrichmentPipeline(llm)
    page = _make_page(content=original)
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.STANDARD,
        language="en",
    )
    assert result.content.startswith(original.rstrip())
    assert "New enrichment" in result.content


@pytest.mark.asyncio
async def test_enrichment_disabled_round1():
    """When round1 disabled, no enrichment happens for standard."""
    llm = AsyncMock()
    pipeline = AsyncEnrichmentPipeline(llm, round1_enabled=False)
    page = _make_page()
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.STANDARD,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.BASE
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrichment_llm_failure_graceful():
    """LLM failure during enrichment should not crash; page stays at current level."""
    llm = AsyncMock()
    llm.generate = AsyncMock(side_effect=Exception("LLM timeout"))
    pipeline = AsyncEnrichmentPipeline(llm)
    page = _make_page()
    original_content = page.content
    result = await pipeline.enrich_page(
        page,
        entity_name="Test",
        entity_label="Class",
        tier=ImportanceTier.CORE,
        language="en",
    )
    assert result.metadata.enrichment_level == EnrichmentLevel.BASE
    assert result.content == original_content
