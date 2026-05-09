import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_compose_bottomup_generates_pages():
    from wiki.nodes.graph_nodes import compose_bottomup_node

    state = {
        "business_id": "test",
        "repositories": ["repo1"],
        "modules": {"repo1": []},
        "module_tree": [
            {
                "canonical_key": "root",
                "entity_uids": ["u1", "u2"],
                "file_paths": ["a.py", "b.py"],
                "title": "Root Module",
                "description": "",
                "token_estimate": 1000,
                "children": [
                    {
                        "canonical_key": "leaf-a",
                        "entity_uids": ["u1"],
                        "file_paths": ["a.py"],
                        "title": "Leaf A",
                        "description": "",
                        "token_estimate": 500,
                        "children": [],
                    },
                ],
            },
        ],
        "canonical_keys": {"root": "Root Module", "leaf-a": "Leaf A"},
        "domain_cache": {},
        "pages": [],
        "config": {},
        "language": "zh",
        "errors": [],
    }

    mock_llm = AsyncMock()
    mock_llm.agenerate.return_value = "# Generated Content"
    config = {"configurable": {"llm": mock_llm}}

    result = await compose_bottomup_node(state, config)
    assert "pages" in result
    assert len(result["pages"]) >= 2  # leaf + parent
