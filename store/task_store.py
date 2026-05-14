"""SQLite-backed unified task store with WAL, TTL cleanup, and resource locks."""

from __future__ import annotations

import json
import secrets
import time
from dataclasses import dataclass

import aiosqlite


@dataclass
class TaskRecord:
    task_id: str
    task_type: str
    business_id: str | None = None
    status: str = "pending"
    progress_json: str = "{}"


# Stable order for SQL NOT IN / IN parameter binding
_TERMINAL_STATUSES: tuple[str, ...] = ("cancelled", "completed", "failed")


class SqliteTaskStore:
    """Persist tasks and short-lived mutex locks in SQLite (WAL)."""

    def __init__(self, db_path: str, ttl_seconds: int = 86400) -> None:
        self._db_path = db_path
        self._ttl_seconds = ttl_seconds
        self._db: aiosqlite.Connection | None = None

    async def initialize(self) -> None:
        self._db = await aiosqlite.connect(self._db_path)
        await self._db.execute("PRAGMA journal_mode=WAL")
        await self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY NOT NULL,
                task_type TEXT NOT NULL,
                business_id TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                progress_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS task_locks (
                resource_id TEXT PRIMARY KEY NOT NULL,
                token TEXT NOT NULL,
                expires_at REAL NOT NULL
            );
            """
        )
        await self._db.commit()

    async def close(self) -> None:
        if self._db:
            await self._db.close()
            self._db = None

    def _require_db(self) -> aiosqlite.Connection:
        if not self._db:
            msg = "Store is not initialized; call initialize() first"
            raise RuntimeError(msg)
        return self._db

    async def put(self, rec: TaskRecord) -> None:
        db = self._require_db()
        now = time.time()
        cur = await db.execute(
            "SELECT created_at FROM tasks WHERE task_id = ?", (rec.task_id,)
        )
        row = await cur.fetchone()
        created_at = row[0] if row else now
        progress = rec.progress_json if rec.progress_json else "{}"
        await db.execute(
            """INSERT OR REPLACE INTO tasks (
                task_id, task_type, business_id, status,
                progress_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                rec.task_id,
                rec.task_type,
                rec.business_id,
                rec.status,
                progress,
                created_at,
                now,
            ),
        )
        await db.commit()

    async def get(self, task_id: str) -> TaskRecord | None:
        db = self._require_db()
        cur = await db.execute(
            "SELECT task_id, task_type, business_id, status, progress_json "
            "FROM tasks WHERE task_id = ?",
            (task_id,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row[0],
            task_type=row[1],
            business_id=row[2],
            status=row[3],
            progress_json=row[4],
        )

    async def update_status(self, task_id: str, status: str, **fields: object) -> None:
        db = self._require_db()
        now = time.time()
        assignments = ["status = ?", "updated_at = ?"]
        values: list[object] = [status, now]
        allowed = {"task_type", "business_id", "progress_json"}
        for key in sorted(fields.keys()):
            if key not in allowed:
                msg = f"Unsupported field for update_status: {key}"
                raise ValueError(msg)
            assignments.append(f"{key} = ?")
            values.append(fields[key])
        values.append(task_id)
        sql = f"UPDATE tasks SET {', '.join(assignments)} WHERE task_id = ?"
        await db.execute(sql, values)
        await db.commit()

    async def update_progress(self, task_id: str, progress: dict) -> None:
        db = self._require_db()
        now = time.time()
        payload = json.dumps(progress)
        await db.execute(
            "UPDATE tasks SET progress_json = ?, updated_at = ? WHERE task_id = ?",
            (payload, now, task_id),
        )
        await db.commit()

    async def list_active(self, task_type: str | None = None) -> list[TaskRecord]:
        db = self._require_db()
        terminal = ",".join("?" * len(_TERMINAL_STATUSES))
        base = (
            "SELECT task_id, task_type, business_id, status, progress_json "
            f"FROM tasks WHERE status NOT IN ({terminal})"
        )
        params: list = list(_TERMINAL_STATUSES)
        if task_type is not None:
            base += " AND task_type = ?"
            params.append(task_type)
        cur = await db.execute(base, params)
        rows = await cur.fetchall()
        return [
            TaskRecord(
                task_id=r[0],
                task_type=r[1],
                business_id=r[2],
                status=r[3],
                progress_json=r[4],
            )
            for r in rows
        ]

    async def _purge_expired_locks(self, db: aiosqlite.Connection) -> None:
        await db.execute(
            "DELETE FROM task_locks WHERE expires_at < ?", (time.time(),)
        )

    async def try_lock(self, resource_id: str, ttl: int) -> str | None:
        db = self._require_db()
        await self._purge_expired_locks(db)
        token = secrets.token_urlsafe(16)
        expires_at = time.time() + ttl
        try:
            await db.execute(
                "INSERT INTO task_locks (resource_id, token, expires_at) VALUES (?, ?, ?)",
                (resource_id, token, expires_at),
            )
        except aiosqlite.IntegrityError:
            await db.commit()
            return None
        await db.commit()
        return token

    async def unlock(self, resource_id: str, token: str) -> bool:
        db = self._require_db()
        cur = await db.execute(
            "DELETE FROM task_locks WHERE resource_id = ? AND token = ?",
            (resource_id, token),
        )
        await db.commit()
        return cur.rowcount > 0

    async def cleanup_expired(self) -> int:
        """Delete terminal tasks older than ttl_seconds based on updated_at."""
        db = self._require_db()
        cutoff = time.time() - self._ttl_seconds
        placeholders = ",".join("?" * len(_TERMINAL_STATUSES))
        cur = await db.execute(
            f"DELETE FROM tasks WHERE status IN ({placeholders}) AND updated_at < ?",
            (*_TERMINAL_STATUSES, cutoff),
        )
        await db.commit()
        return cur.rowcount

