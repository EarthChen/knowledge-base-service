import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_session_store():
    store = AsyncMock()
    store.get = AsyncMock(return_value=None)
    store.save = AsyncMock()
    store.delete = AsyncMock()
    return store


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete_with_tools = AsyncMock(return_value={"tool_calls": None})
    llm.generate = AsyncMock(return_value="# Edited content")
    return llm


@pytest.mark.asyncio
async def test_create_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    session_id = await svc.create_session("page-1", "# Original")
    assert session_id is not None
    assert len(session_id) > 0
    mock_session_store.save.assert_called_once()


@pytest.mark.asyncio
async def test_get_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    from store.session_store import Session
    mock_session_store.get.return_value = Session(
        session_id="s1", session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Old", "current_content": "# Old"},
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    session = await svc.get_session("s1")
    assert session is not None
    assert session.metadata["page_uid"] == "p1"


@pytest.mark.asyncio
async def test_delete_session(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    await svc.delete_session("s1")
    mock_session_store.delete.assert_called_once_with("s1")


@pytest.mark.asyncio
async def test_apply_edit(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    from store.session_store import Session
    mock_session_store.get.return_value = Session(
        session_id="s1", session_type="edit",
        metadata={"page_uid": "p1", "original_content": "# Old", "current_content": "# New"},
    )
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    result = await svc.apply_edit("s1")
    assert result["page_uid"] == "p1"
    assert result["content"] == "# New"


@pytest.mark.asyncio
async def test_apply_edit_not_found(mock_session_store, mock_llm):
    from wiki.edit_service import WikiEditService
    svc = WikiEditService(session_store=mock_session_store, llm=mock_llm)
    with pytest.raises(ValueError, match="not found"):
        await svc.apply_edit("nonexistent")
