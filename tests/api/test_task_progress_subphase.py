# tests/api/test_task_progress_subphase.py
import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_progress_handler_merges_repo_progress():
    """_progress handler extracts repo_progress fields into task store extra."""
    task_store = AsyncMock()
    task_store.update_status = AsyncMock()

    task_id = "biz-wiki-test123"

    async def _progress(info):
        tr = int(info.get("total_repos", 0) or 0)
        cr = int(info.get("completed_repos", 0) or 0)
        denom = max(tr, 1)
        pct = int(cr / denom * 100)
        extra = {
            "completed_repos": str(cr),
            "total_repos": str(tr),
            "current_repo": str(info.get("current_repo", "")),
            "progress_pct": str(pct),
        }
        phase = info.get("phase")
        if phase:
            extra["phase"] = str(phase)
        repo_progress = info.get("repo_progress")
        if repo_progress:
            extra["subphase"] = str(repo_progress.get("subphase", ""))
            extra["pages_composed"] = str(repo_progress.get("pages_composed", 0))
            extra["total_pages"] = str(repo_progress.get("total_pages", 0))
        await task_store.update_status(task_id, "running", **extra)

    await _progress({
        "completed_repos": 1,
        "total_repos": 3,
        "current_repo": "repo-a",
        "phase": "generating_pages",
        "repo_progress": {
            "subphase": "leaf_compose",
            "pages_composed": 200,
            "total_pages": 500,
        },
    })

    task_store.update_status.assert_awaited_once()
    call_args = task_store.update_status.call_args
    kwargs = call_args.kwargs if call_args.kwargs else {}
    if not kwargs:
        # In case positional + keyword args are mixed
        _, kwargs = call_args
    assert kwargs["subphase"] == "leaf_compose"
    assert kwargs["pages_composed"] == "200"
    assert kwargs["total_pages"] == "500"
    assert kwargs["current_repo"] == "repo-a"


@pytest.mark.asyncio
async def test_progress_handler_without_repo_progress():
    """Without repo_progress, no subphase fields are added."""
    task_store = AsyncMock()
    task_store.update_status = AsyncMock()

    task_id = "biz-wiki-test456"

    async def _progress(info):
        tr = int(info.get("total_repos", 0) or 0)
        cr = int(info.get("completed_repos", 0) or 0)
        denom = max(tr, 1)
        pct = int(cr / denom * 100)
        extra = {
            "completed_repos": str(cr),
            "total_repos": str(tr),
            "current_repo": str(info.get("current_repo", "")),
            "progress_pct": str(pct),
        }
        phase = info.get("phase")
        if phase:
            extra["phase"] = str(phase)
        repo_progress = info.get("repo_progress")
        if repo_progress:
            extra["subphase"] = str(repo_progress.get("subphase", ""))
            extra["pages_composed"] = str(repo_progress.get("pages_composed", 0))
            extra["total_pages"] = str(repo_progress.get("total_pages", 0))
        await task_store.update_status(task_id, "running", **extra)

    await _progress({
        "completed_repos": 1,
        "total_repos": 3,
        "current_repo": "repo-a",
        "phase": "generating_pages",
    })

    call_args = task_store.update_status.call_args
    kwargs = call_args.kwargs if call_args.kwargs else {}
    if not kwargs:
        _, kwargs = call_args
    assert "subphase" not in kwargs
