import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def wiki_service():
    from wiki.service import WikiService
    svc = WikiService.__new__(WikiService)
    svc._graph = MagicMock()
    svc._graph.query = AsyncMock()
    svc._wiki_store = MagicMock()
    svc._settings = MagicMock()
    return svc


@pytest.mark.asyncio
async def test_set_review_status_approved(wiki_service):
    wiki_service._graph.query.return_value = MagicMock(result_set=[[True]])
    result = await wiki_service.set_page_review_status("page-1", "approved", "")
    assert result["status"] == "approved"
    assert result["page_uid"] == "page-1"


@pytest.mark.asyncio
async def test_set_review_status_needs_revision(wiki_service):
    wiki_service._graph.query.return_value = MagicMock(result_set=[[True]])
    result = await wiki_service.set_page_review_status("page-2", "needs_revision", "Fix section 3")
    assert result["status"] == "needs_revision"
    assert result["notes"] == "Fix section 3"


@pytest.mark.asyncio
async def test_set_review_status_invalid(wiki_service):
    with pytest.raises(ValueError, match="Invalid review status"):
        await wiki_service.set_page_review_status("page-1", "invalid_status", "")


@pytest.mark.asyncio
async def test_set_review_status_page_not_found(wiki_service):
    wiki_service._graph.query.return_value = MagicMock(result_set=[])
    with pytest.raises(ValueError, match="not found"):
        await wiki_service.set_page_review_status("nonexistent", "approved", "")
