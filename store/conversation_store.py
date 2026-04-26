"""SQLite-backed conversation store with TTL and LRU eviction."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

import aiosqlite


@dataclass
class ConversationTurn:
    role: str
    content: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConversationHistory:
    conversation_id: str
    turns: list[ConversationTurn] = field(default_factory=list)
    last_active: float = field(default_factory=time.time)
    repository: str = ""
    scope: str | None = None
    business_id: str = "default"


class SqliteConversationStore:
    def __init__(
        self,
        db_path: str = "data/conversations.db",
        max_conversations: int = 200,
        max_turns: int = 10,
        ttl_seconds: int = 1800,
    ) -> None:
        self._db_path = db_path
        self._max_conversations = max_conversations
        self._max_turns = max_turns
        self._ttl_seconds = ttl_seconds
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.execute(
            """CREATE TABLE IF NOT EXISTS conversations (
                conversation_id TEXT PRIMARY KEY,
                business_id TEXT NOT NULL DEFAULT 'default',
                repository TEXT NOT NULL DEFAULT '',
                scope TEXT,
                turns_json TEXT NOT NULL DEFAULT '[]',
                last_active REAL NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    async def get(self, conversation_id: str) -> ConversationHistory | None:
        if not self._db:
            return None
        now = time.time()
        cursor = await self._db.execute(
            "SELECT conversation_id, business_id, repository, scope, turns_json, last_active "
            "FROM conversations WHERE conversation_id = ?",
            (conversation_id,),
        )
        row = await cursor.fetchone()
        if row is None:
            return None

        last_active = row[5]
        if now - last_active > self._ttl_seconds:
            await self._db.execute(
                "DELETE FROM conversations WHERE conversation_id = ?",
                (conversation_id,),
            )
            await self._db.commit()
            return None

        await self._db.execute(
            "UPDATE conversations SET last_active = ? WHERE conversation_id = ?",
            (now, conversation_id),
        )
        await self._db.commit()

        turns_raw = json.loads(row[4]) if row[4] else []
        turns = [
            ConversationTurn(role=t["role"], content=t["content"], timestamp=t.get("timestamp", 0))
            for t in turns_raw
        ]

        return ConversationHistory(
            conversation_id=row[0],
            business_id=row[1],
            repository=row[2],
            scope=row[3],
            turns=turns,
            last_active=now,
        )

    async def save(self, history: ConversationHistory) -> None:
        if not self._db:
            return
        history.last_active = time.time()
        if len(history.turns) > self._max_turns:
            history.turns = history.turns[-self._max_turns :]

        turns_json = json.dumps(
            [{"role": t.role, "content": t.content, "timestamp": t.timestamp} for t in history.turns],
            ensure_ascii=False,
        )
        await self._db.execute(
            """INSERT INTO conversations (conversation_id, business_id, repository, scope, turns_json, last_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(conversation_id) DO UPDATE SET
                business_id = excluded.business_id,
                repository = excluded.repository,
                scope = excluded.scope,
                turns_json = excluded.turns_json,
                last_active = excluded.last_active""",
            (
                history.conversation_id,
                history.business_id,
                history.repository,
                history.scope,
                turns_json,
                history.last_active,
                history.last_active,
            ),
        )
        await self._db.commit()
        await self._evict_lru()

    async def create(self, repository: str, scope: str | None = None, business_id: str = "default") -> ConversationHistory:
        cid = str(uuid.uuid4())
        h = ConversationHistory(
            conversation_id=cid,
            repository=repository,
            scope=scope,
            business_id=business_id,
        )
        await self.save(h)
        return h

    async def _evict_lru(self) -> None:
        if not self._db:
            return
        cursor = await self._db.execute("SELECT COUNT(*) FROM conversations")
        row = await cursor.fetchone()
        count = row[0] if row else 0
        if count <= self._max_conversations:
            return
        excess = count - self._max_conversations
        await self._db.execute(
            "DELETE FROM conversations WHERE conversation_id IN "
            "(SELECT conversation_id FROM conversations ORDER BY last_active ASC LIMIT ?)",
            (excess,),
        )
        await self._db.commit()
