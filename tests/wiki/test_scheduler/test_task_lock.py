"""Unit tests for wiki.scheduler.task_lock.TaskLock."""

from __future__ import annotations

import asyncio

import pytest

from wiki.scheduler.task_lock import TaskLock


@pytest.mark.asyncio
async def test_acquire_and_release() -> None:
    lock = TaskLock(timeout_seconds=600)
    assert await lock.acquire("repo-a") is True
    assert lock.is_locked("repo-a") is True
    await lock.release("repo-a")
    assert lock.is_locked("repo-a") is False
    assert await lock.acquire("repo-a") is True
    await lock.release("repo-a")


@pytest.mark.asyncio
async def test_same_repository_cannot_double_acquire() -> None:
    lock = TaskLock(timeout_seconds=600)
    assert await lock.acquire("repo-x") is True
    assert await lock.acquire("repo-x") is False
    await lock.release("repo-x")
    assert await lock.acquire("repo-x") is True
    await lock.release("repo-x")


@pytest.mark.asyncio
async def test_different_repositories_can_acquire_concurrently() -> None:
    lock = TaskLock(timeout_seconds=600)
    assert await lock.acquire("r1") is True
    assert await lock.acquire("r2") is True
    assert lock.is_locked("r1") is True
    assert lock.is_locked("r2") is True
    await lock.release("r1")
    await lock.release("r2")


@pytest.mark.asyncio
async def test_timeout_auto_releases_lock() -> None:
    lock = TaskLock(timeout_seconds=1)
    assert await lock.acquire("slow-repo") is True
    assert lock.is_locked("slow-repo") is True
    await asyncio.sleep(1.15)
    assert lock.is_locked("slow-repo") is False
    assert await lock.acquire("slow-repo") is True
    await lock.release("slow-repo")


@pytest.mark.asyncio
async def test_is_locked_tracks_lifecycle() -> None:
    lock = TaskLock(timeout_seconds=600)
    assert lock.is_locked("z") is False
    assert await lock.acquire("z") is True
    assert lock.is_locked("z") is True
    await lock.release("z")
    assert lock.is_locked("z") is False


@pytest.mark.asyncio
async def test_manual_release_cancels_timeout() -> None:
    lock = TaskLock(timeout_seconds=2)
    assert await lock.acquire("manual") is True
    await lock.release("manual")
    assert lock.is_locked("manual") is False
    await asyncio.sleep(2.1)
    assert lock.is_locked("manual") is False
    assert await lock.acquire("manual") is True
    await lock.release("manual")
