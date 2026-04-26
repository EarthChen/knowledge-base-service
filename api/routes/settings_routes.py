"""Settings management API endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Path
from pydantic import BaseModel

from services.settings_service import SettingsService
from store.settings_store import SettingsStore

settings_router = APIRouter(prefix="/api/v1/settings", tags=["settings"])


def _get_service() -> SettingsService:
    return SettingsService(SettingsStore())


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
    return {"categories": categories}


@settings_router.get("/{category}")
async def get_category_settings(
    category: str = Path(...),
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    items = await service.get_category(category)
    if not items:
        raise HTTPException(status_code=404, detail=f"Category '{category}' not found or empty")
    return {"category": category, "settings": items}


@settings_router.put("")
async def update_settings_batch(
    body: SettingsBatchUpdate,
    service: SettingsService = Depends(_get_service),
) -> dict[str, str]:
    await service.update_settings([s.model_dump() for s in body.settings])
    return {"status": "ok", "updated": str(len(body.settings))}


@settings_router.put("/{key:path}")
async def update_single_setting(
    key: str = Path(...),
    value: str = Body(..., embed=True),
    category: str = Body("system", embed=True),
    service: SettingsService = Depends(_get_service),
) -> dict[str, str]:
    await service.update_settings([{"key": key, "value": value, "category": category}])
    return {"status": "ok", "key": key}


@settings_router.delete("/{key:path}")
async def delete_setting(
    key: str = Path(...),
    service: SettingsService = Depends(_get_service),
) -> dict[str, Any]:
    deleted = await service.delete_setting(key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Setting '{key}' not found")
    return {"status": "ok", "key": key}


@settings_router.post("/test-connection")
async def test_connection(
    body: TestConnectionRequest,
) -> dict[str, Any]:
    """Test connectivity to external services."""
    if body.target == "falkordb":
        from config import get_settings
        from store.falkordb_store import FalkorDBStore

        store = FalkorDBStore(get_settings().falkordb)
        try:
            await store.connect()
            return {"status": "ok", "target": "falkordb", "message": "Connection successful"}
        except Exception as e:
            return {"status": "error", "target": "falkordb", "message": str(e)}
        finally:
            await store.close()
    elif body.target == "llm":
        return {"status": "ok", "target": "llm", "message": "LLM test not yet implemented"}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown target: {body.target}")
