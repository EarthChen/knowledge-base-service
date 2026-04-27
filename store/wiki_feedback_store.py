"""Wiki page feedback persistence."""
from __future__ import annotations

import time
import uuid
from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class WikiFeedbackStore:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    async def persist_feedback(
        self,
        page_uid: str,
        rating: str,
        comment: str = "",
        user_id: str = "anonymous",
        *,
        business_id: str = "default",
        severity: str = "normal",
    ) -> str:
        uid = f"WikiFeedback:{uuid.uuid4().hex[:12]}"
        cypher = (
            "CREATE (f:WikiFeedback {"
            "  uid: $uid, page_uid: $page_uid, business_id: $business_id, rating: $rating,"
            "  comment: $comment, user_id: $user_id, timestamp: $ts, severity: $severity"
            "})"
        )
        await self._graph.execute_query(
            cypher,
            {
                "uid": uid,
                "page_uid": page_uid,
                "business_id": business_id,
                "rating": rating,
                "comment": comment,
                "user_id": user_id,
                "ts": time.time(),
                "severity": severity,
            },
        )
        return uid

    async def get_feedback_summary(self, page_uid: str, business_id: str = "default") -> dict[str, Any]:
        cypher = (
            "MATCH (f:WikiFeedback {page_uid: $page_uid, business_id: $business_id}) "
            "RETURN "
            "  sum(CASE WHEN f.rating = 'up' THEN 1 ELSE 0 END) AS up,"
            "  sum(CASE WHEN f.rating = 'down' THEN 1 ELSE 0 END) AS down"
        )
        result = await self._graph.execute_query(
            cypher, {"page_uid": page_uid, "business_id": business_id},
        )
        rows = getattr(result, "data", []) or []
        if rows and isinstance(rows[0], dict):
            r0 = rows[0]
            up = r0.get("up") or 0
            down = r0.get("down") or 0
            return {
                "up": int(up) if up is not None else 0,
                "down": int(down) if down is not None else 0,
                "total": (int(up) if up is not None else 0) + (int(down) if down is not None else 0),
            }
        return {"up": 0, "down": 0, "total": 0}
