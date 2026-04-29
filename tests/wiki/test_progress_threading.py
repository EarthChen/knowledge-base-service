import pytest


@pytest.mark.asyncio
async def test_generate_receives_progress_callback():
    """Progress callback receives sub-phase data from compose phase."""
    progress_events = []

    async def capture_progress(info):
        progress_events.append(info)

    event = {
        "phase": "generating_pages",
        "completed_repos": 0,
        "total_repos": 2,
        "current_repo": "repo-a",
        "repo_progress": {
            "subphase": "leaf_compose",
            "pages_composed": 50,
            "total_pages": 100,
        },
    }
    await capture_progress(event)

    assert len(progress_events) == 1
    assert progress_events[0]["repo_progress"]["subphase"] == "leaf_compose"
    assert progress_events[0]["repo_progress"]["pages_composed"] == 50
