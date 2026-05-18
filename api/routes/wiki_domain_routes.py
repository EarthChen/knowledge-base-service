"""REST API routes for domain hierarchy management."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from core.log import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/domains/hierarchy", tags=["wiki-domains"])

_domain_service = None


def set_domain_service(svc: Any) -> None:
    global _domain_service
    _domain_service = svc


def _get_domain_service() -> Any:
    if _domain_service is None:
        raise RuntimeError("DomainManagementService not initialized")
    return _domain_service


class UpdateDomainBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str | None = None


class CreateSubdomainBody(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = ""


class MoveDomainBody(BaseModel):
    target_parent_uid: str


class MergeDomainBody(BaseModel):
    source_uid: str
    target_uid: str


class MoveModuleDomainBody(BaseModel):
    module_uid: str
    target_domain: str


@router.patch("/{uid}")
async def rename_domain(
    uid: str,
    body: UpdateDomainBody,
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.rename_domain(business_id, uid, body.title, body.description)


@router.delete("/{uid}")
async def delete_domain(
    uid: str,
    promote_children: bool = Query(True),
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.delete_domain(business_id, uid, promote_children)


@router.post("/{uid}/children")
async def create_subdomain(
    uid: str,
    body: CreateSubdomainBody,
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.create_subdomain(business_id, uid, body.title, body.description)


@router.post("/{uid}/move")
async def move_domain(
    uid: str,
    body: MoveDomainBody,
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.move_domain(business_id, uid, body.target_parent_uid)


@router.post("/merge")
async def merge_domains(
    body: MergeDomainBody,
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.merge_domains(business_id, body.source_uid, body.target_uid)


@router.post("/move-module")
async def move_module_domain(
    body: MoveModuleDomainBody,
    business_id: str = Query(...),
) -> dict[str, Any]:
    svc = _get_domain_service()
    return await svc.move_module_domain(business_id, body.module_uid, body.target_domain)


@router.post("/reorganize")
async def reorganize_domains(
    business_id: str = Query(...),
    reset_user_edits: bool = Query(False),
) -> dict[str, Any]:
    """Manually trigger domain theme aggregation."""
    svc = _get_domain_service()
    return await svc.reorganize_domains(business_id, reset_user_edits=reset_user_edits)
