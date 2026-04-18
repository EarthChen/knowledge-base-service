"""Tests for wiki.webhook.dispatcher — EventDispatcher routing and branch rules."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.webhook.debounce import PushDebouncer
from wiki.webhook.dispatcher import EventDispatcher
from wiki.webhook.event_model import ChangedFile, WebhookEvent


def _event(
    *,
    event_type: str = "push",
    ref: str = "refs/heads/main",
    repo: str = "org/repo",
    delivery_id: str = "dlv-1",
) -> WebhookEvent:
    return WebhookEvent(
        provider="github",
        event_type=event_type,
        delivery_id=delivery_id,
        repository=repo,
        ref=ref,
        before="a" * 40,
        after="b" * 40,
        changed_files=[ChangedFile(path="x.py", status="modified")],
        sender="bob",
        timestamp=datetime(2026, 4, 18, tzinfo=UTC),
    )


@pytest.mark.asyncio
class TestDispatcherPushRouting:
    async def test_push_event_dispatched_to_debouncer_add(self) -> None:
        debouncer = MagicMock(spec=PushDebouncer)
        debouncer._on_flush = None
        debouncer.add = AsyncMock()
        updater = AsyncMock()
        d = EventDispatcher(debouncer, updater=updater)
        ev = _event()
        result = await d.dispatch(ev)
        assert result == {"status": "queued"}
        debouncer.add.assert_awaited_once_with(ev)


@pytest.mark.asyncio
class TestDispatcherIgnoreNonPush:
    async def test_non_push_ignored(self) -> None:
        debouncer = MagicMock(spec=PushDebouncer)
        debouncer._on_flush = None
        debouncer.add = AsyncMock()
        d = EventDispatcher(debouncer, updater=AsyncMock())
        ev = _event(event_type="pull_request")
        assert await d.dispatch(ev) == {"status": "ignored"}
        debouncer.add.assert_not_called()


@pytest.mark.asyncio
class TestDispatcherBranches:
    async def test_push_non_configured_branch_ignored(self) -> None:
        debouncer = MagicMock(spec=PushDebouncer)
        debouncer._on_flush = None
        debouncer.add = AsyncMock()
        d = EventDispatcher(debouncer, updater=AsyncMock(), branches=["main", "master"])
        ev = _event(ref="refs/heads/feature-xyz")
        assert await d.dispatch(ev) == {"status": "ignored"}
        debouncer.add.assert_not_called()

    async def test_main_and_master_allowed(self) -> None:
        debouncer = MagicMock(spec=PushDebouncer)
        debouncer._on_flush = None
        debouncer.add = AsyncMock()
        up = AsyncMock()
        d = EventDispatcher(debouncer, updater=up, branches=["main", "master"])
        main_ev = _event(ref="refs/heads/main")
        master_ev = _event(ref="refs/heads/master", delivery_id="m2")
        assert await d.dispatch(main_ev) == {"status": "queued"}
        assert await d.dispatch(master_ev) == {"status": "queued"}
        assert debouncer.add.await_count == 2


@pytest.mark.asyncio
class TestDispatcherNoUpdater:
    async def test_no_updater_returns_no_updater(self) -> None:
        debouncer = MagicMock(spec=PushDebouncer)
        debouncer._on_flush = None
        debouncer.add = AsyncMock()
        d = EventDispatcher(debouncer, updater=None)
        ev = _event()
        assert await d.dispatch(ev) == {"status": "no_updater"}
        debouncer.add.assert_not_called()
