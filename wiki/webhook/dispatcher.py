"""Route normalized webhook events to incremental update handlers."""

from __future__ import annotations

import asyncio
from typing import Any, Protocol, runtime_checkable

from wiki.webhook.debounce import PushDebouncer, branch_from_ref
from wiki.webhook.event_model import WebhookEvent


@runtime_checkable
class IncrementalUpdatePort(Protocol):
    async def update(self, repository: str, changed_files: list) -> Any: ...


class EventDispatcher:
    """Routes webhook events to appropriate handlers."""

    def __init__(
        self,
        debouncer: PushDebouncer,
        updater: IncrementalUpdatePort | None = None,
        branches: list[str] | None = None,
    ) -> None:
        self._debouncer = debouncer
        self._updater = updater
        self._branches = frozenset(branches or ["main", "master"])

        prev = debouncer._on_flush

        async def flush_handler(ev: WebhookEvent) -> None:
            if prev is not None:
                prev_result = prev(ev)
                if asyncio.iscoroutine(prev_result):
                    await prev_result
            if self._updater is not None:
                await self._updater.update(ev.repository, ev.changed_files)

        debouncer._on_flush = flush_handler

    async def dispatch(self, event: WebhookEvent) -> dict:
        """Process a webhook event.

        Returns dispatch result dict with status.
        Only processes push events for configured branches.
        """
        if event.event_type != "push":
            return {"status": "ignored"}

        branch = branch_from_ref(event.ref)
        if branch not in self._branches:
            return {"status": "ignored"}

        if self._updater is None:
            return {"status": "no_updater"}

        await self._debouncer.add(event)
        return {"status": "queued"}
