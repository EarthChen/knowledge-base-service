"""Typed broadcast event bus for wiki subsystem (asyncio-based)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from core.log import get_logger

log = get_logger(__name__)

# Interval for queue reads while streaming; on timeout a heartbeat is yielded (SSE keepalive).
_STREAM_QUEUE_GET_TIMEOUT_SEC = 30.0


@dataclass
class WikiEvent:
    event_type: str
    repository: str
    data: dict[str, Any] = field(default_factory=dict)
    business_id: str = "default"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class WikiEventBus:
    """Broadcast wiki events to all connected SSE clients."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[WikiEvent | None]] = []

    def subscribe(self) -> asyncio.Queue[WikiEvent | None]:
        q: asyncio.Queue[WikiEvent | None] = asyncio.Queue(maxsize=100)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[WikiEvent | None]) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    async def publish(self, event: WikiEvent) -> None:
        log.debug("wiki_event_published", event_type=event.event_type, repository=event.repository)
        dead: list[asyncio.Queue] = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self.unsubscribe(q)

    async def stream(self, business_id: str | None = None) -> AsyncIterator[WikiEvent]:
        q = self.subscribe()
        hb_business_id = business_id if business_id is not None else "default"
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=_STREAM_QUEUE_GET_TIMEOUT_SEC)
                except asyncio.TimeoutError:
                    yield WikiEvent(
                        event_type="heartbeat",
                        repository="",
                        data={},
                        business_id=hb_business_id,
                    )
                    continue
                if event is None:
                    break
                if event.event_type == "close":
                    yield event
                    break
                if business_id is not None and event.business_id != business_id:
                    continue
                yield event
        finally:
            self.unsubscribe(q)

    async def shutdown(self) -> None:
        close_event = WikiEvent(
            event_type="close",
            repository="",
            data={"reason": "server_shutdown"},
        )
        for q in list(self._subscribers):
            try:
                q.put_nowait(close_event)
            except asyncio.QueueFull:
                pass
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        self._subscribers.clear()
