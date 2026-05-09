import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_assign_keys_populates_canonical_keys():
    from wiki.nodes.graph_nodes import assign_canonical_keys_node

    state = {
        "business_id": "test",
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1"],
                "file_paths": ["src/auth/login.py"],
                "title": "",
                "description": "",
                "token_estimate": 0,
                "children": [],
            },
        ],
    }
    result = await assign_canonical_keys_node(state)
    assert "canonical_keys" in result
    assert "src-auth" in result["canonical_keys"]


@pytest.mark.asyncio
async def test_generate_titles_fills_title():
    from wiki.nodes.graph_nodes import generate_titles_node

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"title": "认证模块", "description": "处理登录注册"}'

    state = {
        "business_id": "test",
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1"],
                "file_paths": ["src/auth/login.py"],
                "title": "",
                "description": "",
                "token_estimate": 0,
                "children": [],
            },
        ],
        "canonical_keys": {"src-auth": ""},
    }
    config = {"configurable": {"llm": mock_llm}}
    result = await generate_titles_node(state, config)
    assert "canonical_keys" in result
    assert "module_tree" in result


@pytest.mark.asyncio
async def test_generate_titles_no_llm_uses_key():
    from wiki.nodes.graph_nodes import generate_titles_node

    state = {
        "business_id": "test",
        "module_tree": [
            {
                "canonical_key": "src-auth",
                "entity_uids": ["u1"],
                "file_paths": ["src/auth/login.py"],
                "title": "",
                "description": "",
                "token_estimate": 0,
                "children": [],
            },
        ],
        "canonical_keys": {"src-auth": ""},
    }
    config = {"configurable": {}}
    result = await generate_titles_node(state, config)
    # single entity_uid → title derived from entity name
    assert result["canonical_keys"]["src-auth"] == "u1"
