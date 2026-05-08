"""Test that _query_call_chains reads caller_functions/callee_functions from module rows."""
import asyncio
from unittest.mock import AsyncMock
from dataclasses import dataclass

import pytest


@dataclass
class _FakeResult:
    data: list


@pytest.fixture
def mock_graph():
    graph = AsyncMock()
    graph.execute_query = AsyncMock()
    return graph


def test_caller_functions_used_from_module_rows(mock_graph):
    """When module_rows contain caller_functions/callee_functions, those should populate CallChainStep."""
    from wiki.content_context_builder import ContentContextBuilder, CallChainStep

    module_rows = _FakeResult(data=[
        {
            "caller": "ModuleA",
            "callee": "ModuleB",
            "caller_functions": ["handleRequest", "processData"],
            "callee_functions": ["save", "validate"],
        },
        {
            "caller": "ModuleB",
            "callee": "ModuleC",
            "caller_functions": [],
            "callee_functions": ["notify"],
        },
    ])
    method_rows = _FakeResult(data=[])

    mock_graph.execute_query = AsyncMock(side_effect=[module_rows, method_rows])

    ccb = ContentContextBuilder.__new__(ContentContextBuilder)
    ccb._graph = mock_graph

    steps = asyncio.run(ccb._query_call_chains(["ModuleA", "ModuleB"], depth=2))

    assert len(steps) == 2
    assert steps[0].caller_method == "handleRequest"
    assert steps[0].callee_method == "save"
    assert steps[1].caller_method == ""
    assert steps[1].callee_method == "notify"


def test_old_method_map_bug_not_present(mock_graph):
    """All rows should NOT share the same caller_method — the old bug."""
    from wiki.content_context_builder import ContentContextBuilder

    module_rows = _FakeResult(data=[
        {"caller": "A", "callee": "B", "caller_functions": ["fn1"], "callee_functions": ["fn2"]},
        {"caller": "C", "callee": "D", "caller_functions": ["fn3"], "callee_functions": ["fn4"]},
    ])
    method_rows = _FakeResult(data=[])

    mock_graph.execute_query = AsyncMock(side_effect=[module_rows, method_rows])

    ccb = ContentContextBuilder.__new__(ContentContextBuilder)
    ccb._graph = mock_graph

    steps = asyncio.run(ccb._query_call_chains(["A", "C"], depth=2))

    assert steps[0].caller_method == "fn1"
    assert steps[1].caller_method == "fn3"
    assert steps[0].caller_method != steps[1].caller_method
