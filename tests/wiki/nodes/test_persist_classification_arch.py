"""Tests for architecture layer persistence in persist_classification_node."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest


@pytest.fixture
def mock_graph_store() -> AsyncMock:
    store = AsyncMock()
    store.update_node_property = AsyncMock()
    return store


@pytest.fixture
def base_state() -> dict:
    return {
        "business_id": "biz1",
        "domain_mapping": {
            "user-domain": [("repo1", "UserController"), ("repo1", "UserService")],
        },
        "domain_display_names": {"user-domain": "User Domain"},
        "modules": {
            "repo1": [
                {
                    "uid": "Module:repo1:UserController",
                    "label": "Module",
                    "properties": {"name": "UserController"},
                },
                {
                    "uid": "Module:repo1:UserService",
                    "label": "Module",
                    "properties": {"name": "UserService"},
                },
            ],
        },
        "architecture_layers": {
            "UserController": {"layer": "api", "confidence": 0.9},
            "UserService": {"layer": "service", "confidence": 0.8},
        },
    }


@pytest.mark.asyncio
async def test_persist_arch_layers_written(mock_graph_store: AsyncMock, base_state: dict) -> None:
    """Verify update_node_property called with wiki_architecture_layer and wiki_architecture_confidence."""
    from wiki.nodes.persist_classification import persist_classification_node

    mock_wiki_store = AsyncMock()
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()

    config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
    await persist_classification_node(base_state, config)

    arch_calls = [
        c
        for c in mock_graph_store.update_node_property.call_args_list
        if c.args[2] in ("wiki_architecture_layer", "wiki_architecture_confidence")
    ]
    assert len(arch_calls) == 4

    layer_calls = {c.args[1]: c.args[3] for c in arch_calls if c.args[2] == "wiki_architecture_layer"}
    conf_calls = {c.args[1]: c.args[3] for c in arch_calls if c.args[2] == "wiki_architecture_confidence"}
    assert layer_calls["Module:repo1:UserController"] == "api"
    assert layer_calls["Module:repo1:UserService"] == "service"
    assert conf_calls["Module:repo1:UserController"] == 0.9
    assert conf_calls["Module:repo1:UserService"] == 0.8


@pytest.mark.asyncio
async def test_persist_arch_layers_compound_key(mock_graph_store: AsyncMock, base_state: dict) -> None:
    """architecture_layers keyed by repo|name are resolved via compound lookup."""
    from wiki.nodes.persist_classification import persist_classification_node

    base_state["architecture_layers"] = {
        "repo1|UserController": {"layer": "api", "confidence": 0.9},
        "repo1|UserService": {"layer": "service", "confidence": 0.8},
    }
    mock_wiki_store = AsyncMock()
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()

    config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
    await persist_classification_node(base_state, config)

    arch_calls = [
        c
        for c in mock_graph_store.update_node_property.call_args_list
        if c.args[2] in ("wiki_architecture_layer", "wiki_architecture_confidence")
    ]
    assert len(arch_calls) == 4

    layer_calls = {c.args[1]: c.args[3] for c in arch_calls if c.args[2] == "wiki_architecture_layer"}
    conf_calls = {c.args[1]: c.args[3] for c in arch_calls if c.args[2] == "wiki_architecture_confidence"}
    assert layer_calls["Module:repo1:UserController"] == "api"
    assert layer_calls["Module:repo1:UserService"] == "service"
    assert conf_calls["Module:repo1:UserController"] == 0.9
    assert conf_calls["Module:repo1:UserService"] == 0.8


@pytest.mark.asyncio
async def test_persist_arch_layers_empty(mock_graph_store: AsyncMock, base_state: dict) -> None:
    """No arch_layers → no architecture property calls."""
    from wiki.nodes.persist_classification import persist_classification_node

    base_state["architecture_layers"] = {}
    mock_wiki_store = AsyncMock()
    mock_wiki_store.upsert_wiki_space = AsyncMock()
    mock_wiki_store.upsert_wiki_section = AsyncMock()
    mock_wiki_store.add_has_child_edge = AsyncMock()

    config = {"configurable": {"wiki_store": mock_wiki_store, "graph_store": mock_graph_store}}
    await persist_classification_node(base_state, config)

    arch_calls = [
        c
        for c in mock_graph_store.update_node_property.call_args_list
        if c.args[2] in ("wiki_architecture_layer", "wiki_architecture_confidence")
    ]
    assert len(arch_calls) == 0
