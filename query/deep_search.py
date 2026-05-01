"""Dashboard deep search — delegates to IterativeRAGEngine."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class DeepSearchEngine:
    """Deep search delegating to IterativeRAGEngine."""

    def __init__(self, rag_engine: Any) -> None:
        self._engine = rag_engine

    async def search(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        business_id: str = "",
        model: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        from wiki.rag.protocol import RetrievalScope

        bid = business_id or (tenant_id or "")
        scope = RetrievalScope(
            scope_type="business" if bid else "global",
            business_id=bid or None,
        )
        try:
            state = await self._engine.arun(
                question=query,
                scope=scope,
                max_rounds=max_iterations,
            )
        except Exception:
            logger.error("deep_search_rag_failed", exc_info=True)
            return {"analysis": "", "search_trace": [], "business_flows": [], "code_locations": []}
        return {
            "analysis": state.get("current_draft", ""),
            "search_trace": self._build_trace(state.get("sse_events", [])),
            "business_flows": [],
            "code_locations": [],
        }

    async def search_stream(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        business_id: str = "",
        model: str | None = None,
        tenant_id: str | None = None,
    ):
        from wiki.rag.protocol import RetrievalScope

        bid = business_id or (tenant_id or "")
        scope = RetrievalScope(
            scope_type="business" if bid else "global",
            business_id=bid or None,
        )
        yield {"type": "plan", "data": {"intent": query, "sub_queries": [query]}}

        try:
            state = await self._engine.arun(
                question=query,
                scope=scope,
                max_rounds=max_iterations,
            )
        except Exception:
            logger.error("deep_search_stream_rag_failed", exc_info=True)
            yield {"type": "conclusion", "data": {"analysis": "", "sufficient": False, "business_flows": [], "code_locations": []}}
            return

        for sse in state.get("sse_events", []):
            yield {"type": "progress", "data": sse}

        yield {
            "type": "conclusion",
            "data": {
                "analysis": state.get("current_draft", ""),
                "sufficient": True,
                "business_flows": [],
                "code_locations": [],
            },
        }

    @staticmethod
    def _build_trace(sse_events: list[dict]) -> list[dict]:
        return [{"stage": e.get("type", "unknown"), **e} for e in sse_events]
