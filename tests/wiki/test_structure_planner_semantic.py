"""Tests for WikiStructurePlanner semantic grouping (G-DW1)."""
import json
import pytest
from unittest.mock import AsyncMock

from store.schema import GraphNode, NodeLabel
from wiki.models import PageType, ScopeParam
from wiki.structure_planner import WikiStructurePlanner


def _make_module(name: str, path: str = "", business_summary: str = "") -> GraphNode:
    return GraphNode(
        uid=f"Module:{name}",
        label=NodeLabel.MODULE,
        properties={
            "name": name,
            "path": path or f"src/{name}",
            "business_summary": business_summary,
        },
    )


def _mock_graph(modules: list[GraphNode]) -> AsyncMock:
    graph = AsyncMock()
    graph.find_top_level_modules = AsyncMock(return_value=modules)
    return graph


def _mock_llm(groups_json: list[dict] | Exception) -> AsyncMock:
    llm = AsyncMock()
    if isinstance(groups_json, Exception):
        llm.complete_json = AsyncMock(side_effect=groups_json)
        llm.generate = AsyncMock(side_effect=groups_json)
    else:
        llm.complete_json = AsyncMock(return_value={"groups": groups_json})
        llm.generate = AsyncMock(return_value=json.dumps({"groups": groups_json}))
    return llm


@pytest.mark.asyncio
async def test_small_repo_no_semantic_grouping():
    """Repos with fewer modules than threshold should NOT trigger LLM grouping."""
    modules = [_make_module(f"mod_{i}") for i in range(5)]
    graph = _mock_graph(modules)
    llm = _mock_llm([])  # Should not be called

    planner = WikiStructurePlanner(graph, llm=llm, semantic_group_threshold=12)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    assert structure.root.page_type == PageType.REPO_OVERVIEW
    assert len(structure.root.children) == 5
    llm.complete_json.assert_not_awaited()
    llm.generate.assert_not_awaited()


@pytest.mark.asyncio
async def test_large_repo_triggers_semantic_grouping():
    """Repos with many modules should trigger LLM grouping into categories."""
    modules = [
        _make_module("auth", business_summary="Authentication and authorization"),
        _make_module("users", business_summary="User management"),
        _make_module("orders", business_summary="Order processing"),
        _make_module("payments", business_summary="Payment gateway integration"),
        _make_module("products", business_summary="Product catalog"),
        _make_module("inventory", business_summary="Inventory tracking"),
        _make_module("shipping", business_summary="Shipping and delivery"),
        _make_module("notifications", business_summary="Email and push notifications"),
        _make_module("analytics", business_summary="Data analytics"),
        _make_module("logging", business_summary="Centralized logging"),
        _make_module("config", business_summary="Configuration management"),
        _make_module("cache", business_summary="Caching layer"),
        _make_module("api_gateway", business_summary="API routing"),
        _make_module("migrations", business_summary="Database migrations"),
        _make_module("scheduler", business_summary="Task scheduling"),
    ]
    graph = _mock_graph(modules)
    llm_groups = [
        {"group_name": "Core Business", "modules": ["auth", "users", "orders", "payments"]},
        {"group_name": "Product & Inventory", "modules": ["products", "inventory", "shipping"]},
        {"group_name": "Infrastructure", "modules": ["logging", "config", "cache", "api_gateway", "migrations", "scheduler"]},
        {"group_name": "Communication", "modules": ["notifications", "analytics"]},
    ]
    llm = _mock_llm(llm_groups)

    planner = WikiStructurePlanner(graph, llm=llm, semantic_group_threshold=12)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    assert structure.root.page_type == PageType.REPO_OVERVIEW
    llm.complete_json.assert_awaited_once()

    group_names = [c.title for c in structure.root.children]
    assert "Core Business" in group_names
    assert "Infrastructure" in group_names

    # Each group should have child modules
    for child in structure.root.children:
        if child.title == "Core Business":
            assert len(child.children) == 4
        if child.title == "Infrastructure":
            assert len(child.children) == 6


@pytest.mark.asyncio
async def test_semantic_grouping_llm_failure_fallback():
    """When LLM fails, should fallback to flat module list."""
    modules = [_make_module(f"mod_{i}") for i in range(15)]
    graph = _mock_graph(modules)
    llm = _mock_llm(RuntimeError("LLM service unavailable"))

    planner = WikiStructurePlanner(graph, llm=llm, semantic_group_threshold=12)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    assert structure.root.page_type == PageType.REPO_OVERVIEW
    assert len(structure.root.children) == 15  # Flat, no grouping
    assert all(c.children == [] for c in structure.root.children)


@pytest.mark.asyncio
async def test_semantic_grouping_respects_threshold():
    """Custom threshold should be respected."""
    modules = [_make_module(f"mod_{i}") for i in range(6)]
    graph = _mock_graph(modules)
    llm_groups = [
        {"group_name": "Group A", "modules": ["mod_0", "mod_1", "mod_2"]},
        {"group_name": "Group B", "modules": ["mod_3", "mod_4", "mod_5"]},
    ]
    llm = _mock_llm(llm_groups)

    planner = WikiStructurePlanner(graph, llm=llm, semantic_group_threshold=5)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    llm.complete_json.assert_awaited_once()
    assert len(structure.root.children) == 2  # Two groups


@pytest.mark.asyncio
async def test_no_llm_no_grouping():
    """When LLM is None, no grouping regardless of module count."""
    modules = [_make_module(f"mod_{i}") for i in range(20)]
    graph = _mock_graph(modules)

    planner = WikiStructurePlanner(graph, llm=None)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    assert len(structure.root.children) == 20  # Flat


@pytest.mark.asyncio
async def test_semantic_grouping_unassigned_modules():
    """Modules not assigned by LLM should still appear in the tree."""
    modules = [_make_module(f"mod_{i}") for i in range(15)]
    graph = _mock_graph(modules)
    # LLM only assigns some modules
    llm_groups = [
        {"group_name": "Group A", "modules": ["mod_0", "mod_1"]},
    ]
    llm = _mock_llm(llm_groups)

    planner = WikiStructurePlanner(graph, llm=llm, semantic_group_threshold=12)
    scope = ScopeParam(scope_type="repo", value="test-repo")
    structure = await planner.plan("test-repo", scope)

    # Group A (2 modules) + 13 unassigned flat modules
    total_children = len(structure.root.children)
    assert total_children == 14  # 1 group + 13 flat
