"""Role-based access control with token-business binding.

Token configuration sources (priority high → low):
  1. tokens.yaml file (structured, supports business binding)
  2. API_TOKENS env var (legacy: role:token comma-separated)
  3. API_TOKEN env var (legacy: single admin token)

When none configured, all endpoints are open (no auth).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from pathlib import Path
from typing import Any

import yaml
from fastapi import Depends, Header, HTTPException

from config import Settings, get_settings
from log import get_logger

log = get_logger(__name__)


class Role(IntEnum):
    VIEWER = 1
    EDITOR = 2
    ADMIN = 3


_ROLE_MAP: dict[str, Role] = {
    "viewer": Role.VIEWER,
    "editor": Role.EDITOR,
    "admin": Role.ADMIN,
}


@dataclass(frozen=True, slots=True)
class TokenInfo:
    role: Role
    business_id: str | None = None


_token_registry: dict[str, TokenInfo] | None = None


def _load_yaml_tokens(path: Path) -> dict[str, TokenInfo]:
    """Parse tokens.yaml into a token→TokenInfo mapping."""
    registry: dict[str, TokenInfo] = {}
    if not path.is_file():
        return registry

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        return registry

    for entry in data.get("tokens", []):
        if not isinstance(entry, dict):
            continue
        token = str(entry.get("token", "")).strip()
        role_str = str(entry.get("role", "")).strip().lower()
        business = entry.get("business")

        if not token or role_str not in _ROLE_MAP:
            continue

        biz_id = str(business).strip() if business else None
        registry[token] = TokenInfo(role=_ROLE_MAP[role_str], business_id=biz_id)

    return registry


def _load_env_tokens(settings: Settings) -> dict[str, TokenInfo]:
    """Fallback: parse API_TOKENS / API_TOKEN env vars (no business binding)."""
    registry: dict[str, TokenInfo] = {}

    if settings.api_tokens:
        for entry in settings.api_tokens.split(","):
            entry = entry.strip()
            if ":" not in entry:
                continue
            role_str, token = entry.split(":", 1)
            role_str = role_str.strip().lower()
            token = token.strip()
            if token and role_str in _ROLE_MAP:
                registry[token] = TokenInfo(role=_ROLE_MAP[role_str])

    if settings.api_token and settings.api_token not in registry:
        registry[settings.api_token] = TokenInfo(role=Role.ADMIN)

    return registry


def _build_token_registry(settings: Settings) -> dict[str, TokenInfo]:
    yaml_path = Path(settings.tokens_file)
    if not yaml_path.is_absolute():
        yaml_path = Path(__file__).resolve().parent / yaml_path

    registry = _load_yaml_tokens(yaml_path)
    if registry:
        log.info("tokens_loaded_from_yaml", count=len(registry), path=str(yaml_path))
        return registry

    registry = _load_env_tokens(settings)
    if registry:
        log.info("tokens_loaded_from_env", count=len(registry))
    return registry


def _get_registry() -> dict[str, TokenInfo]:
    global _token_registry
    if _token_registry is None:
        _token_registry = _build_token_registry(get_settings())
    return _token_registry


def resolve_token(authorization: str | None) -> TokenInfo | None:
    """Extract TokenInfo for a given Authorization header value.

    Returns None when no auth is configured (open access).
    Raises HTTPException on invalid/missing token.
    """
    registry = _get_registry()

    if not registry:
        return None

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid authorization format")

    token = authorization[7:]
    info = registry.get(token)
    if info is None:
        raise HTTPException(status_code=401, detail="Invalid token")

    return info


def resolve_business_id(
    token_info: TokenInfo | None,
    header_business_id: str,
) -> str:
    """Determine the effective business_id from token binding and header.

    Rules:
    - Token bound to a business → use bound business (ignore header)
    - Token not bound (admin) → use X-Business-Id header
    - No auth → use header
    """
    if token_info is None:
        return header_business_id

    if token_info.business_id is not None:
        if header_business_id != "default" and header_business_id != token_info.business_id:
            raise HTTPException(
                status_code=403,
                detail=f"Token is bound to business '{token_info.business_id}', "
                       f"cannot access '{header_business_id}'",
            )
        return token_info.business_id

    return header_business_id


def require_role(minimum: Role):
    """FastAPI dependency factory: require at least ``minimum`` role."""

    def _check(authorization: str | None = Header(default=None)) -> TokenInfo | None:
        info = resolve_token(authorization)
        if info is None:
            return None
        if info.role < minimum:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient permissions. Required: {minimum.name.lower()}, "
                       f"current: {info.role.name.lower()}",
            )
        return info

    return _check


def get_current_role(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    """Return info about the current token (for /auth/me endpoint)."""
    registry = _get_registry()

    if not registry:
        return {"role": "admin", "auth_enabled": False, "business_id": None}

    if not authorization or not authorization.startswith("Bearer "):
        return {"role": None, "auth_enabled": True, "business_id": None}

    token = authorization[7:]
    info = registry.get(token)
    if info is None:
        return {"role": None, "auth_enabled": True, "business_id": None}

    return {
        "role": info.role.name.lower(),
        "auth_enabled": True,
        "business_id": info.business_id,
    }
