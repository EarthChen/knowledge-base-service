import pytest
from unittest.mock import AsyncMock, MagicMock, patch

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


@pytest.mark.asyncio
async def test_compose_bottomup_with_graph_store_calls_enrich_for_leaves():
    """When graph_store is in config, leaf nodes trigger graph context enrichment."""
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "# Foo Service\n\nGenerated with context."
    mock_graph_store = AsyncMock()
    mock_graph_store.execute_query = AsyncMock(return_value=MagicMock(data=[]))

    leaf = ModuleNode(
        canonical_key="leaf-mod",
        entity_uids=["FooService"],
        file_paths=["src/foo.py"],
        title="Foo Service",
    )
    tree = ModuleTree(roots=[leaf], repo_id="test")

    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
    }
    config = {
        "configurable": {
            "llm": mock_llm,
            "graph_store": mock_graph_store,
        },
    }

    with patch("wiki.nodes.graph_nodes._enrich_leaf_context", new_callable=AsyncMock) as mock_enrich:
        mock_enrich.return_value = "### 方法签名\n- `FooService.bar()`"
        from wiki.nodes.graph_nodes import compose_bottomup_node

        result = await compose_bottomup_node(state, config)

    pages = result["pages"]
    assert len(pages) == 1
    assert pages[0]["content"]
    mock_enrich.assert_called_once()
    mock_llm.generate.assert_called()
    call_args = mock_llm.generate.call_args
    assert "FooService" in str(call_args) or "方法签名" in str(call_args)


@pytest.mark.asyncio
async def test_enrich_leaf_context_returns_structured_text():
    """_enrich_leaf_context should query graph and return structured context string."""
    from wiki.nodes.graph_nodes import _enrich_leaf_context

    node = ModuleNode(
        canonical_key="auth-service",
        entity_uids=["AuthService", "LoginHandler"],
        file_paths=["src/auth/service.py"],
        children=[],
    )

    mock_graph = AsyncMock()
    # METHODS_CY result
    methods_result = MagicMock()
    methods_result.data = [
        {
            "module_name": "AuthService",
            "func_name": "login",
            "signature": "(username, password)",
            "docstring": "Authenticate user",
            "file_path": "src/auth/service.py",
        },
    ]
    # CALLERS_CY result
    callers_result = MagicMock()
    callers_result.data = [
        {"caller_name": "ApiController", "target_name": "AuthService"},
    ]
    # call_chain result
    chain_result = MagicMock()
    chain_result.data = [
        {
            "caller": "ApiController",
            "callee": "AuthService",
            "caller_functions": ["handle_request"],
            "callee_functions": ["login"],
        },
    ]
    # CHUNK_SNIPPETS_CY result
    snippets_result = MagicMock()
    snippets_result.data = [
        {
            "entity_name": "AuthService",
            "snippet": "class AuthService:\n    def login(self, username, password):\n        return self.db.authenticate(username, password)",
            "file_path": "src/auth/service.py",
        },
    ]

    mock_graph.execute_query = AsyncMock(
        side_effect=[methods_result, callers_result, chain_result, snippets_result]
    )

    result = await _enrich_leaf_context(node, mock_graph)

    assert isinstance(result, str)
    assert "login" in result
    assert "AuthService" in result
    assert "ApiController" in result
    assert len(result) > 100
    assert len(result) <= 8000


@pytest.mark.asyncio
async def test_compose_leaf_uses_enriched_context_when_graph_available():
    """When graph_store is available, _compose_leaf_for_bottomup should include code snippets in prompt."""
    from wiki.nodes.graph_nodes import _compose_leaf_for_bottomup

    node = ModuleNode(
        canonical_key="auth-service",
        entity_uids=["AuthService"],
        file_paths=["src/auth/service.py"],
        children=[],
    )
    node.title = "Auth Service"

    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value="# Auth Service\n\nHandles authentication with login() method."
    )

    mock_graph = AsyncMock()

    with patch("wiki.nodes.graph_nodes._enrich_leaf_context", new_callable=AsyncMock) as mock_enrich:
        mock_enrich.return_value = "### 方法签名\n- `AuthService.login(username, password)` — Authenticate user"
        result = await _compose_leaf_for_bottomup(
            node, mock_llm, None, graph_store=mock_graph
        )

    assert result["content"]
    mock_enrich.assert_called_once_with(node, mock_graph)
    call_args = mock_llm.generate.call_args
    prompt_text = str(call_args)
    assert "AuthService.login" in prompt_text or "方法签名" in prompt_text
