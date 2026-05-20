"""Business management CRUD API routes.

All operations delegate to BusinessManager (Redis) as the single source of truth.
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

import api.kb_state as kb_state
from api.exceptions import KbServiceUnavailable
from api.pagination import slice_page
from core.auth import Role, require_role
from core.log import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["business"])


class BusinessCreate(BaseModel):
    id: str = Field(..., min_length=1, max_length=63, pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)


class BusinessUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RepositoryBind(BaseModel):
    repositories: list[str] = Field(..., min_length=1)


def _get_bm():
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    return kb_state.registry.business_manager


@router.get("/businesses", dependencies=[Depends(require_role(Role.VIEWER))])
async def list_businesses(
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> dict[str, Any]:
    bm = _get_bm()
    loop = asyncio.get_running_loop()
    businesses = await loop.run_in_executor(None, bm.list_businesses)
    total = len(businesses)
    window, _ = slice_page(businesses, offset=offset, limit=limit)
    out: dict[str, Any] = {"businesses": window, "total": total}
    if limit is not None:
        out["offset"] = offset
        out["limit"] = limit
    return out


@router.post("/businesses", status_code=201, dependencies=[Depends(require_role(Role.ADMIN))])
async def create_business(body: BusinessCreate) -> dict[str, Any]:
    bm = _get_bm()
    loop = asyncio.get_running_loop()
    try:
        meta = await loop.run_in_executor(
            None, lambda: bm.create_business(body.id, body.name, body.description),
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return meta


@router.put("/businesses/{business_id}", dependencies=[Depends(require_role(Role.EDITOR))])
async def update_business(business_id: str, body: BusinessUpdate) -> dict[str, Any]:
    if body.name is None and body.description is None:
        raise HTTPException(400, "No fields to update")
    bm = _get_bm()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None, lambda: bm.update_business(business_id, name=body.name, description=body.description),
    )
    if result is None:
        raise HTTPException(404, f"Business {business_id} not found")
    return result


@router.delete("/businesses/{business_id}", dependencies=[Depends(require_role(Role.ADMIN))])
async def delete_business(business_id: str) -> dict[str, str]:
    """Delete a business: FalkorDB graph, cached service, and Redis metadata."""
    if kb_state.registry is None:
        raise KbServiceUnavailable("Service not ready")
    try:
        await kb_state.registry.remove_service(business_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"status": "deleted"}


@router.put("/businesses/{business_id}/repositories", dependencies=[Depends(require_role(Role.EDITOR))])
async def bind_repositories(business_id: str, body: RepositoryBind) -> dict[str, Any]:
    bm = _get_bm()
    loop = asyncio.get_running_loop()
    meta = await loop.run_in_executor(None, bm.get_business, business_id)
    if meta is None:
        raise HTTPException(404, f"Business {business_id} not found")
    repos = await loop.run_in_executor(
        None, lambda: bm.set_repos(business_id, body.repositories),
    )
    return {"business_id": business_id, "repositories": repos}


@router.get("/businesses/{business_id}/repositories", dependencies=[Depends(require_role(Role.VIEWER))])
async def get_repositories(business_id: str) -> dict[str, Any]:
    bm = _get_bm()
    loop = asyncio.get_running_loop()
    repos = await loop.run_in_executor(None, bm.get_repos, business_id)
    return {"business_id": business_id, "repositories": repos}
