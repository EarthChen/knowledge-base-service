"""TDD tests for wiki audit fixes: compose concurrency, public entity digest API."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.data_collector import PageData
from wiki.models import SourceLocation
from wiki import pipeline_nodes as pipeline_nodes_mod
from wiki.pipeline_nodes import (
    _count_modules_in_domain_tree,
    _find_domain_in_tree,
    _flatten_all_domains,
    compose_leaf_pages_node,
)
from wiki.semantic_diagram_gen import SemanticDiagramGenerator


@pytest.mark.asyncio
async def test_compose_pages_parallelizes_leaf_domains_with_bounded_concurrency() -> None:
    """Multiple leaf domains should compose concurrently (not strictly one-at-a-time)."""
    concurrent = [0]
    max_concurrent = [0]
    lock = asyncio.Lock()

    class FakeComposer:
        def __init__(self, llm: object, *, token_budget: int = 8000, **kwargs: object) -> None:
            self.llm = llm
            self.token_budget = token_budget

        async def compose_leaf_domain(self, domain: dict) -> list[dict]:
            async with lock:
                concurrent[0] += 1
                max_concurrent[0] = max(max_concurrent[0], concurrent[0])
            try:
                await asyncio.sleep(0.05)
            finally:
                async with lock:
                    concurrent[0] -= 1
            name = domain["name"]
            return [
                {
                    "title": name,
                    "content": "# x",
                    "path": f"wiki/{name}",
                    "page_type": "topic",
                    "domain": name,
                }
            ]

    n_domains = 8
    domain_tree = [
        {"name": f"domain{i}", "modules": [f"Mod{i}"], "children": []} for i in range(n_domains)
    ]
    modules_list = [
        {
            "uid": f"Module::Mod{i}:0",
            "label": "Module",
            "properties": {"name": f"Mod{i}"},
        }
        for i in range(n_domains)
    ]

    with patch("wiki.pipeline_nodes.TopicPageComposer", FakeComposer):
        state = {
            "domain_tree": domain_tree,
            "entity_roles": {},
            "modules": {"r1": modules_list},
        }
        await compose_leaf_pages_node(state, {"configurable": {"llm": None}})

    assert max_concurrent[0] >= 2, (
        "compose_leaf_domain should overlap for independent domains "
        f"(expected >= 2 concurrent, got max {max_concurrent[0]})"
    )
    assert max_concurrent[0] <= 5, (
        f"concurrency should be capped at 5 (got max {max_concurrent[0]})"
    )


def test_review_status_node_renamed_from_misleading_plan_structure() -> None:
    """Former plan_structure_node is set_review_status_node (only sets pending_review)."""
    assert hasattr(pipeline_nodes_mod, "set_review_status_node")
    assert not hasattr(pipeline_nodes_mod, "plan_structure_node")


def test_semantic_diagram_generator_exposes_build_entity_digest() -> None:
    """Public API should delegate to digest logic (no pipeline reliance on private _)."""
    center = GraphNode(
        label=NodeLabel.MODULE,
        properties={"name": "orders", "business_summary": "Handles orders"},
        uid="Domain::orders",
    )
    loc = SourceLocation(
        file_path="", start_line=0, end_line=0, fqn="orders", repository=""
    )
    page_data = PageData(
        node=center,
        edges=[],
        children=[],
        source_location=loc,
        method_locations=[],
        business_summary="Handles orders",
        methods=[],
    )
    gen = SemanticDiagramGenerator(None)
    assert hasattr(gen, "build_entity_digest")
    public = gen.build_entity_digest(page_data)
    private = gen._build_entity_digest(page_data)
    assert public == private
    assert "orders" in public


def test_find_domain_in_tree_top_level_and_nested_and_missing():
    tree = [
        {
            "name": "payments",
            "modules": ["PaySvc"],
            "children": [
                {
                    "name": "risk",
                    "modules": ["RiskEngine"],
                    "children": [],
                }
            ],
        }
    ]
    assert _find_domain_in_tree(tree, "payments") is tree[0]
    nested = _find_domain_in_tree(tree, "risk")
    assert nested is not None and nested.get("name") == "risk"
    assert _find_domain_in_tree(tree, "no-such-domain") is None


def test_flatten_all_domains_flat_nested_empty():
    flat = [
        {"name": "a", "children": [], "modules": ["m"]},
        {"name": "b", "children": [], "modules": []},
    ]
    assert len(_flatten_all_domains(flat)) == 2
    assert [n["name"] for n in _flatten_all_domains(flat)] == ["a", "b"]

    nested = [
        {
            "name": "parent",
            "modules": [],
            "children": [
                {"name": "child1", "modules": [], "children": []},
                {"name": "child2", "modules": [], "children": []},
            ],
        }
    ]
    names = [n["name"] for n in _flatten_all_domains(nested)]
    assert names == ["parent", "child1", "child2"]

    assert _flatten_all_domains([]) == []


def test_count_modules_in_domain_tree_flat_nested_empty():
    flat = [
        {"name": "x", "modules": ["m1", "m2"], "children": []},
        {"name": "y", "modules": ["m3"], "children": []},
    ]
    assert _count_modules_in_domain_tree(flat) == 3

    nested = [
        {
            "name": "root",
            "modules": ["a"],
            "children": [
                {"name": "c1", "modules": ["b", "c"], "children": []},
            ],
        }
    ]
    assert _count_modules_in_domain_tree(nested) == 3

    assert _count_modules_in_domain_tree([]) == 0
    assert _count_modules_in_domain_tree("not-a-list") == 0
