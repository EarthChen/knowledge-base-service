from __future__ import annotations

from typing import Any


def sse_thinking_start(*, round_no: int, max_rounds: int) -> dict[str, Any]:
    return {"type": "thinking_start", "round": round_no, "max_rounds": max_rounds}


def rag_sse_append(state: dict[str, Any], typ: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Append SSE event; mirrors design §2.7 types."""
    events: list[dict[str, Any]] = list(state.get("sse_events") or [])
    body: dict[str, Any] = {"type": typ, **payload}
    events.append(body)
    return events
