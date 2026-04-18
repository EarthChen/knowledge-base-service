"""Unit tests for wiki.scheduler.wiki_scheduler.WikiScheduler."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from wiki.scheduler.task_lock import TaskLock
from wiki.scheduler.wiki_scheduler import ScheduleConfig, WikiScheduler

# Preserve real asyncio.sleep before tests patch wiki_scheduler.asyncio.sleep (same module object).
_real_asyncio_sleep = asyncio.sleep


@pytest.fixture
def task_lock() -> TaskLock:
    return TaskLock(timeout_seconds=600)


@pytest.mark.asyncio
async def test_start_stop(task_lock: TaskLock) -> None:
    regen = AsyncMock()
    cfg = ScheduleConfig(schedule_type="none")
    scheduler = WikiScheduler(cfg, task_lock, regen)

    await scheduler.start()
    await _real_asyncio_sleep(0.05)
    await scheduler.stop()

    regen.assert_not_called()


@pytest.mark.asyncio
async def test_interval_triggers_regenerate_fn(task_lock: TaskLock) -> None:
    regen = AsyncMock()
    cfg = ScheduleConfig(
        schedule_type="interval",
        interval_hours=1,
        enabled_repositories=["repo-a"],
    )
    scheduler = WikiScheduler(cfg, task_lock, regen)

    sleep_calls: list[float] = []

    async def fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)
        await _real_asyncio_sleep(0)

    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        await _real_asyncio_sleep(0.15)
        await scheduler.stop()

    regen.assert_awaited()
    assert regen.await_args_list[0].args == ("repo-a",)
    assert sleep_calls and sleep_calls[0] == 3600.0


@pytest.mark.asyncio
async def test_skip_when_task_lock_held(task_lock: TaskLock) -> None:
    assert await task_lock.acquire("busy-repo") is True
    regen = AsyncMock()
    cfg = ScheduleConfig(
        schedule_type="interval",
        interval_hours=1,
        enabled_repositories=["busy-repo"],
    )
    scheduler = WikiScheduler(cfg, task_lock, regen)

    async def fake_sleep(delay: float) -> None:
        await _real_asyncio_sleep(0)

    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        await _real_asyncio_sleep(0.15)
        await scheduler.stop()

    regen.assert_not_called()
    await task_lock.release("busy-repo")


@pytest.mark.asyncio
async def test_get_status_reflects_schedule_and_results(task_lock: TaskLock) -> None:
    regen = AsyncMock()
    cfg = ScheduleConfig(
        schedule_type="interval",
        interval_hours=2,
        enabled_repositories=["r1", "r2"],
    )
    scheduler = WikiScheduler(cfg, task_lock, regen)

    async def fake_sleep(delay: float) -> None:
        await _real_asyncio_sleep(0)

    before = datetime.now(tz=UTC)
    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        for _ in range(500):
            if regen.await_count >= 2:
                break
            await _real_asyncio_sleep(0.01)
        await scheduler.stop()
    after = datetime.now(tz=UTC)

    statuses = {s.repository: s for s in scheduler.get_status()}
    assert set(statuses) == {"r1", "r2"}
    for key in ("r1", "r2"):
        st = statuses[key]
        assert st.schedule_type == "interval"
        assert st.interval_hours == 2
        assert st.last_result == "success"
        assert st.last_run is not None
        assert before <= st.last_run <= after + timedelta(seconds=2)
        assert st.next_run is not None
        assert st.last_run <= st.next_run


@pytest.mark.asyncio
async def test_schedule_type_none_does_not_run(task_lock: TaskLock) -> None:
    regen = AsyncMock()
    cfg = ScheduleConfig(
        schedule_type="none",
        enabled_repositories=["x"],
    )
    scheduler = WikiScheduler(cfg, task_lock, regen)

    async def fake_sleep(delay: float) -> None:
        await _real_asyncio_sleep(0)

    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        await _real_asyncio_sleep(0.15)
        await scheduler.stop()

    regen.assert_not_called()
    statuses = scheduler.get_status()
    assert len(statuses) == 1
    assert statuses[0].schedule_type == "none"
    assert statuses[0].last_result == "pending"


@pytest.mark.asyncio
async def test_update_config_dynamic(task_lock: TaskLock) -> None:
    regen = AsyncMock()
    cfg = ScheduleConfig(schedule_type="none", enabled_repositories=["a"])
    scheduler = WikiScheduler(cfg, task_lock, regen)

    slept: list[float] = []

    async def fake_sleep(delay: float) -> None:
        slept.append(delay)
        await _real_asyncio_sleep(0)

    with patch("wiki.scheduler.wiki_scheduler.asyncio.sleep", side_effect=fake_sleep):
        await scheduler.start()
        await _real_asyncio_sleep(0.05)
        scheduler.update_config(
            ScheduleConfig(
                schedule_type="interval",
                interval_hours=1,
                enabled_repositories=["b"],
            )
        )
        await _real_asyncio_sleep(0.2)
        await scheduler.stop()

    names = [c.args[0] for c in regen.await_args_list]
    assert "b" in names
    st = {s.repository: s for s in scheduler.get_status()}
    assert "b" in st
    assert st["b"].schedule_type == "interval"
