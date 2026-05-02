"""Unit tests for TaskSupervisor."""
from __future__ import annotations

import asyncio

import pytest

from core.task_supervisor import TaskSupervisor


@pytest.fixture
def supervisor() -> TaskSupervisor:
    return TaskSupervisor()


@pytest.mark.asyncio
async def test_spawn_runs_task(supervisor: TaskSupervisor) -> None:
    result: list[int] = []

    async def work() -> None:
        result.append(42)

    tid = supervisor.spawn(lambda: work(), name="test:basic")
    assert tid
    assert len(supervisor.active_tasks) == 1
    await asyncio.sleep(0.05)
    assert result == [42]
    assert len(supervisor.active_tasks) == 0
    assert supervisor.stats["total_spawned"] == 1
    assert supervisor.stats["total_completed"] == 1


@pytest.mark.asyncio
async def test_cancel_task(supervisor: TaskSupervisor) -> None:
    async def forever() -> None:
        await asyncio.sleep(999)

    tid = supervisor.spawn(lambda: forever(), name="test:cancel")
    assert supervisor.cancel(tid) is True
    await asyncio.sleep(0.05)
    assert len(supervisor.active_tasks) == 0
    assert supervisor.cancel("nonexistent") is False


@pytest.mark.asyncio
async def test_shutdown_cancels_remaining(supervisor: TaskSupervisor) -> None:
    async def forever() -> None:
        await asyncio.sleep(999)

    supervisor.spawn(lambda: forever(), name="test:sd1")
    supervisor.spawn(lambda: forever(), name="test:sd2")
    assert len(supervisor.active_tasks) == 2
    await supervisor.shutdown(timeout=0.5)
    assert len(supervisor.active_tasks) == 0


@pytest.mark.asyncio
async def test_shutdown_rejects_new_spawn(supervisor: TaskSupervisor) -> None:
    await supervisor.shutdown(timeout=0.1)
    with pytest.raises(RuntimeError, match="shutting down"):
        supervisor.spawn(lambda: asyncio.sleep(0), name="test:rejected")


@pytest.mark.asyncio
async def test_retry_on_failure(supervisor: TaskSupervisor) -> None:
    attempts: list[int] = []

    async def flaky() -> None:
        attempts.append(1)
        if len(attempts) < 3:
            raise ValueError("not yet")

    supervisor.spawn(lambda: flaky(), name="test:retry", max_retries=3, retry_delay=0.01)
    await asyncio.sleep(0.5)
    assert len(attempts) == 3
    assert supervisor.stats["total_retried"] >= 2
    assert supervisor.stats["total_completed"] == 1


@pytest.mark.asyncio
async def test_retry_exhausted_calls_on_failure(supervisor: TaskSupervisor) -> None:
    failures: list[str] = []

    async def always_fail() -> None:
        raise ValueError("boom")

    def on_fail(task_id: str, exc: BaseException) -> None:
        failures.append(task_id)

    supervisor.spawn(
        lambda: always_fail(),
        name="test:exhaust",
        max_retries=1,
        retry_delay=0.01,
        on_failure=on_fail,
    )
    await asyncio.sleep(0.3)
    assert len(failures) == 1
    assert supervisor.stats["total_failed"] == 1


@pytest.mark.asyncio
async def test_timeout_cancels_task(supervisor: TaskSupervisor) -> None:
    async def slow() -> None:
        await asyncio.sleep(999)

    supervisor.spawn(lambda: slow(), name="test:timeout", timeout=0.05)
    await asyncio.sleep(0.5)
    assert len(supervisor.active_tasks) == 0
    assert supervisor.stats["total_failed"] == 1


@pytest.mark.asyncio
async def test_active_tasks_snapshot(supervisor: TaskSupervisor) -> None:
    async def hold() -> None:
        await asyncio.sleep(1)

    supervisor.spawn(lambda: hold(), name="test:snap1")
    supervisor.spawn(lambda: hold(), name="test:snap2")
    snap = supervisor.active_tasks
    assert len(snap) == 2
    for info in snap.values():
        assert "name" in info
        assert "created_at" in info
        assert "retry_count" in info
    await supervisor.shutdown(timeout=0.5)


@pytest.mark.asyncio
async def test_concurrent_tasks(supervisor: TaskSupervisor) -> None:
    results: list[int] = []

    async def job(n: int) -> None:
        await asyncio.sleep(0.01)
        results.append(n)

    for i in range(5):
        supervisor.spawn(lambda i=i: job(i), name=f"test:concurrent-{i}")
    await asyncio.sleep(0.3)
    assert sorted(results) == [0, 1, 2, 3, 4]
    assert supervisor.stats["total_completed"] == 5
