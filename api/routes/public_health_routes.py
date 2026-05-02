"""Route group: public_health_routes (extracted from main)."""
from __future__ import annotations

import asyncio
import json
from typing import Any
from fastapi import Depends, HTTPException
from fastapi.responses import JSONResponse
import api.kb_state as kb_state
from api.routes import kb_routers
from auth import get_current_role
from log import get_logger
from services.kb_service import KnowledgeBaseService
from store.graph_queries import GraphQueryRepository, validate_architecture_class_search
from utils.git_utils import looks_like_git_url

log = get_logger(__name__)
viewer_router = kb_routers.viewer_router
editor_router = kb_routers.editor_router
admin_router = kb_routers.admin_router
public_router = kb_routers.public_router
@public_router.get("/health")
async def health() -> JSONResponse:
    if kb_state.registry is None:
        return JSONResponse(
            status_code=503,
            content={"status": "initializing", "detail": "registry not started"},
        )
    body, status_code = await kb_state.registry.readiness()
    if status_code != 200:
        return JSONResponse(status_code=status_code, content=body)

    falkordb = await kb_state.registry.falkordb_graph_ping()
    payload: dict[str, Any] = dict(body)
    components: dict[str, str] = dict(payload.get("components") or {})
    components["falkordb"] = falkordb
    payload["components"] = components
    if falkordb != "ready":
        payload["status"] = "degraded"
        payload["falkordb"] = "unreachable"
    return JSONResponse(status_code=200, content=payload)


@public_router.get("/auth/me")
async def auth_me(info: dict[str, Any] = Depends(get_current_role)) -> dict[str, Any]:
    """Return the current token's role information."""
    return info


