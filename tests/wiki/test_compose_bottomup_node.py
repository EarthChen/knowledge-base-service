import pytest
from unittest.mock import AsyncMock

from wiki.models.module_tree import ModuleNode, ModuleTree


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
    mock_llm.generate.return_value = "# Generated Content"
    config = {"configurable": {"llm": mock_llm}}

    result = await compose_bottomup_node(state, config)
    assert "pages" in result
    assert len(result["pages"]) >= 2  # leaf + parent


@pytest.mark.asyncio
async def test_compose_bottomup_with_parent_children():
    """When tree has parent-children structure, ParentSynthesizer should be called."""
    from wiki.nodes.graph_nodes import compose_bottomup_node

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "# Generated Content\n\nSome content."

    child1 = ModuleNode(
        canonical_key="child-1",
        entity_uids=["A"],
        file_paths=["src/a.py"],
        title="Child 1",
    )
    child2 = ModuleNode(
        canonical_key="child-2",
        entity_uids=["B"],
        file_paths=["src/b.py"],
        title="Child 2",
    )
    parent = ModuleNode(
        canonical_key="parent-mod",
        entity_uids=["A", "B"],
        file_paths=["src/a.py", "src/b.py"],
        title="Parent Module",
        children=[child1, child2],
    )
    tree = ModuleTree(roots=[parent], repo_id="test")

    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
    }
    config = {"configurable": {"llm": mock_llm}}

    result = await compose_bottomup_node(state, config)

    pages = result["pages"]
    assert len(pages) == 3
    page_keys = {p["canonical_key"] for p in pages}
    assert "child-1" in page_keys
    assert "child-2" in page_keys
    assert "parent-mod" in page_keys
    assert mock_llm.generate.call_count >= 3
