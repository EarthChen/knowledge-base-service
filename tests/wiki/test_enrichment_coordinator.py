"""Unit tests for wiki.enrichment_coordinator.WikiEnrichmentCoordinator."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.enrichment_coordinator import WikiEnrichmentCoordinator
from wiki.errors import WikiRepoNotFoundError
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


@pytest.fixture(autouse=True)
def cleanup_enrichment_running():
    WikiEnrichmentCoordinator._enrichment_running.clear()
    yield
    WikiEnrichmentCoordinator._enrichment_running.clear()


@pytest.mark.asyncio
async def test_get_enrichment_status_without_execute_query_returns_zeros() -> None:
    coord = _coordinator(store=object())
    out = await coord.get_enrichment_status("r", verify_repository=False)
    assert out["total_pages"] == 0
    assert out["repository"] == "r"


@pytest.mark.asyncio
async def test_get_enrichment_status_aggregates_levels() -> None:
    coord = _coordinator()
    coord._store.execute_query = AsyncMock(
        return_value=MagicMock(
            raw=[
                ["base", 2],
                ["enriched", 1],
                [None, 1],
            ]
        )
    )
    out = await coord.get_enrichment_status("r", verify_repository=False)
    assert out["total_pages"] == 4
    assert out["base"] == 3
    assert out["enriched"] == 1


@pytest.mark.asyncio
async def test_trigger_enrichment_raises_when_repository_missing() -> None:
    coord = _coordinator(repository_exists=AsyncMock(return_value=False))
    with pytest.raises(WikiRepoNotFoundError) as exc:
        await coord.trigger_enrichment("gone")
    assert exc.value.repository == "gone"


@pytest.mark.asyncio
async def test_trigger_enrichment_verify_repository_disabled_skips_check() -> None:
    coord = _coordinator(repository_exists=AsyncMock(return_value=False))
    coord._wiki_cfg.enrichment_enabled = False
    out = await coord.trigger_enrichment("any", verify_repository=False)
    assert out["status"] == "skipped"
    coord._repository_exists.assert_not_called()


@pytest.mark.asyncio
async def test_trigger_enrichment_already_running_returns_same_task() -> None:
    repo = f"coord-test-{uuid.uuid4().hex[:8]}"
    existing_id = "enrich-existingid"
    WikiEnrichmentCoordinator._enrichment_running[repo] = existing_id

    coord = _coordinator()
    coord._wiki_cfg.enrichment_enabled = True
    coord._store.execute_query = AsyncMock(return_value=MagicMock(raw=[[4]]))

    result = await coord.trigger_enrichment(repo, verify_repository=False)

    assert result["status"] == "already_running"
    assert result["task_id"] == existing_id
    assert result["eligible_pages"] == 4


@pytest.mark.asyncio
async def test_enrich_pages_after_compose_skips_structure_mode() -> None:
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
    config = WikiConfig(repository="repo", mode="structure")

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline") as Pipe:
        await coord.enrich_pages_after_compose(
            [page],
            {"/p": ImportanceTier.STANDARD},
            config,
        )
    Pipe.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_pages_after_compose_skips_without_tiers() -> None:
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

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline") as Pipe:
        await coord.enrich_pages_after_compose([page], {}, config)
    Pipe.return_value.enrich_page.assert_not_called()


@pytest.mark.asyncio
async def test_enrich_pages_after_compose_no_llm_returns_quietly() -> None:
    coord = _coordinator(llm_resolver=MagicMock(return_value=None))
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

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline") as Pipe:
        await coord.enrich_pages_after_compose(
            [page],
            {"/p": ImportanceTier.STANDARD},
            config,
        )
    Pipe.assert_not_called()


@pytest.mark.asyncio
async def test_run_enrichment_background_clears_running_registry() -> None:
    coord = _coordinator()
    repo = f"bg-{uuid.uuid4().hex[:8]}"
    WikiEnrichmentCoordinator._enrichment_running[repo] = "task-holder"

    coord._store.execute_query = AsyncMock(
        return_value=MagicMock(
            raw=[
                ["/mod", "body", "Title", "module_overview", "standard", "en"],
            ]
        )
    )
    coord._persistence.persist_pages_to_graph = AsyncMock()

    mock_pipeline = MagicMock()
    mock_pipeline.enrich_page = AsyncMock()

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline", return_value=mock_pipeline):
        await coord.run_enrichment_background(repo, MagicMock(), "tid")

    assert repo not in WikiEnrichmentCoordinator._enrichment_running
    mock_pipeline.enrich_page.assert_awaited()
    coord._persistence.persist_pages_to_graph.assert_awaited()


@pytest.mark.asyncio
async def test_run_enrichment_background_no_pages_exits_early() -> None:
    coord = _coordinator()
    repo = f"empty-{uuid.uuid4().hex[:8]}"
    WikiEnrichmentCoordinator._enrichment_running[repo] = "t"

    coord._store.execute_query = AsyncMock(return_value=MagicMock(raw=[]))

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline") as Pipe:
        await coord.run_enrichment_background(repo, MagicMock(), "tid")

    Pipe.assert_not_called()
    assert repo not in WikiEnrichmentCoordinator._enrichment_running
