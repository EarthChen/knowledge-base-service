"""Business management CRUD API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError

from core.auth import Role, require_role
from core.log import get_logger

from api.pagination import slice_page

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["business"])


class BusinessCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)


class BusinessUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RepositoryBind(BaseModel):
    repositories: list[str] = Field(..., min_length=1)


@router.get("/businesses")
async def list_businesses(
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=100),
) -> dict[str, Any]:
    graph = request.app.state.graph
    q = "MATCH (b:Business) RETURN b.uid AS id, b.name AS name, b.description AS description, b.created_at AS created_at ORDER BY b.created_at DESC"
    result = await graph.query(q)
    businesses = []
    for row in result.result_set:
        businesses.append({
            "id": row[0],
            "name": row[1],
            "description": row[2],
            "created_at": row[3],
        })
    total = len(businesses)
    window, _ = slice_page(businesses, offset=offset, limit=limit)
    out: dict[str, Any] = {"businesses": window, "total": total}
    if limit is not None:
        out["offset"] = offset
        out["limit"] = limit
    return out


@router.post("/businesses", status_code=201, dependencies=[Depends(require_role(Role.EDITOR))])
async def create_business(request: Request, body: BusinessCreate) -> dict[str, Any]:
    graph = request.app.state.graph
    uid = f"business:{uuid4().hex[:12]}"
    now = datetime.now(timezone.utc).isoformat()
    q = (
        "CREATE (b:Business {uid: $uid, name: $name, description: $desc, created_at: $now}) "
        "RETURN b.uid AS id"
    )
    result = await graph.query(q, params={"uid": uid, "name": body.name, "desc": body.description, "now": now})
    return {"id": uid, "name": body.name, "description": body.description}


@router.put("/businesses/{business_id}", dependencies=[Depends(require_role(Role.EDITOR))])
async def update_business(request: Request, business_id: str, body: BusinessUpdate) -> dict[str, Any]:
    graph = request.app.state.graph
    sets = []
    params: dict[str, Any] = {"bid": business_id}
    if body.name is not None:
        sets.append("b.name = $name")
        params["name"] = body.name
    if body.description is not None:
        sets.append("b.description = $desc")
        params["desc"] = body.description
    if not sets:
        raise HTTPException(400, "No fields to update")
    q = f"MATCH (b:Business {{uid: $bid}}) SET {', '.join(sets)} RETURN b.uid AS id, b.name AS name, b.description AS description"
    result = await graph.query(q, params=params)
    if not result.result_set:
        raise HTTPException(404, f"Business {business_id} not found")
    row = result.result_set[0]
    return {"id": row[0], "name": row[1], "description": row[2]}


@router.delete("/businesses/{business_id}", dependencies=[Depends(require_role(Role.EDITOR))])
async def delete_business(request: Request, business_id: str) -> dict[str, str]:
    graph = request.app.state.graph
    await graph.query(
        "MATCH (b:Business {uid: $bid})-[r:CONTAINS_REPO]->() DELETE r",
        params={"bid": business_id},
    )
    q = "MATCH (b:Business {uid: $bid}) DELETE b RETURN count(b) AS deleted"
    result = await graph.query(q, params={"bid": business_id})
    deleted = result.result_set[0][0] if result.result_set else 0
    if deleted == 0:
        raise HTTPException(404, f"Business {business_id} not found")
    return {"status": "deleted"}


@router.put("/businesses/{business_id}/repositories", dependencies=[Depends(require_role(Role.EDITOR))])
async def bind_repositories(
    request: Request,
    business_id: str,
    payload: dict[str, Any] = Body(...),
) -> dict[str, Any]:
    graph = request.app.state.graph
    if payload.get("repositories") == []:
        raise HTTPException(
            status_code=400,
            detail="repositories list must not be empty; use DELETE to unbind",
        )
    try:
        body = RepositoryBind.model_validate(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    check = "MATCH (b:Business {uid: $bid}) RETURN b.uid"
    result = await graph.query(check, params={"bid": business_id})
    if not result.result_set:
        raise HTTPException(404, f"Business {business_id} not found")
    await graph.query(
        "MATCH (b:Business {uid: $bid})-[r:CONTAINS_REPO]->() DELETE r",
        params={"bid": business_id},
    )
    bind_q = (
        "MATCH (b:Business {uid: $bid}) "
        "UNWIND $repos AS repo_name "
        "MERGE (r:Repository {name: repo_name}) "
        "MERGE (b)-[:CONTAINS_REPO]->(r)"
    )
    await graph.query(bind_q, params={"bid": business_id, "repos": body.repositories})
    return {"business_id": business_id, "repositories": body.repositories}


@router.get("/businesses/{business_id}/repositories")
async def get_repositories(request: Request, business_id: str) -> dict[str, Any]:
    graph = request.app.state.graph
    q = (
        "MATCH (b:Business {uid: $bid})-[:CONTAINS_REPO]->(r) "
        "RETURN r.name AS repo ORDER BY repo"
    )
    result = await graph.query(q, params={"bid": business_id})
    repos = [row[0] for row in result.result_set]
    return {"business_id": business_id, "repositories": repos}
