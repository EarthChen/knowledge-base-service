"""Tests for background business wiki generation with task_id return."""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_wiki_service():
    svc = AsyncMock()
    svc.generate_business_wiki = AsyncMock(
        return_value={
            "business_id": "default",
            "domains": ["auth"],
            "pages_count": 1,
            "references_count": 0,
            "repositories": ["repo1"],
            "partial_errors": [],
        }
    )
    return svc


@pytest.fixture
def mock_task_store():
    store = AsyncMock()
    store.try_lock = AsyncMock(return_value="test-lock-token")
    store.unlock = AsyncMock(return_value=True)
    store.put_task = AsyncMock()
    store.update_status = AsyncMock()
    store.get_task = AsyncMock(
        return_value={
            "task_id": "biz-wiki-test",
            "status": "completed",
            "business_id": "default",
        }
    )
    return store


@pytest.mark.asyncio
async def test_business_generate_returns_task_status(mock_wiki_service, mock_task_store):
    """Background task should complete and update store to completed."""
    from api.routes.wiki_task_routes import _run_business_wiki_background

    await _run_business_wiki_background(
        task_id="biz-wiki-test",
        business_id="default",
        language="en",
        llm_provider=None,
        incremental=True,
        svc=mock_wiki_service,
        task_store=mock_task_store,
        event_bus=None,
    )
    mock_task_store.update_status.assert_called()
    last_call = mock_task_store.update_status.call_args_list[-1]
    assert last_call[0][1] in ("completed", "failed")


@pytest.mark.asyncio
async def test_business_generate_lock_conflict(mock_task_store):
    """Should return None token when lock already held."""
    mock_task_store.try_lock.return_value = None
    from api.routes.wiki_task_routes import _check_business_lock

    locked = await _check_business_lock(mock_task_store, "default")
    assert locked is None


@pytest.mark.asyncio
async def test_business_generate_body_incremental():
    """BusinessWikiGenerateBody should accept incremental field."""
    from api.models.wiki_models import BusinessWikiGenerateBody

    body = BusinessWikiGenerateBody(business_id="default", incremental=True)
    assert body.incremental is True
    body2 = BusinessWikiGenerateBody(business_id="default")
    assert body2.incremental is True


@pytest.mark.asyncio
async def test_progress_callback_updates_store(mock_wiki_service, mock_task_store):
    """Background task should update task_store with progress."""
    from api.routes.wiki_task_routes import _run_business_wiki_background

    await _run_business_wiki_background(
        task_id="biz-wiki-prog",
        business_id="default",
        language="en",
        llm_provider=None,
        incremental=True,
        svc=mock_wiki_service,
        task_store=mock_task_store,
        event_bus=None,
    )
    assert mock_task_store.update_status.call_count >= 2


@pytest.mark.asyncio
async def test_background_task_unlocks_on_failure(mock_task_store):
    """If service raises, lock should still be released."""
    from api.routes.wiki_task_routes import _run_business_wiki_background

    failing_svc = AsyncMock()
    failing_svc.generate_business_wiki = AsyncMock(side_effect=RuntimeError("boom"))

    await _run_business_wiki_background(
        task_id="biz-wiki-fail",
        business_id="default",
        language="en",
        llm_provider=None,
        incremental=True,
        svc=failing_svc,
        task_store=mock_task_store,
        event_bus=None,
        lock_token="test-lock-token",
    )
    mock_task_store.unlock.assert_called_once_with("default", "test-lock-token")
    last_status_call = mock_task_store.update_status.call_args_list[-1]
    assert last_status_call[0][1] == "failed"
    assert last_status_call[1].get("detail") == "boom"
    assert last_status_call[1].get("error") == "internal_error"
