import pytest
from unittest.mock import AsyncMock, MagicMock

from store.wiki_feedback_store import WikiFeedbackStore


@pytest.mark.asyncio
async def test_persist_feedback() -> None:
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    store = WikiFeedbackStore(mock_graph)
    uid = await store.persist_feedback(
        page_uid="WikiPage:test",
        rating="up",
        comment="Very helpful!",
        user_id="user-1",
        business_id="biz-42",
    )
    assert uid.startswith("WikiFeedback:")
    mock_graph.execute_query.assert_called_once()
    call_params = mock_graph.execute_query.call_args[0][1]
    assert call_params.get("business_id") == "biz-42"


@pytest.mark.asyncio
async def test_get_feedback_summary() -> None:
    mock_graph = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [{"up": 5, "down": 1}]
    mock_graph.execute_query = AsyncMock(return_value=mock_result)

    store = WikiFeedbackStore(mock_graph)
    summary = await store.get_feedback_summary("WikiPage:test", business_id="acme")
    assert "up" in summary or "total" in summary
    call_params = mock_graph.execute_query.call_args[0][1]
    assert call_params.get("page_uid") == "WikiPage:test"
    assert call_params.get("business_id") == "acme"
