"""Feedback-driven wiki regeneration with threshold, critical path, and cooldown."""
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from core.log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class FeedbackDrivenRegeneration:
    def __init__(
        self,
        graph: _GraphPort,
        wiki_config: Any,
        enqueue_regenerate: Callable[[str, str, float], Awaitable[None]],
    ) -> None:
        self._graph = graph
        self._cfg = wiki_config
        self._enqueue = enqueue_regenerate

    def _cooldown_ok(self, last_ts: float | None) -> bool:
        h = int(getattr(self._cfg, "feedback_regen_cooldown_hours", 24))
        if last_ts is None:
            return True
        return (time.time() - last_ts) >= h * 3600

    async def on_feedback(
        self,
        page_uid: str,
        business_id: str,
        rating: str,
        *,
        severity: str = "normal",
    ) -> dict[str, Any]:
        if not getattr(self._cfg, "feedback_regen_enabled", True):
            return {"action": "noop", "reason": "disabled"}
        if rating != "down":
            return {"action": "recorded", "regenerate": False}

        last = await self._last_regen_ts(page_uid, business_id)
        if not self._cooldown_ok(last):
            return {"action": "skipped", "reason": "cooldown"}

        if severity == "critical" and getattr(
            self._cfg, "feedback_regen_critical_immediate", True
        ):
            mult = float(getattr(self._cfg, "feedback_regen_token_multiplier", 1.5))
            await self._enqueue(page_uid, "high", mult)
            await self._mark_regen(page_uid, business_id)
            return {"action": "queued", "priority": "high", "token_multiplier": mult}

        n_down = await self._count_negative(page_uid, business_id)
        thr = int(getattr(self._cfg, "feedback_regen_threshold", 3))
        if n_down >= thr:
            mult = float(getattr(self._cfg, "feedback_regen_batch_token_multiplier", 1.2))
            await self._enqueue(page_uid, "normal", mult)
            await self._mark_regen(page_uid, business_id)
            return {"action": "queued", "priority": "normal", "token_multiplier": mult}
        return {"action": "recorded", "regenerate": False}

    async def _count_negative(self, page_uid: str, business_id: str) -> int:
        q = (
            "MATCH (f:WikiFeedback {page_uid: $p, business_id: $b, rating: 'down'}) "
            "RETURN count(f) AS c"
        )
        r = await self._graph.execute_query(q, {"p": page_uid, "b": business_id})
        rows = getattr(r, "data", []) or []
        if rows and isinstance(rows[0], dict):
            return int(rows[0].get("c") or 0)
        return 0

    async def _last_regen_ts(self, page_uid: str, business_id: str) -> float | None:
        q = (
            "MATCH (wp:WikiPage) WHERE wp.uid = $uid "
            "RETURN coalesce(wp.last_feedback_regen_at, null) AS ts"
        )
        r = await self._graph.execute_query(q, {"uid": page_uid})
        rows = getattr(r, "data", []) or []
        if not rows or not isinstance(rows[0], dict):
            return None
        ts = rows[0].get("ts")
        return float(ts) if ts is not None else None

    async def _mark_regen(self, page_uid: str, business_id: str) -> None:
        q = (
            "MATCH (wp:WikiPage) WHERE wp.uid = $uid "
            "SET wp.last_feedback_regen_at = $ts"
        )
        await self._graph.execute_query(q, {"uid": page_uid, "ts": time.time()})
