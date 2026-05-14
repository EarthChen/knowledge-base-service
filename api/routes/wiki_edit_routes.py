"""Wiki AI edit session REST + SSE."""

from __future__ import annotations

import asyncio
import json
import threading
import time
from collections import defaultdict
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.routes.wiki_shared import get_wiki_edit_service_dep
from core.auth import Role, require_role
from wiki.agents.edit_agent import EditEventQueue
from wiki.edit_service import WikiEditService

# Tunable for tests / operations (sliding idle SSE — default 60s since last event).
_SSE_IDLE_TIMEOUT_SEC = 60.0
_SSE_WAIT_CAP_SEC = 30.0

# Extra per-IP cap for expensive session creation (runs in addition to global RateLimiterMiddleware).
_EDIT_SESSION_BURST_WINDOW_SEC = 60.0
_EDIT_SESSION_BURST_LIMIT = 12

_edit_session_burst_times: dict[str, list[float]] = defaultdict(list)
_edit_burst_lock = threading.Lock()


def _clear_edit_session_burst_counters() -> None:
    """Test hook: reset per-IP burst bookkeeping."""
    with _edit_burst_lock:
        _edit_session_burst_times.clear()


async def enforce_edit_session_creation_burst_limit(request: Request) -> None:
    lim = _EDIT_SESSION_BURST_LIMIT
    if lim <= 0:
        return
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _edit_burst_lock:
        window = _edit_session_burst_times[ip]
        cutoff = now - _EDIT_SESSION_BURST_WINDOW_SEC
        window[:] = [ts for ts in window if ts >= cutoff]
        if len(window) >= lim:
            raise HTTPException(
                status_code=429,
                detail=(
                    "Wiki edit session creation rate limit exceeded for this client. "
                    "Try again shortly or lower request volume."
                ),
            )
        window.append(now)


router = APIRouter(
    tags=["wiki-edit"],
    dependencies=[Depends(require_role(Role.EDITOR))],
)


class CreateEditSessionBody(BaseModel):
    """Start an edit session from the current markdown and a user prompt."""

    prompt: str = Field(..., min_length=1, max_length=2000)
    current_content: str = Field(..., min_length=1)


class SendMessageBody(BaseModel):
    """Follow-up instruction in an existing edit session."""

    prompt: str = Field(..., min_length=1, max_length=2000)


async def _iter_edit_session_sse(queue: EditEventQueue) -> AsyncIterator[bytes]:
    idle_timeout = _SSE_IDLE_TIMEOUT_SEC
    last_event_time = time.monotonic()
    while True:
        elapsed = time.monotonic() - last_event_time
        remaining = idle_timeout - elapsed
        if remaining <= 0:
            break
        try:
            evt = await asyncio.wait_for(
                queue.get(),
                timeout=min(_SSE_WAIT_CAP_SEC, remaining),
            )
        except asyncio.TimeoutError:
            yield b": keepalive\n\n"
            continue
        last_event_time = time.monotonic()
        line = json.dumps(asdict(evt), ensure_ascii=False, default=str)
        yield f"event: {evt.type}\ndata: {line}\n\n".encode()
        if evt.type in ("done", "error"):
            return


@router.post(
    "/pages/{page_uid:path}/edit-session",
    response_model=None,
    dependencies=[Depends(enforce_edit_session_creation_burst_limit)],
)
async def create_edit_session(
    page_uid: str,
    body: CreateEditSessionBody,
    svc: WikiEditService = Depends(get_wiki_edit_service_dep),
) -> dict[str, str]:
    decoded = unquote(page_uid)
    session_id = await svc.create_session(decoded, body.current_content)
    await svc.send_message(session_id, body.prompt)
    return {"session_id": session_id}


@router.post(
    "/pages/{page_uid:path}/edit-session/{session_id}/message",
    response_model=None,
)
async def send_edit_session_message(
    page_uid: str,
    session_id: str,
    body: SendMessageBody,
    svc: WikiEditService = Depends(get_wiki_edit_service_dep),
) -> dict[str, str]:
    await svc.send_message(session_id, body.prompt)
    return {"status": "processing"}


@router.get("/pages/{page_uid:path}/edit-session/{session_id}/stream", response_model=None)
async def stream_edit_session(
    page_uid: str,
    session_id: str,
    svc: WikiEditService = Depends(get_wiki_edit_service_dep),
) -> StreamingResponse:
    _ = unquote(page_uid)
    queue = svc.get_event_queue(session_id)
    if queue is None:
        raise HTTPException(status_code=404, detail="edit stream not ready or already consumed")
    return StreamingResponse(
        _iter_edit_session_sse(queue),
        media_type="text/event-stream",
    )


@router.post(
    "/pages/{page_uid:path}/edit-session/{session_id}/apply",
    response_model=None,
)
async def apply_edit_session(
    page_uid: str,
    session_id: str,
    svc: WikiEditService = Depends(get_wiki_edit_service_dep),
) -> dict[str, Any]:
    _ = unquote(page_uid)
    return await svc.apply_edit(session_id)


@router.delete(
    "/pages/{page_uid:path}/edit-session/{session_id}",
    response_model=None,
)
async def delete_edit_session(
    page_uid: str,
    session_id: str,
    svc: WikiEditService = Depends(get_wiki_edit_service_dep),
) -> dict[str, str]:
    _ = unquote(page_uid)
    await svc.delete_session(session_id)
    return {"status": "deleted"}
