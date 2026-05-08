# tests/wiki/test_agent_generate.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from wiki.page_agent import WikiPageAgent


@pytest.mark.asyncio
async def test_agent_generate_returns_markdown():
    """Agent.generate() should return non-empty markdown with expected sections."""
    mock_llm = MagicMock()
    mock_llm.complete_with_tools = AsyncMock(return_value={
        "content": "## 概述\nTest module overview\n## 核心业务流程\nNo data\n## 关键实现\nImpl\n## 依赖关系\nNone",
        "tool_calls": None,
    })
    mock_llm.generate = AsyncMock(return_value="## 概述\nTest module\n## 核心业务流程\nNo data")

    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=[])

    agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph)
    result = await agent.generate(
        module_names=["TestModule"],
        domain_name="test_domain",
        baseline_context={"modules": [{"name": "TestModule"}]},
        max_rounds=3,
    )

    assert result is not None
    assert len(result) > 50
    assert "概述" in result or "Overview" in result


@pytest.mark.asyncio
async def test_agent_generate_fallback_on_error():
    """Agent.generate() should return skeleton content on LLM failure."""
    mock_llm = MagicMock()
    mock_llm.complete_with_tools = AsyncMock(side_effect=Exception("LLM API error"))
    mock_llm.generate = AsyncMock(side_effect=Exception("LLM API error"))

    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=[])

    agent = WikiPageAgent(llm=mock_llm, graph_store=mock_graph)
    result = await agent.generate(
        module_names=["TestModule"],
        domain_name="test_domain",
        baseline_context={},
        max_rounds=3,
    )

    assert result is not None
    assert "TestModule" in result
    assert "CONTEXT_GAP" in result or "概述" in result
