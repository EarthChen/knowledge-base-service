"""Redis Hash–backed wiki task storage with TTL and concurrency locks."""
from __future__ import annotations

import json
import uuid
from typing import Any

from log import get_logger

log = get_logger(__name__)

UNLOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
end
return 0
"""


class WikiTaskStore:
    """Persist wiki generation task state in Redis Hashes.

    Uses the FalkorDB instance's underlying Redis connection — zero extra deps.
    Keys expire after DEFAULT_TTL to bound memory usage.
    """

    KEY_PREFIX = "kb:wiki_tasks:"
    LOCK_PREFIX = "kb:wiki_gen_lock:"
    DEFAULT_TTL = 1800  # 30 minutes
    LOCK_TTL = 3600  # 1 hour

    _JSON_FIELDS = frozenset({"partial_errors", "skipped_repos", "result"})

    def __init__(self, redis_conn: Any) -> None:
        self._redis = redis_conn

    def _key(self, task_id: str) -> str:
        return f"{self.KEY_PREFIX}{task_id}"

    def _lock_key(self, business_id: str) -> str:
        return f"{self.LOCK_PREFIX}{business_id}"

    async def put_task(self, task_id: str, record: dict[str, Any]) -> None:
        mapping: dict[str, str] = {}
        for k, v in record.items():
            if k in self._JSON_FIELDS and not isinstance(v, str):
                mapping[k] = json.dumps(v, default=str)
            else:
                mapping[k] = str(v) if v is not None else ""
        key = self._key(task_id)
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, self.DEFAULT_TTL)

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        raw = await self._redis.hgetall(self._key(task_id))
        if not raw:
            return None
        out: dict[str, Any] = {}
        for k, v in raw.items():
            key_str = k.decode() if isinstance(k, bytes) else str(k)
            val_str = v.decode() if isinstance(v, bytes) else str(v)
            if key_str in self._JSON_FIELDS:
                try:
                    out[key_str] = json.loads(val_str)
                except (json.JSONDecodeError, TypeError):
                    out[key_str] = val_str
            else:
                out[key_str] = val_str
        return out

    async def update_status(self, task_id: str, status: str, **extra: Any) -> None:
        mapping: dict[str, str] = {"status": status}
        for k, v in extra.items():
            if k in self._JSON_FIELDS and not isinstance(v, str):
                mapping[k] = json.dumps(v, default=str)
            else:
                mapping[k] = str(v) if v is not None else ""
        key = self._key(task_id)
        await self._redis.hset(key, mapping=mapping)
        await self._redis.expire(key, self.DEFAULT_TTL)

    async def try_lock(self, business_id: str) -> str | None:
        """Try to acquire lock. Returns lock token if successful, None otherwise."""
        token = str(uuid.uuid4())
        ok = await self._redis.set(
            self._lock_key(business_id), token, nx=True, ex=self.LOCK_TTL,
        )
        return token if ok else None

    async def unlock(self, business_id: str, lock_token: str) -> bool:
        """Release lock only if we still hold it. Returns True if released."""
        result = await self._redis.eval(
            UNLOCK_SCRIPT, 1, self._lock_key(business_id), lock_token,
        )
        return bool(result)

    async def force_release_lock(self, business_id: str) -> None:
        """Delete lock without token check (cancel, orphan recovery, admin)."""
        await self._redis.delete(self._lock_key(business_id))

    async def list_active(self) -> list[dict[str, Any]]:
        cursor = 0
        active: list[dict[str, Any]] = []
        while True:
            cursor, keys = await self._redis.scan(
                cursor, match=f"{self.KEY_PREFIX}*", count=50,
            )
            for key in keys:
                raw = await self._redis.hgetall(key)
                if not raw:
                    continue
                status_raw = raw.get(b"status", raw.get("status", b""))
                status = status_raw.decode() if isinstance(status_raw, bytes) else str(status_raw)
                if status not in ("completed", "failed"):
                    task = await self.get_task(
                        (key.decode() if isinstance(key, bytes) else str(key))
                        .removeprefix(self.KEY_PREFIX)
                    )
                    if task:
                        active.append(task)
            if cursor == 0:
                break
        return active
