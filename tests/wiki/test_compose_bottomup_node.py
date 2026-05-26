import asyncio
import hashlib

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.models.module_tree import ModuleNode, ModuleTree

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")


async def _deterministic_llm_generate(
    prompt: str,
    system: str | None = None,
    max_tokens: int | None = None,
) -> str:
    """Stateful LLM mock: parent synthesis uses architect system string."""
    if system and "架构师" in str(system):
        digest = hashlib.sha256(prompt.encode()).hexdigest()[:24]
        return f"# synth\n{digest}"
    return "# leaf-static\n"


async def _expected_parent_contents_by_key(
    parents: list,
    initial_contents: dict[str, str],
    llm: MagicMock,
) -> dict[str, str]:
    from wiki.nodes.graph_nodes import _synthesize_parent_for_bottomup

    nc = dict(initial_contents)
    out: dict[str, str] = {}
    for node in parents:
        child_contents = [nc.get(c.canonical_key, "") for c in node.children]
        page_dict = await _synthesize_parent_for_bottomup(
            node, child_contents, llm,
        )
        text = page_dict.get("content", "")
        nc[node.canonical_key] = text
        out[node.canonical_key] = text
    return out


def _three_level_tree() -> ModuleTree:
    leaf1 = ModuleNode(
        canonical_key="leaf-1",
        entity_uids=["A"],
        file_paths=["a.py"],
        title="Leaf 1",
    )
    leaf2 = ModuleNode(
        canonical_key="leaf-2",
        entity_uids=["B"],
        file_paths=["b.py"],
        title="Leaf 2",
    )
    mid1 = ModuleNode(
        canonical_key="mid-1",
        entity_uids=["A"],
        file_paths=["a.py"],
        title="Mid 1",
        children=[leaf1],
    )
    mid2 = ModuleNode(
        canonical_key="mid-2",
        entity_uids=["B"],
        file_paths=["b.py"],
        title="Mid 2",
        children=[leaf2],
    )
    root = ModuleNode(
        canonical_key="root-3l",
        entity_uids=["A", "B"],
        file_paths=["a.py", "b.py"],
        title="Root 3L",
        children=[mid1, mid2],
    )
    return ModuleTree(roots=[root], repo_id="test-3l")


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


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_compose_bottomup_parent_waves_match_sequential_content():
    """Wave parent synthesis yields same page text as sequential replay (pure LLM mock)."""
    from wiki.nodes.graph_nodes import compose_bottomup_node

    tree = _three_level_tree()
    topo = tree.topological_order()
    leaves = [n for n in topo if n.is_leaf()]
    parents = [n for n in topo if not n.is_leaf()]
    leaf_keys = {n.canonical_key for n in leaves}
    parent_keys = {n.canonical_key for n in parents}

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_deterministic_llm_generate)

    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test-3l",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
        "modules": {},
    }
    result = await compose_bottomup_node(state, {"configurable": {"llm": mock_llm}})

    nc0 = {
        p["canonical_key"]: p["content"]
        for p in result["pages"]
        if p["canonical_key"] in leaf_keys
    }
    expected = await _expected_parent_contents_by_key(parents, nc0, mock_llm)
    actual = {
        p["canonical_key"]: p["content"]
        for p in result["pages"]
        if p["canonical_key"] in parent_keys
    }
    assert actual == expected
    assert len(actual) == len(parent_keys)


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_compose_bottomup_parent_waves_respect_dependencies():
    """Root parent runs only after all intermediate parents have finished."""
    from wiki.nodes import graph_nodes as gn
    from wiki.nodes.graph_nodes import compose_bottomup_node

    tree = _three_level_tree()
    order: list[str] = []

    orig = gn._synthesize_parent_for_bottomup

    async def _track(
        node: ModuleNode,
        child_contents: list[str],
        llm: object,
    ) -> dict:
        order.append(node.canonical_key)
        return await orig(node, child_contents, llm)

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_deterministic_llm_generate)

    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test-3l",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
        "modules": {},
    }
    with patch.object(gn, "_synthesize_parent_for_bottomup", side_effect=_track):
        await compose_bottomup_node(state, {"configurable": {"llm": mock_llm}})

    root_i = order.index("root-3l")
    assert root_i > order.index("mid-1")
    assert root_i > order.index("mid-2")


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_compose_bottomup_sibling_parents_run_concurrently():
    """Two sibling intermediate parents should overlap in time (same wave)."""
    from wiki.nodes.graph_nodes import compose_bottomup_node

    tree = _three_level_tree()
    lock = asyncio.Lock()
    active = 0
    max_active = 0

    async def _gen(prompt: str, system: str | None = None, max_tokens: int | None = None) -> str:
        nonlocal active, max_active
        if system and "架构师" in str(system):
            async with lock:
                active += 1
                max_active = max(max_active, active)
            try:
                await asyncio.sleep(0.06)
            finally:
                async with lock:
                    active -= 1
            return "# parent"
        return "# leaf"

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_gen)

    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test-3l",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
        "modules": {},
    }
    await compose_bottomup_node(state, {"configurable": {"llm": mock_llm}})
    assert max_active >= 2


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_compose_bottomup_parent_timeout_fallback(monkeypatch):
    from wiki.nodes import graph_nodes as gn
    from wiki.nodes.graph_nodes import compose_bottomup_node

    monkeypatch.setattr(gn, "_PARENT_TIMEOUT_SEC", 0.05)

    async def _slow_parent(
        prompt: str,
        system: str | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if system and "架构师" in str(system):
            await asyncio.sleep(0.3)
            return "# late"
        return "# leaf"

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_slow_parent)

    tree = _three_level_tree()
    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test-3l",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
        "modules": {},
    }
    result = await compose_bottomup_node(state, {"configurable": {"llm": mock_llm}})

    for p in result["pages"]:
        if p["canonical_key"] in {"mid-1", "mid-2", "root-3l"}:
            assert "(Synthesis timed out)" in p["content"]


@pytest.mark.timeout(30)
@pytest.mark.asyncio
async def test_compose_bottomup_parent_gather_error_fallback():
    """Unexpected errors from parent synthesis surface as Generation failed pages."""
    from wiki.nodes import graph_nodes as gn
    from wiki.nodes.graph_nodes import compose_bottomup_node

    calls = 0

    orig = gn._synthesize_parent_for_bottomup

    async def _flaky(
        node: ModuleNode,
        child_contents: list[str],
        llm: object,
    ) -> dict:
        nonlocal calls
        calls += 1
        if node.canonical_key == "mid-2":
            msg = "simulated parent failure"
            raise RuntimeError(msg)
        return await orig(node, child_contents, llm)

    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(side_effect=_deterministic_llm_generate)

    tree = _three_level_tree()
    state = {
        "module_tree": tree.to_dicts(),
        "business_id": "test-3l",
        "domain_cache": {},
        "module_summaries": {},
        "pages": [],
        "modules": {},
    }
    with patch.object(gn, "_synthesize_parent_for_bottomup", side_effect=_flaky):
        result = await compose_bottomup_node(state, {"configurable": {"llm": mock_llm}})

    failed = next(p for p in result["pages"] if p["canonical_key"] == "mid-2")
    assert "(Generation failed)" in failed["content"]
    root_page = next(p for p in result["pages"] if p["canonical_key"] == "root-3l")
    assert root_page["content"]
