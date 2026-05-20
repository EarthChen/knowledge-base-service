"""Test that generate_stream_events is resilient to individual page failures."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from store.schema import NodeLabel
from tests.wiki_config_inject import wiki_service_injection
from wiki.data_collector import PageData
from wiki.models import (
    PageType,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
)
from wiki.service import WikiService


def _wiki_page(path: str) -> WikiPage:
    return WikiPage(
        path=path,
        title=path,
        page_type=PageType.MODULE_OVERVIEW,
        content="content",
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )


def _structure() -> WikiStructure:
    return WikiStructure(
        repository="test-repo",
        root=WikiStructureNode(
            path=".",
            title="test-repo",
            page_type=PageType.REPO_OVERVIEW,
            children=[
                WikiStructureNode(
                    path="mod_a",
                    title="ModA",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
                WikiStructureNode(
                    path="mod_b",
                    title="ModB",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
                WikiStructureNode(
                    path="mod_c",
                    title="ModC",
                    page_type=PageType.MODULE_OVERVIEW,
                    children=[],
                ),
            ],
        ),
        total_pages=4,
    )


@pytest.mark.asyncio
async def test_stream_continues_after_single_page_compose_failure() -> None:
    """If compose_page raises for one node, the stream yields page_error and continues."""
    structure = _structure()
    graph_node = MagicMock(
        uid="Module:test-repo:mod",
        label=NodeLabel.MODULE,
        properties={"name": "mod", "path": "mod"},
    )
    page_data = PageData(
        node=graph_node,
        edges=[],
        children=[],
        source_location=MagicMock(),
        method_locations=[],
        business_summary=None,
        methods=[],
    )

    compose_calls = {"count": 0}

    async def compose_side_effect(*_args, **_kwargs):
        compose_calls["count"] += 1
        if compose_calls["count"] == 2:
            raise RuntimeError("compose failed for mod_b")
        path = f"mod_{'a' if compose_calls['count'] == 1 else 'c'}"
        return _wiki_page(path)

    mock_composer = MagicMock()
    mock_composer._wiki_store = None
    mock_composer.compose_page = AsyncMock(side_effect=compose_side_effect)

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=MagicMock(),
            llm=MagicMock(),
            repository_exists=AsyncMock(return_value=True),
            **wiki_service_injection(),
        )

    svc._planner.plan = AsyncMock(return_value=structure)
    svc._ensure_repo = AsyncMock()
    svc._composer_for = MagicMock(return_value=mock_composer)
    svc._resolve_structure_node = AsyncMock(return_value=graph_node)
    svc._collector.collect = AsyncMock(return_value=page_data)
    svc._enrich_pages_after_compose = AsyncMock()
    svc._persist_pages_to_graph = AsyncMock()
    svc._sync_graph_references_into_page_content = AsyncMock()
    svc._run_compilation_snapshot = AsyncMock()

    events: list[dict] = []
    async for event in svc.generate_stream_events(
        "test-repo",
        scope_raw="repo",
        mode="structure",
        format="json",
        language="en",
    ):
        events.append(event)

    page_events = [e for e in events if "page" in e]
    error_events = [e for e in events if e.get("type") == "page_error"]
    complete_events = [e for e in events if "complete" in e]

    assert len(page_events) == 3  # overview + mod_a + mod_c
    assert len(error_events) == 1
    assert error_events[0]["path"] == "mod_b"
    assert "compose failed" in error_events[0]["error"]
    assert len(complete_events) == 1
    assert complete_events[0]["complete"]["error_count"] == 1


@pytest.mark.asyncio
async def test_walk_stream_service_has_background_tasks() -> None:
    """WikiService initializes background task tracking used by streaming paths."""
    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=MagicMock(),
            llm=MagicMock(),
            repository_exists=AsyncMock(return_value=True),
            **wiki_service_injection(),
        )

    assert hasattr(svc, "_background_tasks")
