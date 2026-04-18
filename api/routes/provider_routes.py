"""Routes for LLM provider discovery."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from auth import Role, require_role
from config import get_settings
from llm.provider_factory import LLMProviderFactory, provider_config_from_llm

provider_router = APIRouter(
    prefix="/api/v1",
    tags=["llm"],
    dependencies=[Depends(require_role(Role.VIEWER))],
)


@provider_router.get("/llm/providers")
async def list_providers() -> dict[str, object]:
    """List configured LLM provider keys and the configured default."""
    settings = get_settings()
    cfg = provider_config_from_llm(settings.llm)
    factory = LLMProviderFactory(cfg)
    return {"providers": factory.list_providers(), "default": settings.llm.default_provider}
