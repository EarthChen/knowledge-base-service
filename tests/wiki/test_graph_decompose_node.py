import pytest
from unittest.mock import AsyncMock, MagicMock


def test_graph_decompose_query_includes_inherits_and_implements():
    """The module edge query should include INHERITS and IMPLEMENTS relationships."""
    from wiki.nodes.graph_nodes import _GRAPH_DECOMPOSE_MODULE_EDGES_CY

    query = _GRAPH_DECOMPOSE_MODULE_EDGES_CY
    assert "INHERITS" in query, "Query should include INHERITS edges"
    assert "IMPLEMENTS" in query, "Query should include IMPLEMENTS edges"
    assert query.count("UNION") >= 4, (
        "Should have at least 4 UNION clauses (IMPORTS, CALLS, DEPENDS_ON, INHERITS, IMPLEMENTS)"
    )


@pytest.mark.asyncio
async def test_graph_decompose_node_produces_module_tree():
    from wiki.nodes.graph_nodes import graph_decompose_node

    mock_graph_store = AsyncMock()
    mock_result = MagicMock()
    mock_result.data = []
    mock_graph_store.execute_query.return_value = mock_result

    state = {
        "business_id": "test-biz",
        "repositories": ["repo1"],
        "modules": {
            "repo1": [
                {"uid": "Module:src/a.py:ModA:0", "label": "Module", "properties": {"name": "ModA", "path": "src/a.py", "code_length": 1000}},
                {"uid": "Module:src/b.py:ModB:0", "label": "Module", "properties": {"name": "ModB", "path": "src/b.py", "code_length": 800}},
            ],
        },
        "module_tree": [],
        "config": {},
    }

    config = {"configurable": {"graph_store": mock_graph_store}}
    result = await graph_decompose_node(state, config)
    assert "module_tree" in result
    assert len(result["module_tree"]) > 0


@pytest.mark.asyncio
async def test_graph_decompose_node_no_graph_store():
    from wiki.nodes.graph_nodes import graph_decompose_node

    state = {
        "business_id": "test",
        "repositories": ["repo1"],
        "modules": {
            "repo1": [
                {"uid": "Module:x.py:X:0", "label": "Module", "properties": {"name": "X", "path": "x.py", "code_length": 100}},
            ],
        },
        "module_tree": [],
        "config": {},
    }
    config = {"configurable": {}}
    result = await graph_decompose_node(state, config)
    assert "module_tree" in result


@pytest.mark.asyncio
async def test_graph_decompose_incremental_empty_diff_skips_cypher():
    """Incremental run with no affected modules should skip expensive Cypher queries."""
    from wiki.nodes.graph_nodes import graph_decompose_node

    mock_graph_store = AsyncMock()
    state = {
        "business_id": "test-biz",
        "repositories": ["repo1", "repo2"],
        "is_incremental": True,
        "affected_modules": [],
        "modules": {
            "repo1": [
                {"uid": "Module:src/a.py:ModA:0", "label": "Module", "properties": {"name": "ModA", "path": "src/a.py", "code_length": 1000}},
            ],
        },
        "module_tree": [{"name": "existing", "children": []}],
    }
    config = {"configurable": {"graph_store": mock_graph_store}}

    result = await graph_decompose_node(state, config)

    mock_graph_store.execute_query.assert_not_called()
    assert result == {}
