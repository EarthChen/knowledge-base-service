import asyncio
import pytest
from unittest.mock import AsyncMock

from wiki.lint import LintReport
from wiki.lint_scheduler import LintScheduler


@pytest.mark.asyncio
async def test_scheduler_runs_lint() -> None:
    report = LintReport(
        issues=[],
        stats={"total": 0, "errors": 0, "warnings": 0, "info": 0},
        checked_at="",
        scope="all",
    )
    mock_lint_factory = AsyncMock()
    mock_lint_service = AsyncMock()
    mock_lint_service.lint = AsyncMock(return_value=report)
    mock_lint_factory.return_value = mock_lint_service

    scheduler = LintScheduler(
        mock_lint_factory,
        repositories=["acme/app"],
        interval_seconds=0.05,
    )
    scheduler.start()
    await asyncio.sleep(0.15)
    await scheduler.stop()

    assert mock_lint_factory.call_count >= 1
    mock_lint_service.lint.assert_called()
    assert mock_lint_service.lint.call_args[0][0] == "acme/app"


def test_scheduler_default_interval() -> None:
    scheduler = LintScheduler(AsyncMock(), repositories=[])
    assert scheduler._interval_seconds == 21600  # 6 hours
