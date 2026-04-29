"""Tests for trigger_enrichment actual implementation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_trigger_enrichment_returns_task_id() -> None:
    """trigger_enrichment should return a task_id when eligible pages exist."""
    from wiki.service import WikiService

    svc = WikiService.__new__(WikiService)
    svc._wiki_cfg = MagicMock()
    svc._wiki_cfg.enrichment_enabled = True
    svc._wiki_cfg.enrichment_round1_enabled = True
    svc._wiki_cfg.enrichment_round2_enabled = False
    svc._store = MagicMock()
    svc._store.execute_query = AsyncMock(
        return_value=MagicMock(raw=[[5]])
    )
    svc._ensure_repo = AsyncMock()
    svc._resolve_llm_port = MagicMock(return_value=MagicMock())

    def _stub_create_task(coro, *, name=None):
        coro.close()
        return MagicMock()

    with patch("wiki.service.asyncio.create_task", side_effect=_stub_create_task) as mock_ct:
        result = await svc.trigger_enrichment("test-repo")

    assert "task_id" in result
    assert result["eligible_pages"] == 5
    assert result["status"] == "started"
    assert result["repository"] == "test-repo"
    mock_ct.assert_called_once()


@pytest.mark.asyncio
async def test_trigger_enrichment_no_eligible_pages() -> None:
    """trigger_enrichment should skip when no eligible pages."""
    from wiki.service import WikiService

    svc = WikiService.__new__(WikiService)
    svc._wiki_cfg = MagicMock()
    svc._wiki_cfg.enrichment_enabled = True
    svc._store = MagicMock()
    svc._store.execute_query = AsyncMock(
        return_value=MagicMock(raw=[[0]])
    )
    svc._ensure_repo = AsyncMock()
    svc._resolve_llm_port = MagicMock(return_value=MagicMock())

    result = await svc.trigger_enrichment("test-repo")

    assert result["eligible_pages"] == 0
    assert result["status"] == "skipped"


@pytest.mark.asyncio
async def test_trigger_enrichment_no_llm() -> None:
    """trigger_enrichment should report unavailable when LLM is missing."""
    from wiki.service import WikiService

    svc = WikiService.__new__(WikiService)
    svc._wiki_cfg = MagicMock()
    svc._wiki_cfg.enrichment_enabled = True
    svc._store = MagicMock()
    svc._ensure_repo = AsyncMock()
    svc._resolve_llm_port = MagicMock(return_value=None)

    result = await svc.trigger_enrichment("test-repo")

    assert result["eligible_pages"] == 0
    assert result["status"] == "skipped"
    assert "LLM" in result.get("reason", "")
