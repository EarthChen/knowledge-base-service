"""ISO8601 timestamp parsing for webhook payloads."""

from __future__ import annotations

from datetime import UTC, datetime


def parse_iso_timestamp(value: str) -> datetime | None:
    try:
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt
    except (OSError, TypeError, ValueError):
        return None
