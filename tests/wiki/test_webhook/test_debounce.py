"""Tests for wiki.webhook.debounce — PushDebouncer merge, dedupe, and flush."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import pytest

from wiki.webhook.debounce import PushDebouncer
from wiki.webhook.event_model import ChangedFile, WebhookEvent


def _push_event(
    repo: str,
    branch: str,
    before: str,
    after: str,
    *,
    delivery_id: str = "delivery-1",
    files: list[ChangedFile] | None = None,
    ts: datetime | None = None,
) -> WebhookEvent:
    return WebhookEvent(
        provider="github",
        event_type="push",
        delivery_id=delivery_id,
        repository=repo,
        ref=f"refs/heads/{branch}",
        before=before,
        after=after,
        changed_files=list(files or []),
        sender="alice",
        timestamp=ts or datetime(2026, 4, 18, 12, 0, 0, tzinfo=UTC),
    )


@pytest.mark.asyncio
class TestPushDebouncerFlushSingle:
    async def test_single_event_flush_returns_merged_push(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        e = _push_event("org/repo", "main", "a" * 40, "b" * 40, files=[ChangedFile(path="x.py", status="added")])
        await d.add(e)
        assert d.pending_count() == 1
        out = await d.flush("org/repo", "main")
        assert out is not None
        assert out.before == e.before
        assert out.after == e.after
        assert out.changed_files == [ChangedFile(path="x.py", status="added")]
        assert d.pending_count() == 0


@pytest.mark.asyncio
class TestPushDebouncerMerge:
    async def test_same_repo_branch_merges_before_after_and_files(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        e1 = _push_event(
            "org/repo",
            "main",
            "1111111111111111111111111111111111111111",
            "2222222222222222222222222222222222222222222",
            delivery_id="d1",
            files=[ChangedFile(path="a.py", status="added"), ChangedFile(path="b.py", status="modified")],
        )
        e2 = _push_event(
            "org/repo",
            "main",
            "3333333333333333333333333333333333333333",
            "4444444444444444444444444444444444444444",
            delivery_id="d2",
            files=[
                ChangedFile(path="b.py", status="removed"),
                ChangedFile(path="c.py", status="added"),
            ],
        )
        await d.add(e1)
        await d.add(e2)
        assert d.pending_count() == 1
        out = await d.flush("org/repo", "main")
        assert out is not None
        assert out.before == e1.before
        assert out.after == e2.after
        assert out.delivery_id == "d2"
        by_path = {cf.path: cf for cf in out.changed_files}
        assert by_path["a.py"].status == "added"
        assert by_path["b.py"].status == "removed"
        assert by_path["c.py"].status == "added"


@pytest.mark.asyncio
class TestDeliveryDedupe:
    async def test_same_delivery_id_second_add_ignored(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        e = _push_event(
            "r/a",
            "main",
            "a" * 40,
            "b" * 40,
            delivery_id="same-id",
            files=[ChangedFile(path="f.py", status="added")],
        )
        await d.add(e)
        e2 = _push_event(
            "r/a",
            "main",
            "c" * 40,
            "d" * 40,
            delivery_id="same-id",
            files=[ChangedFile(path="g.py", status="added")],
        )
        await d.add(e2)
        out = await d.flush("r/a", "main")
        assert out is not None
        assert out.after == e.after
        assert len(out.changed_files) == 1


@pytest.mark.asyncio
class TestSeparateKeys:
    async def test_different_repos_not_merged(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        await d.add(_push_event("org/a", "main", "a" * 40, "b" * 40, delivery_id="d-a"))
        await d.add(_push_event("org/b", "main", "c" * 40, "d" * 40, delivery_id="d-b"))
        assert d.pending_count() == 2
        oa = await d.flush("org/a", "main")
        ob = await d.flush("org/b", "main")
        assert oa is not None and oa.repository == "org/a"
        assert ob is not None and ob.repository == "org/b"

    async def test_different_branches_not_merged(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        await d.add(_push_event("org/r", "main", "a" * 40, "b" * 40, delivery_id="dm"))
        await d.add(_push_event("org/r", "dev", "c" * 40, "d" * 40, delivery_id="dd"))
        assert d.pending_count() == 2


@pytest.mark.asyncio
class TestWindowAutoFlush:
    async def test_after_window_pending_cleared_and_flush_returns_none(self) -> None:
        flushed: list[WebhookEvent] = []

        async def capture(ev: WebhookEvent) -> None:
            flushed.append(ev)

        d = PushDebouncer(window_seconds=0.05, on_flush=capture)
        e = _push_event("org/x", "main", "a" * 40, "b" * 40, delivery_id="auto-1")
        await d.add(e)
        await asyncio.sleep(0.15)
        assert d.pending_count() == 0
        assert len(flushed) == 1
        assert flushed[0].repository == "org/x"
        manual = await d.flush("org/x", "main")
        assert manual is None


@pytest.mark.asyncio
class TestPendingCount:
    async def test_pending_count_tracks_distinct_repo_branch(self) -> None:
        d = PushDebouncer(window_seconds=3600)
        assert d.pending_count() == 0
        await d.add(_push_event("a", "main", "a" * 40, "b" * 40, delivery_id="p1"))
        assert d.pending_count() == 1
        await d.add(_push_event("b", "main", "a" * 40, "b" * 40, delivery_id="p2"))
        assert d.pending_count() == 2
