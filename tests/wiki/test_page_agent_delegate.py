import pytest
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_delegate_submodule_creates_sub_agent():
    """_tool_delegate_submodule should create a sub WikiPageAgent and call generate."""
    from wiki.page_agent import WikiPageAgent

    mock_llm = AsyncMock()
    mock_graph = AsyncMock()

    agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph, repo_path="/tmp/repo")
    agent._delegation_depth = 0
    agent._delegation_count = 0

    with patch.object(WikiPageAgent, "generate", new_callable=AsyncMock) as mock_generate:
        mock_generate.return_value = "# SubModule\n\nGenerated content for submodule delegation result."
        result = await agent._tool_delegate_submodule({
            "entity_names": ["SubAuth", "SubToken"],
            "focus": "authentication flow",
        })

    assert result.get("delegated") is True
    assert "content" in result
    assert len(result["content"]) > 50


@pytest.mark.asyncio
async def test_delegate_depth_limit_enforced():
    """Should return error when delegation depth exceeds limit."""
    from wiki.page_agent import WikiPageAgent

    agent = WikiPageAgent(llm=AsyncMock(), graph_store=AsyncMock())
    agent._delegation_depth = 2

    result = await agent._tool_delegate_submodule({"entity_names": ["A"], "focus": ""})

    assert "error" in result
    assert "depth" in result.get("error", "")


@pytest.mark.asyncio
async def test_delegate_count_limit_enforced():
    """Should return error when delegation count exceeds limit."""
    from wiki.page_agent import WikiPageAgent

    agent = WikiPageAgent(llm=AsyncMock(), graph_store=AsyncMock())
    agent._delegation_depth = 0
    agent._delegation_count = 3

    result = await agent._tool_delegate_submodule({"entity_names": ["A"], "focus": ""})

    assert "error" in result
    assert "count" in result.get("error", "") or "delegation" in result.get("error", "").lower()
