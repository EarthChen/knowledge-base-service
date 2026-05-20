"""Guards for ad-hoc read-only Cypher execution (raw_cypher)."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from query.nl_cypher import _MUTATING_KEYWORDS

if TYPE_CHECKING:
    from core.auth import TokenInfo

RAW_CYPHER_DEFAULT_LIMIT = 1000
RAW_CYPHER_TIMEOUT_SEC = 30.0

_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class RawCypherValidationError(ValueError):
    """Raised when raw Cypher fails read-only or shape checks."""


_RAW_CYPHER_ADMIN_MSG = "raw_cypher requires admin role"


def check_raw_cypher_admin(token_info: TokenInfo | None) -> str | None:
    """Return an error message when the caller may not run raw_cypher, else None."""
    from core.auth import Role, get_auth_mode
    from core.config import get_settings

    if token_info is not None and token_info.role < Role.ADMIN:
        return _RAW_CYPHER_ADMIN_MSG
    if get_auth_mode() == "token" or get_settings().require_auth:
        if token_info is None or token_info.role < Role.ADMIN:
            return _RAW_CYPHER_ADMIN_MSG
    return None


def validate_raw_cypher_read_only(cypher: str) -> None:
    """Reject mutating Cypher (CREATE, DELETE, SET, etc.)."""
    if _MUTATING_KEYWORDS.search(cypher):
        raise RawCypherValidationError("raw_cypher only supports read-only queries")


def ensure_raw_cypher_limit(
    cypher: str,
    *,
    default_limit: int = RAW_CYPHER_DEFAULT_LIMIT,
) -> str:
    """Append LIMIT when the query omits one (caps unbounded scans)."""
    text = cypher.strip().rstrip(";").strip()
    if not text:
        return text
    if _LIMIT_RE.search(text):
        return text
    return f"{text} LIMIT {default_limit}"
