"""Finalize node for wiki pipeline."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)


async def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    timings = state.get("stage_timings", {})
    total_ms = sum(timings.values())
    log.info(
        "pipeline_complete",
        total_pages=len(state.get("pages", [])),
        total_elapsed_ms=total_ms,
        llm_call_count=state.get("llm_call_count", 0),
        error_count=len(state.get("errors", [])),
    )
    return {}
