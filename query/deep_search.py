"""Dashboard deep search — delegates to IterativeRAGEngine."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import json_repair

logger = logging.getLogger(__name__)


def _extract_first_brace_json_slice(candidate: str) -> str | None:
    """Return the first balanced `{...}` substring, or None."""
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : i + 1]
    return None


def _legacy_parse_json_object_brace_only(candidate: str) -> dict[str, Any] | None:
    """Original behavior: brace-counting plus stdlib json.loads only (no repair)."""
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(candidate[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _parse_json_object_from_llm(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from LLM text (fenced code or raw)."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    candidate = code_block.group(1).strip() if code_block else text.strip()

    json_slice = _extract_first_brace_json_slice(candidate)
    if json_slice is not None:
        try:
            obj = json.loads(json_slice)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

        try:
            obj = json_repair.loads(json_slice)
            if isinstance(obj, dict):
                logger.warning(
                    "Used json_repair.loads() because LLM JSON was malformed "
                    "(stdlib json.loads failed)"
                )
                return obj
        except Exception:
            pass

        return _legacy_parse_json_object_brace_only(candidate)

    return None


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
        state = await self._engine.arun(
            question=query,
            scope=scope,
            max_rounds=max_iterations,
        )
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

        state = await self._engine.arun(
            question=query,
            scope=scope,
            max_rounds=max_iterations,
        )

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
