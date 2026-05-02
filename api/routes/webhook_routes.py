"""HTTP routes for inbound Git provider webhooks."""

from __future__ import annotations

import asyncio
import copy
from typing import Annotated, Any

from core.auth import Role, TokenInfo, require_role
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api.exceptions import KbClientError, KbServiceUnavailable
from wiki.webhook.debounce import PushDebouncer
from wiki.webhook.dispatcher import EventDispatcher, IncrementalUpdatePort
from wiki.webhook.receiver import WebhookReceiver

webhook_router = APIRouter(prefix="/api/v1/hooks", tags=["webhooks"])

_VALID_PROVIDERS = frozenset({"github", "gitlab", "gitea"})


def _extract_files_from_push_payload(payload: dict[str, Any]) -> list[str]:
    """Extract unique changed files from a GitHub/GitLab push webhook payload."""
    files: set[str] = set()
    for commit in payload.get("commits", []):
        if not isinstance(commit, dict):
            continue
        files.update(commit.get("added", []) or [])
        files.update(commit.get("modified", []) or [])
        files.update(commit.get("removed", []) or [])
    return sorted(files)


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


class WebhookWikiIngestBody(BaseModel):
    repository: str = Field(..., min_length=1)
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Push webhook JSON body; files are taken from commits[].added/modified/removed.",
    )


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


@webhook_router.post("/ingest/push")
async def webhook_wiki_ingest_push(
    request: Request,
    body: WebhookWikiIngestBody,
    _auth: Annotated[TokenInfo | None, Depends(require_role(Role.EDITOR))],
) -> dict[str, Any]:
    """Incremental wiki ingest from a push-style payload (e.g. GitHub push ``commits``)."""
    files = _extract_files_from_push_payload(body.payload)
    if not files:
        return {
            "pages_regenerated": 0,
            "pages_total": 0,
            "trigger": "git_push",
            "message": "No files in push payload",
        }

    detector = getattr(request.app.state, "change_detector", None)
    factory = getattr(request.app.state, "wiki_service_factory", None)
    if detector is None or factory is None:
        raise KbServiceUnavailable("Incremental ingest not configured")

    affected = await detector.detect_from_file_list(
        body.repository, files, trigger="git_push",
    )
    out = factory()
    service = await out if asyncio.iscoroutine(out) else out
    return await service.bump_affected_wiki_pages(body.repository, affected)


@webhook_router.post("/{provider}")
async def receive_webhook(provider: str, request: Request) -> JSONResponse:
    """Receive and queue a webhook from GitHub/GitLab/Gitea."""
    if provider not in _VALID_PROVIDERS:
        raise KbClientError("Unknown webhook provider")

    cfg: dict[str, Any] = getattr(request.app.state, "webhook_config", None) or default_webhook_config()
    if not cfg.get("enabled", False):
        raise KbServiceUnavailable("Webhooks are disabled")

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
        raise KbServiceUnavailable("Webhook dispatcher not initialized")

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
