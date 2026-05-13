"""Tests for DomainDocAgent snippet pre-fill from graph before explore."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.domain_doc_agent import DomainDocAgent


@pytest.mark.asyncio
async def test_prefills_code_snippets_before_explore():
    query_result = MagicMock()
    query_result.data = [
        {
            "func_name": "handleRequest",
            "snippet": "void handleRequest() { }",
            "file_path": "src/App.java",
        },
    ]
    mock_graph = MagicMock()
    mock_graph.execute_query = AsyncMock(return_value=query_result)

    explore_captured: dict = {}

    async def explore_side_effect(*, memory, **kwargs):
        explore_captured["memory"] = memory
        assert len(memory.code_snippets) >= 1
        assert "handleRequest" in memory.code_snippets[0]
        assert "App.java" in memory.code_snippets[0]

    agent = DomainDocAgent(
        domain_name="orders",
        llm=MagicMock(),
        graph_store=mock_graph,
    )
    agent._page_agent.explore = AsyncMock(side_effect=explore_side_effect)
    agent._page_agent.write = AsyncMock(return_value="# Orders\n\nModA covered.")

    with patch("wiki.domain_doc_agent.evaluate_quality") as mock_eval:
        mock_eval.return_value = MagicMock(
            coverage=0.96,
            citation_density=0.6,
            context_gap_count=0,
            uncovered_modules=[],
        )
        await agent.generate_with_iterations(
            module_names=["ModA"],
            baseline_context="baseline",
        )

    mock_graph.execute_query.assert_called()
    assert explore_captured.get("memory") is not None
