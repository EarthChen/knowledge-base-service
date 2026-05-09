import pytest
from unittest.mock import AsyncMock, MagicMock


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
                {"uid": "uid1", "label": "Module", "properties": {"name": "ModA", "file_path": "src/a.py", "code_length": 1000}},
                {"uid": "uid2", "label": "Module", "properties": {"name": "ModB", "file_path": "src/b.py", "code_length": 800}},
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
                {"uid": "u1", "label": "Module", "properties": {"name": "X", "file_path": "x.py", "code_length": 100}},
            ],
        },
        "module_tree": [],
        "config": {},
    }
    config = {"configurable": {}}
    result = await graph_decompose_node(state, config)
    assert "module_tree" in result
