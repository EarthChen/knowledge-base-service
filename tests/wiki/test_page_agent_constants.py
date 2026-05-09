import pytest
from unittest.mock import AsyncMock


def test_single_result_limit_is_6000():
    from wiki.page_agent import SINGLE_RESULT_LIMIT
    assert SINGLE_RESULT_LIMIT == 6000


@pytest.mark.asyncio
async def test_tool_read_code_default_truncates_at_single_result_limit():
    from wiki.page_agent import SINGLE_RESULT_LIMIT, WikiPageAgent

    long_snippet = "x" * (SINGLE_RESULT_LIMIT + 500)
    mock_graph = AsyncMock()
    mock_graph.execute_query = AsyncMock(
        return_value=type("R", (), {
            "data": [{
                "name": "Foo",
                "type": "Function",
                "file": "a.py",
                "start_line": 1,
                "end_line": 10,
                "snippet": long_snippet,
            }],
        })(),
    )
    agent = WikiPageAgent(llm=AsyncMock(), graph_store=mock_graph, repo_path="/tmp/repo")
    result = await agent._tool_read_code({"entity_name": "Foo"})
    assert result["code"] == "x" * SINGLE_RESULT_LIMIT
    assert len(result["code"]) == SINGLE_RESULT_LIMIT


def test_working_memory_max_total_chars_is_80000():
    from wiki.page_agent import WorkingMemory
    assert WorkingMemory.MAX_TOTAL_CHARS == 80000
