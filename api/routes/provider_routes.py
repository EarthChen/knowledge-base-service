"""Routes for LLM provider discovery."""

from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends, Path

from api.exceptions import KbClientError, KbNotFound
from auth import Role, require_role
from config import get_settings
from llm.provider_factory import LLMProviderFactory, provider_config_from_llm

provider_router = APIRouter(
    prefix="/api/v1",
    tags=["llm"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)

require_admin = require_role(Role.ADMIN)


@provider_router.get("/llm/providers")
async def list_providers() -> dict[str, object]:
    """List configured LLM provider keys and the configured default."""
    settings = get_settings()
    cfg = provider_config_from_llm(settings.llm)
    factory = LLMProviderFactory(cfg)
    return {"providers": factory.list_providers(), "default": settings.llm.default_provider}


@provider_router.get(
    "/llm/providers/{name}/models",
    dependencies=[Depends(require_admin)],
)
async def list_provider_models(name: str = Path(...)) -> dict[str, object]:
    """Discover models available on a given provider via OpenAI-compatible /models API."""
    settings = get_settings()
    cfg = provider_config_from_llm(settings.llm)

    if name == "gateway":
        base_url = settings.llm.base_url.rstrip("/")
        api_key = settings.llm.api_key
    elif name in cfg.providers:
        pcfg = cfg.providers[name]
        base_url = pcfg.get("base_url", "").rstrip("/")
        api_key = pcfg.get("api_key", "")
    else:
        raise KbNotFound(f"Provider '{name}' not configured")

    if not base_url:
        raise KbClientError(f"Provider '{name}' has no base_url configured")

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = await client.get(f"{base_url}/models", headers=headers)
            resp.raise_for_status()
            data = resp.json()
            models = [m["id"] for m in data.get("data", []) if "id" in m]
            return {"provider": name, "models": sorted(models)}
    except httpx.HTTPStatusError as exc:
        raise KbClientError(
            f"Failed to list models for '{name}': {exc.response.status_code}"
        ) from exc
    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        raise KbClientError(f"Cannot reach provider '{name}': {exc}") from exc
