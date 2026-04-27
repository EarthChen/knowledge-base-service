"""Redis ZSET–backed wiki page editing presence (heartbeats, TTL via score pruning)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

from log import get_logger

log = get_logger(__name__)


class WikiEditingStore:
    """Track who is editing a wiki page using FalkorDB's Redis connection.

    Keys: ``kb:editing:{page_uid}`` — sorted set, member = stable editor id (hex),
    score = last heartbeat unix time. Stale scores are removed on each write and on read.
    Key TTL is refreshed to 5 minutes on each mutation.
    """

    KEY_PREFIX = "kb:editing:"
    TTL_SEC = 300  # 5 minutes
    STALE_SEC = 300
    FINGERPRINT_LEN = 16

    def __init__(self, redis_conn: Any) -> None:
        self._redis = redis_conn

    def _key(self, page_uid: str) -> str:
        return f"{self.KEY_PREFIX}{page_uid}"

    @staticmethod
    def editor_fingerprint(*, token: str | None, client_host: str) -> str:
        """Stable per-session id for a browser/API client (no PII in API responses: use short prefix)."""
        if token and token.strip():
            raw = token.strip()
        else:
            raw = f"anon:{client_host or '0.0.0.0'}"
        h = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return h[: WikiEditingStore.FINGERPRINT_LEN]

    def token_prefix(self, editor_id: str) -> str:
        """Short label for UIs: first 8 hex chars of fingerprint."""
        return editor_id[:8] if len(editor_id) >= 8 else editor_id

    async def heartbeat(self, page_uid: str, editor_id: str) -> None:
        key = self._key(page_uid)
        now = time.time()
        await self._redis.zadd(key, {editor_id: now})
        await self._redis.zremrangebyscore(key, 0, now - self.STALE_SEC)
        await self._redis.expire(key, self.TTL_SEC)
        log.debug("wiki_editing_heartbeat", page_uid=page_uid, editor_id_prefix=self.token_prefix(editor_id))

    async def stop(self, page_uid: str, editor_id: str) -> None:
        key = self._key(page_uid)
        await self._redis.zrem(key, editor_id)
        size = await self._redis.zcard(key)
        if size == 0:
            await self._redis.delete(key)
        else:
            await self._redis.expire(key, self.TTL_SEC)
        log.debug("wiki_editing_stop", page_uid=page_uid, editor_id_prefix=self.token_prefix(editor_id))

    async def list_editors(
        self,
        page_uid: str,
        *,
        self_editor_id: str | None,
    ) -> dict[str, Any]:
        key = self._key(page_uid)
        now = time.time()
        await self._redis.zremrangebyscore(key, 0, now - self.STALE_SEC)
        raw_rows = await self._redis.zrange(key, 0, -1, withscores=True)
        editors: list[dict[str, Any]] = []
        for item in raw_rows:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                member, score = item[0], item[1]
            else:
                continue
            eid = member.decode() if isinstance(member, bytes) else str(member)
            last_ts = float(score)
            display = f"{self.token_prefix(eid)}:{int(last_ts)}"
            editors.append(
                {
                    "editor_id": eid,
                    "token_prefix": self.token_prefix(eid),
                    "last_heartbeat": int(last_ts),
                    "label": display,
                },
            )

        other_active = False
        if self_editor_id is not None:
            other_active = any(e["editor_id"] != self_editor_id for e in editors)
        else:
            other_active = len(editors) > 0

        return {
            "editors": editors,
            "other_active": other_active,
        }
