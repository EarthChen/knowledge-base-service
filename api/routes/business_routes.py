"""Business management CRUD API routes."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from auth import Role, require_role
from log import get_logger

log = get_logger(__name__)
router = APIRouter(prefix="/api/v1", tags=["business"])


class BusinessCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(..., min_length=1, max_length=500)


class BusinessUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class RepositoryBind(BaseModel):
    repositories: list[str]


@router.get("/businesses")
async def list_businesses(request: Request) -> dict[str, Any]:
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
    return {"businesses": businesses}


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
async def bind_repositories(request: Request, business_id: str, body: RepositoryBind) -> dict[str, Any]:
    graph = request.app.state.graph
    check = "MATCH (b:Business {uid: $bid}) RETURN b.uid"
    result = await graph.query(check, params={"bid": business_id})
    if not result.result_set:
        raise HTTPException(404, f"Business {business_id} not found")
    q = (
        "MATCH (b:Business {uid: $bid}) "
        "OPTIONAL MATCH (b)-[old:CONTAINS_REPO]->() DELETE old "
        "WITH b "
        "UNWIND $repos AS repo_name "
        "MERGE (r:Repository {name: repo_name}) "
        "MERGE (b)-[:CONTAINS_REPO]->(r)"
    )
    await graph.query(q, params={"bid": business_id, "repos": body.repositories})
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
