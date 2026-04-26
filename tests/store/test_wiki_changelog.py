import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.mark.asyncio
async def test_persist_changelog_creates_node():
    """WikiChangeLog node should be created with required fields."""
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    from store.wiki_changelog import WikiChangeLogStore

    store = WikiChangeLogStore(mock_graph)
    await store.persist_changelog(
        repository="test-repo",
        trigger="git_push",
        pages_affected=["page1", "page2"],
        pages_regenerated=2,
        files_changed=["auth.py"],
    )

    mock_graph.execute_query.assert_called_once()
    call_args = mock_graph.execute_query.call_args
    assert "WikiChangeLog" in call_args[0][0]


@pytest.mark.asyncio
async def test_list_changelogs():
    mock_graph = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {"uid": "cl-1", "trigger": "git_push", "pages_affected": 2, "timestamp": 1234567890.0}
    ]
    mock_graph.execute_query = AsyncMock(return_value=mock_result)

    from store.wiki_changelog import WikiChangeLogStore

    store = WikiChangeLogStore(mock_graph)
    logs = await store.list_changelogs("test-repo", limit=10)
    assert len(logs) == 1
    assert logs[0]["trigger"] == "git_push"
