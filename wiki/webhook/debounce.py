"""Push webhook debouncing: merge rapid pushes per repo+branch with delivery idempotency."""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from wiki.webhook.event_model import ChangedFile, WebhookEvent


def branch_from_ref(ref: str) -> str:
    prefix = "refs/heads/"
    if ref.startswith(prefix):
        return ref[len(prefix) :]
    return ref


def _merge_changed_files(existing: dict[str, ChangedFile], incoming: list[ChangedFile]) -> None:
    for cf in incoming:
        existing[cf.path] = ChangedFile(path=cf.path, status=cf.status, old_path=cf.old_path)


@dataclass
class _PendingMerge:
    provider: str
    repository: str
    ref: str
    before: str
    after: str
    changed_files: dict[str, ChangedFile]
    sender: str
    timestamp: datetime  # earliest push time in window
    delivery_id: str  # latest merged delivery id for representation


class _DeliveryDeduper:
    """In-memory LRU-ish delivery_id cache with TTL for idempotent webhook retries."""

    def __init__(self, maxsize: int = 1000, ttl_seconds: int = 3600) -> None:
        self._maxsize = maxsize
        self._ttl = ttl_seconds
        self._seen: OrderedDict[str, float] = OrderedDict()

    def _purge_expired(self, now: float) -> None:
        expired = [k for k, ts in self._seen.items() if now - ts > self._ttl]
        for k in expired:
            del self._seen[k]

    def is_duplicate(self, delivery_id: str, now: float | None = None) -> bool:
        if not delivery_id:
            return False
        t = now if now is not None else time.monotonic()
        self._purge_expired(t)
        if delivery_id in self._seen:
            ts = self._seen[delivery_id]
            if t - ts <= self._ttl:
                self._seen.move_to_end(delivery_id)
                return True
            del self._seen[delivery_id]
        return False

    def remember(self, delivery_id: str, now: float | None = None) -> None:
        if not delivery_id:
            return
        t = now if now is not None else time.monotonic()
        self._purge_expired(t)
        self._seen[delivery_id] = t
        self._seen.move_to_end(delivery_id)
        while len(self._seen) > self._maxsize:
            self._seen.popitem(last=False)


class PushDebouncer:
    """Merges rapid push events for the same repo+branch within a time window."""

    def __init__(
        self,
        window_seconds: int = 30,
        max_pending: int = 1000,
        *,
        on_flush: Callable[[WebhookEvent], Any] | None = None,
    ) -> None:
        self._window = window_seconds
        self._max_pending = max_pending
        self._on_flush = on_flush
        self._deduper = _DeliveryDeduper(maxsize=1000, ttl_seconds=3600)
        self._pending: dict[tuple[str, str], _PendingMerge] = {}
        self._flush_tasks: dict[tuple[str, str], asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def pending_count(self) -> int:
        """Number of pending repo+branch combos."""
        return len(self._pending)

    async def add(self, event: WebhookEvent) -> None:
        """Add an event to the debounce buffer."""
        repo = event.repository
        branch = branch_from_ref(event.ref)
        key = (repo, branch)

        evicted: WebhookEvent | None = None
        async with self._lock:
            if self._deduper.is_duplicate(event.delivery_id):
                return
            self._deduper.remember(event.delivery_id)

            if key not in self._pending and len(self._pending) >= self._max_pending:
                oldest_key = next(iter(self._pending))
                evicted = await self._pop_and_merge_unlocked(oldest_key)

            pm = self._pending.get(key)
            if pm is None:
                self._pending[key] = _PendingMerge(
                    provider=event.provider,
                    repository=event.repository,
                    ref=event.ref,
                    before=event.before,
                    after=event.after,
                    changed_files={},
                    sender=event.sender,
                    timestamp=event.timestamp,
                    delivery_id=event.delivery_id,
                )
                _merge_changed_files(self._pending[key].changed_files, event.changed_files)
            else:
                pm.after = event.after
                pm.sender = event.sender
                pm.delivery_id = event.delivery_id
                _merge_changed_files(pm.changed_files, event.changed_files)

            self._schedule_flush_unlocked(key)

        if evicted is not None and self._on_flush is not None:
            maybe = self._on_flush(evicted)
            if asyncio.iscoroutine(maybe):
                await maybe

    def _schedule_flush_unlocked(self, key: tuple[str, str]) -> None:
        existing = self._flush_tasks.pop(key, None)
        if existing is not None:
            existing.cancel()

        async def _delayed() -> None:
            try:
                await asyncio.sleep(self._window)
            except asyncio.CancelledError:
                return
            async with self._lock:
                merged = await self._pop_and_merge_unlocked(key)
            if merged is not None and self._on_flush is not None:
                maybe = self._on_flush(merged)
                if asyncio.iscoroutine(maybe):
                    await maybe

        self._flush_tasks[key] = asyncio.create_task(_delayed())

    async def _pop_and_merge_unlocked(self, key: tuple[str, str]) -> WebhookEvent | None:
        task = self._flush_tasks.pop(key, None)
        if task is not None and not task.done():
            task.cancel()
        pm = self._pending.pop(key, None)
        if pm is None:
            return None
        files = sorted(pm.changed_files.values(), key=lambda c: c.path)
        return WebhookEvent(
            provider=pm.provider,
            event_type="push",
            delivery_id=pm.delivery_id,
            repository=pm.repository,
            ref=pm.ref,
            before=pm.before,
            after=pm.after,
            changed_files=files,
            sender=pm.sender,
            timestamp=pm.timestamp,
        )

    async def flush(self, repo: str, branch: str) -> WebhookEvent | None:
        """Flush merged event for repo+branch. Returns None if no pending events."""
        key = (repo, branch)
        async with self._lock:
            return await self._pop_and_merge_unlocked(key)
