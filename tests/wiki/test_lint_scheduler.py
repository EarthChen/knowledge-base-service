import asyncio
import pytest
from unittest.mock import AsyncMock

from wiki.lint_scheduler import LintScheduler


@pytest.mark.asyncio
async def test_scheduler_runs_lint() -> None:
    mock_lint_factory = AsyncMock()
    mock_lint_service = AsyncMock()
    mock_lint_service.run_full_lint = AsyncMock(return_value={"issues": 0})
    mock_lint_factory.return_value = mock_lint_service

    scheduler = LintScheduler(lint_service_factory=mock_lint_factory, interval_seconds=0.05)
    scheduler.start()
    await asyncio.sleep(0.15)
    await scheduler.stop()

    assert mock_lint_factory.call_count >= 1


def test_scheduler_default_interval() -> None:
    scheduler = LintScheduler(lint_service_factory=AsyncMock())
    assert scheduler._interval_seconds == 21600  # 6 hours
