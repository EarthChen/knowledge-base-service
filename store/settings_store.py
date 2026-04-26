"""SQLite-backed settings persistence layer."""

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


class SettingsStore:
    def __init__(self, db_path: str = "data/kb_settings.db") -> None:
        self._db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'system',
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_settings_category
                ON settings(category)
            """)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    async def get_all(self) -> dict[str, dict[str, str]]:
        """Return all settings grouped by category: {category: {key: value}}."""

        def _query():
            with self._connect() as conn:
                rows = conn.execute("SELECT key, value, category FROM settings").fetchall()
            result: dict[str, dict[str, str]] = {}
            for row in rows:
                cat = row["category"]
                if cat not in result:
                    result[cat] = {}
                result[cat][row["key"]] = row["value"]
            return result

        return await asyncio.to_thread(_query)

    async def get_by_category(self, category: str) -> dict[str, str]:
        """Return settings for a single category."""

        def _query():
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT key, value FROM settings WHERE category = ?",
                    (category,),
                ).fetchall()
            return {row["key"]: row["value"] for row in rows}

        return await asyncio.to_thread(_query)

    async def get(self, key: str) -> str | None:
        """Return a single setting value or None."""

        def _query():
            with self._connect() as conn:
                row = conn.execute(
                    "SELECT value FROM settings WHERE key = ?",
                    (key,),
                ).fetchone()
            return row["value"] if row else None

        return await asyncio.to_thread(_query)

    async def upsert(self, key: str, value: str, category: str) -> None:
        """Insert or update a single setting."""
        now = datetime.now(UTC).isoformat()

        def _write():
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO settings (key, value, category, updated_at) "
                    "VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "category=excluded.category, updated_at=excluded.updated_at",
                    (key, value, category, now),
                )

        await asyncio.to_thread(_write)

    async def upsert_batch(self, items: list[dict[str, str]]) -> None:
        """Batch upsert settings. Each dict has 'key', 'value', 'category'."""
        now = datetime.now(UTC).isoformat()

        def _write():
            with self._connect() as conn:
                conn.executemany(
                    "INSERT INTO settings (key, value, category, updated_at) "
                    "VALUES (:key, :value, :category, :updated_at) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "category=excluded.category, updated_at=excluded.updated_at",
                    [{**item, "updated_at": now} for item in items],
                )

        await asyncio.to_thread(_write)

    async def delete(self, key: str) -> bool:
        """Delete a setting. Returns True if deleted."""

        def _write():
            with self._connect() as conn:
                cursor = conn.execute("DELETE FROM settings WHERE key = ?", (key,))
                return cursor.rowcount > 0

        return await asyncio.to_thread(_write)

    def get_all_sync(self) -> dict[str, dict[str, str]]:
        """Synchronous version for startup config loading."""
        with self._connect() as conn:
            rows = conn.execute("SELECT key, value, category FROM settings").fetchall()
        result: dict[str, dict[str, str]] = {}
        for row in rows:
            cat = row["category"]
            if cat not in result:
                result[cat] = {}
            result[cat][row["key"]] = row["value"]
        return result
