"""Finalize node for wiki pipeline."""
from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)


async def finalize_node(state: dict[str, Any]) -> dict[str, Any]:
    log.info(
        "pipeline_complete",
        total_pages=len(state.get("pages", [])),
        error_count=len(state.get("errors", [])),
    )
    return {}
