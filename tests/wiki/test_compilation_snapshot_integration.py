"""Integration-style tests for compilation snapshot wiring in WikiService."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import Settings
from tests.wiki_config_inject import wiki_service_injection
from wiki.compilation_snapshot import WikiCompilationSnapshot
from wiki.service import WikiService


@pytest.mark.asyncio
async def test_run_compilation_snapshot_uses_wiki_compilation_and_logs() -> None:
    """_run_compilation_snapshot delegates to WikiCompilationSnapshot and logs success."""
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))
    store.persist_wiki_pages = AsyncMock(return_value=1)

    graph = AsyncMock()
    svc = WikiService(
        graph=graph,
        llm=None,
        repository_exists=AsyncMock(return_value=True),
        store=store,
        **wiki_service_injection(),
    )

    with patch("wiki.service.log") as mock_log:
        await svc._run_compilation_snapshot("b1", "test-repo")

    mock_log.info.assert_called()
    assert any(
        c.args[0] == "compilation_snapshot_built"
        for c in mock_log.info.call_args_list
    )
    store.execute_query.assert_awaited()
    store.persist_wiki_pages.assert_awaited()
    _repo, page_dicts = store.persist_wiki_pages.await_args.args
    assert _repo == "test-repo"
    assert any(p.get("path") == "wiki_snapshot.md" for p in page_dicts)
    assert all(p.get("page_type") == "index" for p in page_dicts)


@pytest.mark.asyncio
async def test_wiki_compilation_snapshot_generate_calls_execute_query() -> None:
    """WikiCompilationSnapshot.generate runs the graph page query."""
    store = MagicMock()
    store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    cfg = Settings().wiki
    snap = WikiCompilationSnapshot(graph=store, wiki_config=cfg)
    result = await snap.generate("b1", "test-repo")
    assert "test-repo" in result
    store.execute_query.assert_awaited_once()
