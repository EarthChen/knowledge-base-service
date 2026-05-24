"""Tests that enrichment uses PipelineConcurrency for compose-stage limits."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.enrichment_coordinator import WikiEnrichmentCoordinator
from wiki.models import ImportanceTier, PageType, WikiConfig, WikiPage, WikiPageMetadata


def _coordinator(**overrides):
    kwargs = {
        "store": MagicMock(),
        "graph": MagicMock(),
        "wiki_cfg": MagicMock(),
        "persistence": MagicMock(),
        "llm_resolver": MagicMock(return_value=MagicMock()),
        "repository_exists": AsyncMock(return_value=True),
        "deferred_enrichment": None,
    }
    kwargs.update(overrides)
    return WikiEnrichmentCoordinator(**kwargs)


@pytest.mark.asyncio
async def test_enrich_pages_after_compose_uses_pipeline_concurrency_compose_stage() -> None:
    coord = _coordinator()
    coord._wiki_cfg.enrichment_enabled = True
    meta = WikiPageMetadata(node_count=0, edge_count=0, generation_mode="full")
    page = WikiPage(
        path="/p",
        title="t",
        page_type=PageType.MODULE_OVERVIEW,
        content="",
        diagrams=[],
        source_locations=[],
        metadata=meta,
    )
    config = WikiConfig(repository="repo", mode="full")
    mock_pipeline = MagicMock()
    mock_pipeline.enrich_page = AsyncMock()
    mock_sem = asyncio.Semaphore(1)

    with patch("wiki.enrichment_coordinator.PipelineConcurrency.semaphore", return_value=mock_sem) as mock_semaphore:
        with patch("wiki.async_enrichment.AsyncEnrichmentPipeline", return_value=mock_pipeline):
            await coord.enrich_pages_after_compose(
                [page],
                {"/p": ImportanceTier.STANDARD},
                config,
            )

    mock_semaphore.assert_called_once_with("compose")
