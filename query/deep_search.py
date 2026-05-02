"""Dashboard deep search — delegates to IterativeRAGEngine."""

from __future__ import annotations

import re
from typing import Any

from core.log import get_logger
from wiki.rag.engine import _is_arun_stream_callable

log = get_logger(__name__)

# File extensions for code path detection (backtick-wrapped or bare paths).
_CODE_FILE_EXT = (
    r"py|java|ts|tsx|js|jsx|go|rs|kt|kts|swift|m|dart|scala|rb|php|cs|cpp|cc|c|h|hpp|sql|md|yaml|yml|json|toml"
)
_CODE_PATH_BODY = rf"[\w./-]+\.(?:{_CODE_FILE_EXT})"
_BACKTICK_PATH_RE = re.compile(rf"`({_CODE_PATH_BODY})`", re.IGNORECASE)
_BARE_PATH_RE = re.compile(rf"(?<![`\w/])({_CODE_PATH_BODY})\b", re.IGNORECASE)
# Chains: Word (arrow Word)+ using Unicode arrow or ASCII arrows.
_FLOW_CHAIN_RE = re.compile(
    r"([\w]+(?:\s*(?:→|->|=>)\s*[\w]+)+)",
)
_FLOW_DESC_RE = re.compile(
    r"([A-Za-z][A-Za-z0-9]*(?:\s+[A-Za-z][A-Za-z0-9]*)*\s+flow)\b",
    re.IGNORECASE,
)


def _snippet(draft: str, start: int, end: int, radius: int = 100) -> str:
    lo = max(0, start - radius)
    hi = min(len(draft), end + radius)
    return draft[lo:hi].strip()


def _extract_code_locations(draft: str) -> list[dict[str, str]]:
    """Find file paths in draft via backticks or common source extensions."""
    if not draft:
        return []
    seen: set[str] = set()
    out: list[dict[str, str]] = []

    for m in _BACKTICK_PATH_RE.finditer(draft):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            out.append({"path": path, "context": _snippet(draft, m.start(), m.end())})

    for m in _BARE_PATH_RE.finditer(draft):
        path = m.group(1)
        if path not in seen:
            seen.add(path)
            out.append({"path": path, "context": _snippet(draft, m.start(), m.end())})

    return out


def _extract_business_flows(draft: str) -> list[dict[str, str]]:
    """Find arrow-style component chains; attach a short description when detectable."""
    if not draft.strip():
        return []

    flows: list[dict[str, str]] = []
    used_spans: list[tuple[int, int]] = []

    for m in _FLOW_CHAIN_RE.finditer(draft):
        flow_text = m.group(1).strip()
        if not re.search(r"(?:→|->|=>)", flow_text):
            continue
        start, end = m.span(1)

        overlap = any(
            not (end <= u0 or start >= u1) for (u0, u1) in used_spans
        )
        if overlap:
            continue
        used_spans.append((start, end))

        prefix = draft[max(0, start - 200) : start]
        desc_m = _FLOW_DESC_RE.search(prefix)
        description = desc_m.group(1).strip() if desc_m else ""

        if not description:
            colon_m = re.search(r"([^:\n]{1,120}):\s*$", prefix)
            if colon_m:
                description = colon_m.group(1).strip()

        flows.append({"flow": flow_text, "description": description})

    return flows


class DeepSearchEngine:
    """Deep search delegating to IterativeRAGEngine."""

    def __init__(self, rag_engine: Any) -> None:
        self._engine = rag_engine

    async def search(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        _include_code: bool = True,
        business_id: str = "",
        _model: str | None = None,
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
            log.error("deep_search_rag_failed", exc_info=True)
            return {"analysis": "", "search_trace": [], "business_flows": [], "code_locations": []}
        draft = state.get("current_draft", "") or ""
        return {
            "analysis": draft,
            "search_trace": self._build_trace(state.get("sse_events", [])),
            "business_flows": _extract_business_flows(draft),
            "code_locations": _extract_code_locations(draft),
        }

    async def search_stream(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        _include_code: bool = True,
        business_id: str = "",
        _model: str | None = None,
        tenant_id: str | None = None,
    ):
        from wiki.rag.protocol import RetrievalScope

        bid = business_id or (tenant_id or "")
        scope = RetrievalScope(
            scope_type="business" if bid else "global",
            business_id=bid or None,
        )
        yield {"type": "plan", "data": {"intent": query, "sub_queries": [query]}}

        draft = ""
        confidence = 0.0
        use_stream = _is_arun_stream_callable(self._engine)
        try:
            if use_stream:
                async for item in self._engine.arun_stream(
                    question=query,
                    scope=scope,
                    max_rounds=max_iterations,
                ):
                    t = item.get("type")
                    if t == "sse":
                        yield {"type": "progress", "data": item.get("data")}
                    elif t == "draft":
                        draft = str(item.get("content", ""))
                    elif t == "done":
                        confidence = float(item.get("confidence", 0.0))
            else:
                state = await self._engine.arun(
                    question=query,
                    scope=scope,
                    max_rounds=max_iterations,
                )
                for sse in state.get("sse_events", []):
                    yield {"type": "progress", "data": sse}
                draft = state.get("current_draft", "") or ""
                confidence = float(state.get("confidence", 0.0))
        except Exception:
            log.error("deep_search_stream_rag_failed", exc_info=True)
            yield {
                "type": "conclusion",
                "data": {
                    "analysis": "",
                    "sufficient": False,
                    "business_flows": [],
                    "code_locations": [],
                },
            }
            return

        yield {
            "type": "conclusion",
            "data": {
                "analysis": draft,
                "sufficient": confidence >= 0.5,
                "business_flows": _extract_business_flows(draft),
                "code_locations": _extract_code_locations(draft),
            },
        }

    @staticmethod
    def _build_trace(sse_events: list[dict]) -> list[dict]:
        return [{"stage": e.get("type", "unknown"), **e} for e in sse_events]
