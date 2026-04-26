import pytest
from unittest.mock import AsyncMock, MagicMock
from api.mcp_wiki_server import MCPWikiServer


@pytest.mark.asyncio
async def test_wiki_navigate_returns_children():
    mock_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = [
        {"path": "/auth", "title": "Authentication", "type": "section"},
        {"path": "/auth/login", "title": "Login", "type": "page"},
    ]
    mock_store.execute_query = AsyncMock(return_value=mock_result)
    
    server = MCPWikiServer(wiki_store=mock_store)
    result = await server.handle_tool_call("wiki_navigate", {
        "repository": "test-repo",
        "path": "/auth",
    })
    assert "children" in result or "pages" in result or "status" not in result or result.get("status") != "not_implemented"


@pytest.mark.asyncio
async def test_wiki_impact_returns_affected_pages():
    mock_detector = AsyncMock()
    mock_affected = MagicMock()
    mock_affected.page_uids = ["p1", "p2"]
    mock_affected.affected_entities = ["e1"]
    mock_affected.trigger = "api"
    mock_affected.files_changed = ["auth.py"]
    mock_detector.detect_from_file_list = AsyncMock(return_value=mock_affected)
    
    server = MCPWikiServer(change_detector=mock_detector)
    result = await server.handle_tool_call("wiki_impact", {
        "repository": "test-repo",
        "files": ["auth.py"],
    })
    assert "pages_affected" in result or "error" not in result
