"""HTTP routes for inbound Git provider webhooks."""

from __future__ import annotations

import copy
from typing import Annotated, Any

from auth import Role, TokenInfo, require_role
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from wiki.webhook.debounce import PushDebouncer
from wiki.webhook.dispatcher import EventDispatcher, IncrementalUpdatePort
from wiki.webhook.receiver import WebhookReceiver

webhook_router = APIRouter(prefix="/api/v1/hooks", tags=["webhooks"])

_VALID_PROVIDERS = frozenset({"github", "gitlab", "gitea"})


def _mask_webhook_config_for_response(cfg: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of config with provider secrets redacted for API responses."""
    out = copy.deepcopy(cfg)
    providers = out.get("providers") or {}
    if isinstance(providers, dict):
        for prov in providers.values():
            if isinstance(prov, dict):
                sec = prov.get("secret")
                if isinstance(sec, str) and sec.strip():
                    prov["secret"] = "***configured***"
    return out


def default_webhook_config() -> dict[str, Any]:
    return {
        "enabled": False,
        "debounce_seconds": 30,
        "auto_update_branches": ["main", "master"],
        "providers": {},
    }


def apply_webhook_runtime(app: FastAPI) -> None:
    """Rebuild debouncer + dispatcher from ``app.state.webhook_config``."""
    cfg: dict[str, Any] = getattr(app.state, "webhook_config", None) or default_webhook_config()
    window = int(cfg.get("debounce_seconds", 30))
    branches = list(cfg.get("auto_update_branches") or ["main", "master"])
    updater = getattr(app.state, "webhook_incremental_updater", None)

    debouncer = PushDebouncer(window_seconds=window)
    dispatcher = EventDispatcher(debouncer, updater=updater, branches=branches)

    app.state.webhook_debouncer = debouncer
    app.state.webhook_dispatcher = dispatcher


def init_webhook_state(
    app: FastAPI,
    *,
    incremental_updater: IncrementalUpdatePort | None = None,
    initial_config: dict[str, Any] | None = None,
) -> None:
    """Attach webhook config and runtime components to ``app.state``.

    Called from application lifespan. Tests may pass an updater and/or config.
    """
    app.state.webhook_config = initial_config or default_webhook_config()
    if incremental_updater is not None:
        app.state.webhook_incremental_updater = incremental_updater
    apply_webhook_runtime(app)


def _signature_header(provider: str, request: Request) -> str | None:
    h = request.headers
    if provider == "github":
        return h.get("x-hub-signature-256")
    if provider == "gitlab":
        return h.get("x-gitlab-token")
    if provider == "gitea":
        return h.get("x-gitea-signature")
    return None


def _provider_secret(cfg: dict[str, Any], provider: str) -> str:
    providers = cfg.get("providers") or {}
    prov = providers.get(provider) or {}
    secret = prov.get("secret")
    return secret if isinstance(secret, str) else ""


class WebhookConfigUpdate(BaseModel):
    enabled: bool = False
    debounce_seconds: int = Field(default=30, ge=1, le=86400)
    auto_update_branches: list[str] = Field(default_factory=lambda: ["main", "master"])
    providers: dict[str, Any] = Field(default_factory=dict)


@webhook_router.get("/config")
async def get_webhook_config(
    request: Request,
    _auth: Annotated[TokenInfo | None, Depends(require_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Return the current webhook configuration."""
    cfg = getattr(request.app.state, "webhook_config", None)
    if cfg is None:
        return _mask_webhook_config_for_response(default_webhook_config())
    return _mask_webhook_config_for_response(dict(cfg))


@webhook_router.put("/config")
async def update_webhook_config(
    body: WebhookConfigUpdate,
    request: Request,
    _auth: Annotated[TokenInfo | None, Depends(require_role(Role.ADMIN))],
) -> dict[str, Any]:
    """Replace webhook configuration and rebuild debouncer/dispatcher."""
    updated = body.model_dump()
    request.app.state.webhook_config = updated
    apply_webhook_runtime(request.app)
    return _mask_webhook_config_for_response(updated)


@webhook_router.post("/{provider}")
async def receive_webhook(provider: str, request: Request) -> JSONResponse:
    """Receive and queue a webhook from GitHub/GitLab/Gitea."""
    if provider not in _VALID_PROVIDERS:
        raise HTTPException(status_code=400, detail="Unknown webhook provider")

    cfg: dict[str, Any] = getattr(request.app.state, "webhook_config", None) or default_webhook_config()
    if not cfg.get("enabled", False):
        raise HTTPException(status_code=503, detail="Webhooks are disabled")

    payload_bytes = await request.body()
    secret = _provider_secret(cfg, provider)
    sig = _signature_header(provider, request)
    if not WebhookReceiver.verify_signature(provider, secret, payload_bytes, sig):
        raise HTTPException(status_code=401, detail="Invalid webhook signature")

    headers = {str(k): v for k, v in request.headers.items()}
    event = WebhookReceiver.parse_event(provider, headers, payload_bytes)
    if event is None:
        return JSONResponse(status_code=200, content={"status": "ignored"})

    dispatcher: EventDispatcher | None = getattr(request.app.state, "webhook_dispatcher", None)
    if dispatcher is None:
        raise HTTPException(status_code=503, detail="Webhook dispatcher not initialized")

    result = await dispatcher.dispatch(event)
    if result.get("status") == "queued":
        return JSONResponse(
            status_code=202,
            content={"delivery_id": event.delivery_id, "status": "queued"},
        )
    if result.get("status") == "ignored":
        return JSONResponse(status_code=200, content={"status": "ignored"})
    if result.get("status") == "no_updater":
        return JSONResponse(status_code=200, content={"status": "no_updater"})
    return JSONResponse(status_code=200, content=result)
