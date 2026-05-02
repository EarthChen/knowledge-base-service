"""Role-scoped API routers for the core Knowledge Base HTTP API."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from core.auth import Role, require_role

viewer_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.VIEWER))])
editor_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.EDITOR))])
admin_router = APIRouter(prefix="/api/v1", dependencies=[Depends(require_role(Role.ADMIN))])
public_router = APIRouter(prefix="/api/v1")
