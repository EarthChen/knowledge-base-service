"""Tests for WikiService background task lifecycle tracking."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_bare_create_task_tracked():
    """When no task_supervisor, bare asyncio.create_task must be tracked in _background_tasks."""
    from wiki.service import WikiService
    from core.config import AppWikiFlags, EmbeddingConfig

    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[{
        "domain": "test", "repository": "repo", "title": "TestPage", "uid": "uid-1",
    }]))

    wiki_cfg = AppWikiFlags()
    emb_cfg = EmbeddingConfig()

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=mock_graph,
            llm=None,
            repository_exists=AsyncMock(return_value=True),
            wiki_config=wiki_cfg,
            embedding_config=emb_cfg,
            task_supervisor=None,
        )

    result = await svc.trigger_page_regeneration("uid-1")
    assert result["status"] == "accepted"

    # The task should be tracked
    assert hasattr(svc, "_background_tasks")
    assert len(svc._background_tasks) >= 1

    # Cancel tracked tasks (simulates shutdown)
    for t in list(svc._background_tasks):
        t.cancel()
    await asyncio.gather(*svc._background_tasks, return_exceptions=True)
    # After cancellation and cleanup callback, set should be empty or have cancelled tasks
    await asyncio.sleep(0.01)  # Let callbacks fire


@pytest.mark.asyncio
async def test_background_tasks_set_initialized():
    """WikiService must have _background_tasks attribute."""
    from wiki.service import WikiService
    from core.config import AppWikiFlags, EmbeddingConfig

    wiki_cfg = AppWikiFlags()
    emb_cfg = EmbeddingConfig()

    with patch("wiki.service.get_settings") as mock_settings:
        mock_settings.return_value.llm = MagicMock(max_context_tokens=128_000)
        svc = WikiService(
            graph=MagicMock(),
            llm=None,
            repository_exists=AsyncMock(return_value=True),
            wiki_config=wiki_cfg,
            embedding_config=emb_cfg,
        )

    assert hasattr(svc, "_background_tasks")
    assert isinstance(svc._background_tasks, set)
    assert len(svc._background_tasks) == 0
