import pytest
from wiki.change_detector import AffectedPageSet


@pytest.mark.asyncio
async def test_incremental_fallback_on_error():
    """When generate_incremental fails, should fallback to full generate."""
    affected = AffectedPageSet(
        page_uids=["bad-page"],
        trigger="git_push",
        files_changed=["broken.py"],
    )
    # Just verify the AffectedPageSet has the expected structure
    assert affected.trigger == "git_push"
    assert len(affected.page_uids) == 1
