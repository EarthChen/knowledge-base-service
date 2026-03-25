"""Business manager — CRUD operations for business metadata stored in Redis.

Each business maps to an independent FalkorDB graph (``kb_{business_id}``).
Business metadata (name, description, created_at) is persisted as Redis hashes
on the same connection used by FalkorDB.
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from falkordb import FalkorDB

from log import get_logger

log = get_logger(__name__)

_BUSINESS_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")
_REDIS_PREFIX = "kb:businesses"
_GRAPH_PREFIX = "kb_"


def _meta_key(business_id: str) -> str:
    return f"{_REDIS_PREFIX}:{business_id}"


def graph_name_for(business_id: str) -> str:
    """Derive the FalkorDB graph name for a business."""
    return f"{_GRAPH_PREFIX}{business_id}"


class BusinessManager:
    """Manages business metadata via Redis hashes on the FalkorDB connection."""

    def __init__(self, db: FalkorDB) -> None:
        self._conn = db.connection

    def create_business(self, business_id: str, name: str, description: str = "") -> dict[str, Any]:
        if not _BUSINESS_ID_RE.match(business_id):
            raise ValueError(
                f"Invalid business_id '{business_id}': must match [a-z0-9][a-z0-9_-]{{0,62}}"
            )

        key = _meta_key(business_id)
        if self._conn.exists(key):
            raise ValueError(f"Business '{business_id}' already exists")

        meta = {
            "id": business_id,
            "name": name,
            "description": description,
            "created_at": time.time(),
        }
        self._conn.hset(key, mapping={k: json.dumps(v) if not isinstance(v, str) else v for k, v in meta.items()})
        log.info("business_created", business_id=business_id, name=name)
        return meta

    def list_businesses(self) -> list[dict[str, Any]]:
        pattern = f"{_REDIS_PREFIX}:*"
        keys = list(self._conn.scan_iter(match=pattern, count=200))
        results: list[dict[str, Any]] = []
        for key in keys:
            raw = self._conn.hgetall(key)
            if raw:
                meta = self._deserialize(raw)
                results.append(meta)
        results.sort(key=lambda x: x.get("created_at", 0))
        return results

    def get_business(self, business_id: str) -> dict[str, Any] | None:
        raw = self._conn.hgetall(_meta_key(business_id))
        if not raw:
            return None
        return self._deserialize(raw)

    def delete_business(self, business_id: str) -> bool:
        if business_id == "default":
            raise ValueError("Cannot delete the default business")
        key = _meta_key(business_id)
        deleted = self._conn.delete(key)
        if deleted:
            log.info("business_deleted", business_id=business_id)
        return bool(deleted)

    def ensure_default(self) -> None:
        """Ensure the 'default' business exists."""
        if not self._conn.exists(_meta_key("default")):
            self.create_business("default", "Default", "Auto-created default business")

    @staticmethod
    def _deserialize(raw: dict[bytes | str, bytes | str]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for k, v in raw.items():
            key_str = k.decode() if isinstance(k, bytes) else k
            val_str = v.decode() if isinstance(v, bytes) else v
            try:
                result[key_str] = json.loads(val_str)
            except (json.JSONDecodeError, TypeError):
                result[key_str] = val_str
        return result
