"""Tests for wiki_find_implementing_modules MCP tool (G-A2)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.mcp_tools import WikiMCPHandler, WIKI_MCP_TOOLS_MANIFEST


class TestFindImplementingModulesManifest:
    def test_tool_in_manifest(self):
        names = [t["name"] for t in WIKI_MCP_TOOLS_MANIFEST]
        assert "wiki_find_implementing_modules" in names

    def test_manifest_schema(self):
        tool = next(t for t in WIKI_MCP_TOOLS_MANIFEST if t["name"] == "wiki_find_implementing_modules")
        assert "domain_name" in tool["inputSchema"]["properties"]
        assert "domain_name" in tool["inputSchema"]["required"]


@pytest.mark.asyncio
async def test_find_implementing_modules_store_not_configured():
    handler = WikiMCPHandler(store=None)
    result = await handler.handle_wiki_find_implementing_modules({"domain_name": "payments"})
    assert "error" in result
    assert result["error"]["code"] == "service_unavailable"


@pytest.mark.asyncio
async def test_find_implementing_modules_missing_domain():
    handler = WikiMCPHandler(store=MagicMock())
    result = await handler.handle_wiki_find_implementing_modules({"domain_name": ""})
    assert "error" in result
    assert result["error"]["code"] == "invalid_params"


@pytest.mark.asyncio
async def test_find_implementing_modules_success():
    mock_store = MagicMock()
    mock_result = MagicMock()
    mock_result.result_set = [
        ("Module:payments", "payments", "src/payments", "my-repo", "/payments/_overview"),
        ("Module:billing", "billing", "src/billing", "my-repo", "/billing/_overview"),
    ]

    with patch("store.wiki_store.WikiStore") as MockWikiStore:
        mock_ws = AsyncMock()
        mock_ws.find_modules_by_domain = AsyncMock(return_value=mock_result)
        MockWikiStore.return_value = mock_ws

        handler = WikiMCPHandler(store=mock_store)
        result = await handler.handle_wiki_find_implementing_modules({"domain_name": "payments"})

    assert result["domain_name"] == "payments"
    assert result["count"] == 2
    assert len(result["modules"]) == 2
    assert result["modules"][0]["name"] == "payments"
    assert result["modules"][1]["name"] == "billing"


@pytest.mark.asyncio
async def test_find_implementing_modules_no_results():
    mock_store = MagicMock()
    mock_result = MagicMock()
    mock_result.result_set = []

    with patch("store.wiki_store.WikiStore") as MockWikiStore:
        mock_ws = AsyncMock()
        mock_ws.find_modules_by_domain = AsyncMock(return_value=mock_result)
        MockWikiStore.return_value = mock_ws

        handler = WikiMCPHandler(store=mock_store)
        result = await handler.handle_wiki_find_implementing_modules({"domain_name": "nonexistent"})

    assert result["count"] == 0
    assert result["modules"] == []
