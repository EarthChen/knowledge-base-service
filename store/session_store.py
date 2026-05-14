"""SQLite-backed unified session store with TTL and LRU eviction."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

import aiosqlite


@dataclass
class SessionTurn:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class Session:
    session_id: str
    session_type: str
    turns: list[SessionTurn] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    last_active: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class SqliteSessionStore:
    def __init__(
        self,
        db_path: str = "data/sessions.db",
        max_sessions: int = 200,
        max_turns: int = 30,
        ttl_seconds: int = 1800,
    ) -> None:
        self._db_path = db_path
        self._max_sessions = max_sessions
        self._max_turns = max_turns
        self._ttl = ttl_seconds
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                session_type TEXT NOT NULL,
                turns_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                last_active REAL NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def get(self, session_id: str) -> Session | None:
        if not self._db:
            return None
        cursor = await self._db.execute(
            "SELECT session_id, session_type, turns_json, metadata_json, last_active, created_at "
            "FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        if time.time() - row[4] > self._ttl:
            await self.delete(session_id)
            return None
        turns_raw = json.loads(row[2])
        turns = [SessionTurn(**t) for t in turns_raw]
        return Session(
            session_id=row[0],
            session_type=row[1],
            turns=turns,
            metadata=json.loads(row[3]),
            last_active=row[4],
            created_at=row[5],
        )

    async def save(self, session: Session) -> None:
        assert self._db is not None
        session.last_active = time.time()
        if len(session.turns) > self._max_turns:
            session.turns = session.turns[-self._max_turns :]
        turns_json = json.dumps(
            [{"role": t.role, "content": t.content, "timestamp": t.timestamp} for t in session.turns],
            ensure_ascii=False,
        )
        metadata_json = json.dumps(session.metadata, ensure_ascii=False, default=str)
        await self._db.execute(
            """
            INSERT INTO sessions (session_id, session_type, turns_json, metadata_json, last_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                turns_json=excluded.turns_json,
                metadata_json=excluded.metadata_json,
                last_active=excluded.last_active
            """,
            (
                session.session_id,
                session.session_type,
                turns_json,
                metadata_json,
                session.last_active,
                session.created_at,
            ),
        )
        await self._db.commit()
        await self._evict_lru()

    async def delete(self, session_id: str) -> None:
        if not self._db:
            return
        await self._db.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
        await self._db.commit()

    async def list_by_type(self, session_type: str) -> list[Session]:
        if not self._db:
            return []
        now = time.time()
        cursor = await self._db.execute(
            "SELECT session_id, session_type, turns_json, metadata_json, last_active, created_at "
            "FROM sessions WHERE session_type = ? AND (? - last_active) < ?",
            (session_type, now, self._ttl),
        )
        rows = await cursor.fetchall()
        results: list[Session] = []
        for row in rows:
            turns = [SessionTurn(**t) for t in json.loads(row[2])]
            results.append(
                Session(
                    session_id=row[0],
                    session_type=row[1],
                    turns=turns,
                    metadata=json.loads(row[3]),
                    last_active=row[4],
                    created_at=row[5],
                )
            )
        return results

    async def cleanup_expired(self) -> int:
        if not self._db:
            return 0
        cutoff = time.time() - self._ttl
        cursor = await self._db.execute(
            "DELETE FROM sessions WHERE last_active < ?",
            (cutoff,),
        )
        await self._db.commit()
        return cursor.rowcount

    async def _evict_lru(self) -> None:
        assert self._db is not None
        cursor = await self._db.execute("SELECT COUNT(*) FROM sessions")
        (count,) = await cursor.fetchone()
        assert count is not None
        if count > self._max_sessions:
            excess = count - self._max_sessions
            await self._db.execute(
                "DELETE FROM sessions WHERE session_id IN "
                "(SELECT session_id FROM sessions ORDER BY last_active ASC LIMIT ?)",
                (excess,),
            )
            await self._db.commit()
