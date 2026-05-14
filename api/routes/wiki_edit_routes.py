"""Wiki AI edit session REST + SSE (streaming placeholder)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import unquote

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from api.exceptions import KbServiceUnavailable

router = APIRouter(tags=["wiki-edit"])


class CreateEditSessionBody(BaseModel):
    """Start an edit session from the current markdown and a user prompt."""

    prompt: str = Field(..., min_length=1)
    current_content: str = Field(..., min_length=1)


class SendMessageBody(BaseModel):
    """Follow-up instruction in an existing edit session."""

    prompt: str = Field(..., min_length=1)


def _get_edit_service(request: Request) -> Any:
    svc = getattr(request.app.state, "wiki_edit_service", None)
    if svc is None:
        raise KbServiceUnavailable("Wiki edit is not configured")
    return svc


@router.post("/pages/{page_uid:path}/edit-session", response_model=None)
async def create_edit_session(
    page_uid: str,
    body: CreateEditSessionBody,
    svc: Any = Depends(_get_edit_service),
) -> dict[str, str]:
    decoded = unquote(page_uid)
    session_id = await svc.create_session(decoded, body.prompt, body.current_content)
    await svc.send_message(session_id, decoded, body.prompt, body.current_content)
    return {"session_id": str(session_id)}


@router.post(
    "/pages/{page_uid:path}/edit-session/{session_id}/message",
    response_model=None,
)
async def send_edit_session_message(
    page_uid: str,
    session_id: str,
    body: SendMessageBody,
    svc: Any = Depends(_get_edit_service),
) -> dict[str, str]:
    decoded = unquote(page_uid)
    await svc.send_message(session_id, decoded, body.prompt)
    return {"status": "processing"}


async def _wiki_edit_stream_placeholder() -> AsyncIterator[bytes]:
    """Yield a no-op SSE comment until the real stream is wired."""
    yield b": wiki edit stream placeholder\n\n"


@router.get("/pages/{page_uid:path}/edit-session/{session_id}/stream", response_model=None)
async def stream_edit_session(
    page_uid: str,  # reserved for WikiEditService stream wiring
    session_id: str,
    _svc: Any = Depends(_get_edit_service),
) -> StreamingResponse:
    return StreamingResponse(
        _wiki_edit_stream_placeholder(),
        media_type="text/event-stream",
    )


@router.post(
    "/pages/{page_uid:path}/edit-session/{session_id}/apply",
    response_model=None,
)
async def apply_edit_session(
    page_uid: str,
    session_id: str,
    svc: Any = Depends(_get_edit_service),
) -> dict[str, Any]:
    decoded = unquote(page_uid)
    return await svc.apply_edit(session_id, decoded)


@router.delete(
    "/pages/{page_uid:path}/edit-session/{session_id}",
    response_model=None,
)
async def delete_edit_session(
    page_uid: str,
    session_id: str,
    svc: Any = Depends(_get_edit_service),
) -> dict[str, str]:
    decoded = unquote(page_uid)
    await svc.delete_session(session_id, decoded)
    return {"status": "deleted"}
