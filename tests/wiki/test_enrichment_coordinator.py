"""Unit tests for wiki.enrichment_coordinator.WikiEnrichmentCoordinator."""

from __future__ import annotations

import asyncio
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
async def test_trigger_enrichment_concurrent_calls_spawn_single_task() -> None:
    repo = f"coord-race-{uuid.uuid4().hex[:8]}"
    coord = _coordinator()
    coord._wiki_cfg.enrichment_enabled = True
    coord._store.execute_query = AsyncMock(return_value=MagicMock(raw=[[3]]))

    create_task_calls: list[str | None] = []

    def _track_create_task(coro, *, name=None):
        create_task_calls.append(name)
        coro.close()
        return MagicMock()

    with patch(
        "wiki.enrichment_coordinator.asyncio.create_task",
        side_effect=_track_create_task,
    ):
        results = await asyncio.gather(
            coord.trigger_enrichment(repo, verify_repository=False),
            coord.trigger_enrichment(repo, verify_repository=False),
        )

    statuses = sorted(r["status"] for r in results)
    assert statuses == ["already_running", "started"]
    assert len(create_task_calls) == 1
    task_ids = {r["task_id"] for r in results}
    assert len(task_ids) == 1


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
async def test_enrich_pages_after_compose_continues_when_one_page_fails() -> None:
    coord = _coordinator()
    coord._wiki_cfg.enrichment_enabled = True
    coord._wiki_cfg.compose_concurrency = 2
    meta = WikiPageMetadata(node_count=0, edge_count=0, generation_mode="full")

    def _page(path: str, title: str) -> WikiPage:
        return WikiPage(
            path=path,
            title=title,
            page_type=PageType.MODULE_OVERVIEW,
            content="",
            diagrams=[],
            source_locations=[],
            metadata=meta,
        )

    pages = [_page("/a", "A"), _page("/b", "B")]
    config = WikiConfig(repository="repo", mode="full")

    mock_pipeline = MagicMock()

    async def _enrich_page(page: WikiPage, **kwargs: object) -> None:
        if page.path == "/a":
            raise RuntimeError("enrich failed for /a")

    mock_pipeline.enrich_page = AsyncMock(side_effect=_enrich_page)

    with patch("wiki.async_enrichment.AsyncEnrichmentPipeline", return_value=mock_pipeline):
        with patch("wiki.enrichment_coordinator.log") as mock_log:
            await coord.enrich_pages_after_compose(
                pages,
                {"/a": ImportanceTier.STANDARD, "/b": ImportanceTier.STANDARD},
                config,
            )

    assert mock_pipeline.enrich_page.await_count == 2
    mock_log.warning.assert_called()
    warning_calls = [
        c for c in mock_log.warning.call_args_list if c.args and c.args[0] == "enrichment_compose_enrich_failed"
    ]
    assert len(warning_calls) == 1
    assert warning_calls[0].kwargs["path"] == "/a"


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
