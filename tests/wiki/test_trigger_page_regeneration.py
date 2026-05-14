import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def wiki_service():
    from wiki.service import WikiService
    svc = WikiService.__new__(WikiService)
    svc._store = None
    svc._graph = MagicMock()
    svc._graph.execute_query = AsyncMock()
    svc._wiki_store = MagicMock()
    svc._wiki_store.update_wiki_page_content = AsyncMock()
    svc._settings = MagicMock()
    svc._llm = AsyncMock()
    svc._task_supervisor = None
    return svc


@pytest.mark.asyncio
async def test_trigger_regeneration_returns_task_id(wiki_service):
    wiki_service._graph.execute_query.return_value = MagicMock(
        data=[
            {
                "domain": "domain1",
                "repository": "repo1",
                "title": "topic1",
                "uid": "page-uid-1",
            },
        ]
    )
    result = await wiki_service.trigger_page_regeneration("page-uid-1", "fix section 3")
    assert "task_id" in result
    assert result["page_uid"] == "page-uid-1"
    assert result["status"] == "accepted"


@pytest.mark.asyncio
async def test_trigger_regeneration_page_not_found(wiki_service):
    wiki_service._graph.execute_query.return_value = MagicMock(data=[])
    with pytest.raises(ValueError, match="not found"):
        await wiki_service.trigger_page_regeneration("nonexistent", "")
