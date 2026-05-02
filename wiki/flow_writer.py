"""Business flow inference and persistence."""

from __future__ import annotations

import json
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


class BusinessFlowWriter:
    """Infers and persists business flows from code entry points."""

    def __init__(
        self,
        store: Any | None,
        wiki_cfg: Any,
        flow_inferencer: Any | None = None,
    ) -> None:
        self._store = store
        self._wiki_cfg = wiki_cfg
        self._flow_inferencer = flow_inferencer

    async def generate_business_flows(self, repository: str) -> int:
        """Infer BusinessFlow nodes from entry-point call chains."""
        if not self._flow_inferencer:
            return 0
        if not self._flow_inferencer._business_flow_enabled:
            return 0

        entry_points = await self._flow_inferencer.find_entry_points()
        created = 0
        for ep in entry_points:
            chain = await self.build_call_chain(ep)
            if not chain:
                continue
            flow = await self._flow_inferencer.infer_from_chain(chain)
            if flow:
                await self.persist_flow(flow, repository)
                created += 1
        return created

    async def build_call_chain(self, entry_point: dict[str, Any]) -> list[dict[str, str]]:
        """Build a call chain starting from an entry point by traversing CALLS edges."""
        if self._store is None:
            return []
        uid = entry_point.get("uid", "")
        if not uid:
            return []
        q = (
            "MATCH path = (start:Function {uid: $uid})-[:CALLS*1..5]->(callee:Function) "
            "RETURN callee.uid AS uid, callee.name AS name, "
            "callee.business_summary AS business_summary, callee.file AS file "
            "ORDER BY length(path)"
        )
        result = await self._store.execute_query(q, {"uid": uid})
        raw = getattr(result, "raw", None)
        if isinstance(raw, list):
            rows = raw
        else:
            rs = getattr(result, "result_set", None)
            rows = list(rs) if isinstance(rs, (list, tuple)) else []
        chain: list[dict[str, str]] = [
            {
                "name": str(entry_point.get("name", "") or ""),
                "business_summary": str(entry_point.get("business_summary", "") or ""),
                "file": str(entry_point.get("file", "") or ""),
            }
        ]
        seen: set[str] = {uid}
        for row in rows:
            row_uid = row[0]
            if row_uid in seen:
                continue
            seen.add(str(row_uid))
            chain.append(
                {
                    "name": str(row[1] or ""),
                    "business_summary": str(row[2] or ""),
                    "file": str(row[3] or ""),
                }
            )
        return chain

    async def persist_flow(self, flow: dict[str, Any], repository: str) -> None:
        """Persist a BusinessFlow node to the graph."""
        if self._store is None:
            return
        flow_name = flow.get("flow_name", "unnamed_flow")
        uid = f"BusinessFlow:{repository}:{flow_name}"
        q = (
            "MERGE (bf:BusinessFlow {uid: $uid}) "
            "SET bf.name = $name, bf.description = $desc, "
            "bf.category = $cat, bf.repository = $repo, "
            "bf.steps = $steps"
        )
        await self._store.execute_query(
            q,
            {
                "uid": uid,
                "name": flow_name,
                "desc": flow.get("description", ""),
                "cat": flow.get("category", ""),
                "repo": repository,
                "steps": json.dumps(flow.get("steps", []), ensure_ascii=False),
            },
        )
