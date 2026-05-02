from __future__ import annotations

import os
from pathlib import Path

from core.auth import get_auth_mode
from core.config import Settings
from core.log import get_logger

log = get_logger(__name__)


def startup_auth_gate(settings: Settings) -> None:
    """Log when no tokens are configured; optionally fail startup if ``require_auth``."""
    if get_auth_mode() == "open":
        log.warning(
            "no_api_tokens_configured",
            detail=(
                "No API tokens configured — all endpoints are accessible without authentication. "
                "Set API_TOKEN, API_TOKENS, or TOKENS_FILE for production deployments."
            ),
        )
        if settings.require_auth:
            raise RuntimeError(
                "require_auth is enabled but no API tokens are configured. "
                "Set API_TOKEN, API_TOKENS, or TOKENS_FILE before starting the service.",
            )


def enforce_production_security(settings: Settings) -> None:
    """Fail-closed in production: require authentication."""
    env = os.environ.get("KB_ENV", "development").lower()
    if env != "production":
        return
    if not settings.require_auth:
        log.critical(
            "production_require_auth_disabled",
            detail="KB_ENV=production but require_auth is false; refusing to start.",
        )
        raise RuntimeError(
            "KB_ENV=production requires require_auth=true. "
            "Set REQUIRE_AUTH=true and configure API tokens.",
        )
    if not settings.api_token and not settings.api_tokens and not Path(settings.tokens_file).exists():
        log.critical(
            "production_no_api_tokens",
            detail="KB_ENV=production but no API tokens configured; refusing to start.",
        )
        raise RuntimeError(
            "KB_ENV=production requires at least one API token. "
            "Set API_TOKEN, API_TOKENS, or create tokens.yaml.",
        )


def init_security(settings: Settings) -> None:
    """Auth gate + production security check."""
    enforce_production_security(settings)
    startup_auth_gate(settings)
