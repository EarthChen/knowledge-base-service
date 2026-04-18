"""Per-repository async task locks with automatic timeout release."""

from __future__ import annotations

import asyncio
import threading
import time

# Bind at import time so tests that patch asyncio.sleep do not shorten lock timeouts.
_asyncio_sleep = asyncio.sleep


class TaskLock:
    """Per-repository async lock with timeout auto-release."""

    def __init__(self, timeout_seconds: int = 600) -> None:
        self._timeout_seconds = timeout_seconds
        self._sync = threading.Lock()
        self._locks: dict[str, asyncio.Lock] = {}
        self._timeout_tasks: dict[str, asyncio.Task[None]] = {}
        self._deadlines: dict[str, float] = {}

    def _get_async_lock(self, repository: str) -> asyncio.Lock:
        with self._sync:
            if repository not in self._locks:
                self._locks[repository] = asyncio.Lock()
            return self._locks[repository]

    async def acquire(self, repository: str) -> bool:
        """Try to acquire lock for repository. Returns False if already locked."""
        lock = self._get_async_lock(repository)
        if lock.locked():
            return False
        try:
            # Non-blocking try: asyncio.Lock has no try_acquire; use a tiny window.
            await asyncio.wait_for(lock.acquire(), timeout=0.001)
        except TimeoutError:
            return False
        self._schedule_timeout_release(repository)
        return True

    def _schedule_timeout_release(self, repository: str) -> None:
        deadline = time.monotonic() + float(self._timeout_seconds)
        with self._sync:
            self._deadlines[repository] = deadline
            old = self._timeout_tasks.pop(repository, None)
        if old is not None and not old.done():
            old.cancel()

        task = asyncio.create_task(self._timeout_runner(repository))
        with self._sync:
            self._timeout_tasks[repository] = task

    async def _timeout_runner(self, repository: str) -> None:
        try:
            with self._sync:
                deadline = self._deadlines.get(repository)
            if deadline is None:
                return
            remaining = deadline - time.monotonic()
            if remaining > 0:
                await _asyncio_sleep(remaining)
        except asyncio.CancelledError:
            return
        await self._release_lock_only(repository)

    async def _release_lock_only(self, repository: str) -> None:
        with self._sync:
            self._deadlines.pop(repository, None)
            self._timeout_tasks.pop(repository, None)
            lock = self._locks.get(repository)
        if lock is not None and lock.locked():
            lock.release()

    async def release(self, repository: str) -> None:
        """Release lock for repository."""
        with self._sync:
            self._deadlines.pop(repository, None)
            timeout_task = self._timeout_tasks.pop(repository, None)
            lock = self._locks.get(repository)
        if timeout_task is not None and not timeout_task.done():
            timeout_task.cancel()
            try:
                await timeout_task
            except asyncio.CancelledError:
                pass
        if lock is not None and lock.locked():
            lock.release()

    def is_locked(self, repository: str) -> bool:
        """Check if repository is locked."""
        with self._sync:
            lock = self._locks.get(repository)
        return lock is not None and lock.locked()
