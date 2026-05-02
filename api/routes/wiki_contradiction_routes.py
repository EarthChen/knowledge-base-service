"""Contradiction list and status transitions for wiki pages."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from core.auth import Role, require_role
from core.config import get_settings
from store.wiki_store import WikiStore

router = APIRouter(tags=["wiki", "contradictions"])


@router.get("/contradictions", response_model=None)
async def list_wiki_contradictions(
    request: Request,
    page_uid: str = Query(..., min_length=1, description="WikiPage uid"),
    include_resolved: bool = Query(default=False),
) -> dict[str, Any]:
    """List contradiction records linked to a wiki page."""
    if not get_settings().wiki.contradiction_detection_enabled:
        return {"items": []}
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(status_code=503, detail="Wiki store unavailable")
    store = WikiStore(raw_store)
    rows = await store.list_wiki_contradictions_for_page(
        page_uid,
        include_resolved=include_resolved,
    )
    return {"items": rows}


@router.patch(
    "/contradictions/{uid}/acknowledge",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def acknowledge_contradiction(
    request: Request,
    uid: str,
) -> dict[str, Any]:
    if not get_settings().wiki.contradiction_detection_enabled:
        raise HTTPException(status_code=404, detail="Contradiction feature disabled")
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(status_code=503, detail="Wiki store unavailable")
    store = WikiStore(raw_store)
    row = await store.get_wiki_contradiction(uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Contradiction not found")
    await store.set_wiki_contradiction_status(uid, "acknowledged")
    return {"uid": uid, "status": "acknowledged"}


@router.patch(
    "/contradictions/{uid}/resolve",
    response_model=None,
    dependencies=[Depends(require_role(Role.EDITOR))],
)
async def resolve_contradiction(
    request: Request,
    uid: str,
) -> dict[str, Any]:
    if not get_settings().wiki.contradiction_detection_enabled:
        raise HTTPException(status_code=404, detail="Contradiction feature disabled")
    raw_store: Any = getattr(request.app.state, "wiki_store", None)
    if raw_store is None:
        raise HTTPException(status_code=503, detail="Wiki store unavailable")
    store = WikiStore(raw_store)
    row = await store.get_wiki_contradiction(uid)
    if row is None:
        raise HTTPException(status_code=404, detail="Contradiction not found")
    now = int(time.time())
    await store.set_wiki_contradiction_status(
        uid,
        "resolved",
        resolved_at=now,
    )
    return {"uid": uid, "status": "resolved", "resolved_at": now}
