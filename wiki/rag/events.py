from __future__ import annotations

from typing import Any


def sse_thinking_start(*, round_no: int, max_rounds: int) -> dict[str, Any]:
    return {"type": "thinking_start", "round": round_no, "max_rounds": max_rounds}


def sse_rag_planning(*, round_no: int, sub_queries: list[str]) -> dict[str, Any]:
    """SSE payload shape for iterative RAG plan/decomposition step."""
    return {"type": "planning", "round": round_no, "sub_queries": sub_queries}


def sse_rag_evaluating(*, round_no: int, score: float, suggestions: list[str]) -> dict[str, Any]:
    """SSE payload shape for iterative RAG independent evaluation step."""
    return {"type": "evaluating", "round": round_no, "score": score, "suggestions": suggestions}


def rag_sse_append(state: dict[str, Any], typ: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Append SSE event; mirrors design §2.7 types."""
    events: list[dict[str, Any]] = list(state.get("sse_events") or [])
    body: dict[str, Any] = {"type": typ, **payload}
    events.append(body)
    return events
