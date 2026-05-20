"""Guards for ad-hoc read-only Cypher execution (raw_cypher)."""

from __future__ import annotations

import re

from query.nl_cypher import _MUTATING_KEYWORDS

RAW_CYPHER_DEFAULT_LIMIT = 1000
RAW_CYPHER_TIMEOUT_SEC = 30.0

_LIMIT_RE = re.compile(r"\bLIMIT\b", re.IGNORECASE)


class RawCypherValidationError(ValueError):
    """Raised when raw Cypher fails read-only or shape checks."""


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
