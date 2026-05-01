"""Settings management API endpoints."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, Path, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from api.exceptions import KbClientError, KbNotFound
from auth import Role, require_role
from services.settings_service import SettingsService
from store.settings_store import SettingsStore

require_settings_admin = require_role(Role.ADMIN)

settings_router = APIRouter(
    prefix="/api/v1/settings",
    tags=["settings"],
    dependencies=[Depends(require_settings_admin)],
)

HOT_RELOAD_KEYS = frozenset({"wiki.auto_update_on_index"})


def _get_store(request: Request) -> SettingsStore:
    store = getattr(request.app.state, "settings_store", None)
    if store is None:
        store = SettingsStore()
        request.app.state.settings_store = store
    return store


def _get_service(request: Request) -> SettingsService:
    return SettingsService(_get_store(request))


class SettingUpdateItem(BaseModel):
    key: str
    value: str
    category: str = "system"


class SettingsBatchUpdate(BaseModel):
    settings: list[SettingUpdateItem]


class TestConnectionRequest(BaseModel):
    target: str  # "falkordb" or "llm"


@settings_router.get("")
async def get_all_settings(
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    categories = await service.get_all_merged()
    return {
        "categories": categories,
        "notice": "Changes take effect after service restart",
    }


@settings_router.get("/{category}")
async def get_category_settings(
    category: str = Path(...),
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    items = await service.get_category(category)
    if not items:
        raise KbNotFound(f"Category '{category}' not found or empty")
    return {"category": category, "settings": items}


@settings_router.put("")
async def update_settings_batch(
    body: SettingsBatchUpdate,
    request: Request,
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    try:
        await service.update_settings([s.model_dump() for s in body.settings])
    except ValueError as e:
        raise KbClientError(str(e)) from e
    all_hot = all(s.key in HOT_RELOAD_KEYS for s in body.settings)
    return {
        "status": "ok",
        "updated": str(len(body.settings)),
        "restart_required": not all_hot,
    }


@settings_router.put("/{key:path}")
async def update_single_setting(
    key: str = Path(...),
    value: str = Body(..., embed=True),
    category: str = Body("system", embed=True),
    service: SettingsService = Depends(_get_service),
) -> dict[str, str]:
    try:
        await service.update_settings([{"key": key, "value": value, "category": category}])
    except ValueError as e:
        raise KbClientError(str(e)) from e
    return {"status": "ok", "key": key}


@settings_router.delete("/{key:path}")
async def delete_setting(
    key: str = Path(...),
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    deleted = await service.delete_setting(key)
    if not deleted:
        raise KbNotFound(f"Setting '{key}' not found")
    return {"status": "ok", "key": key}


@settings_router.post("/test-connection", response_model=None)
async def test_connection(
    body: TestConnectionRequest,
) -> dict[str, Any] | JSONResponse:
    """Test connectivity to external services."""
    if body.target == "falkordb":
        from config import get_settings
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore(get_settings().falkordb)
        try:
            await store.connect()
            return {"status": "ok", "target": "falkordb", "message": "Connection successful"}
        except Exception:
            logging.getLogger(__name__).exception("FalkorDB connection test failed")
            return JSONResponse(
                status_code=503,
                content={"status": "error", "target": "falkordb", "message": "Connection failed"},
            )
        finally:
            await store.close()
    if body.target == "llm":
        return JSONResponse(
            status_code=501,
            content={
                "status": "error",
                "target": "llm",
                "message": "LLM test not yet implemented",
            },
        )
    raise KbClientError(f"Unknown target: {body.target}")
