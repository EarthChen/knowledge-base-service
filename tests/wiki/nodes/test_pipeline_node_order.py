"""Tests verifying wiki pipeline node execution order."""

from __future__ import annotations

from wiki.pipeline_graph import _NODE_PHASE_MAP, build_wiki_pipeline
from wiki.topo_sort import kahn_topological_order


def _pipeline_execution_order() -> list[str]:
    pipeline = build_wiki_pipeline(checkpointer=False)
    graph = pipeline.get_graph()
    adjacency: dict[str, list[str]] = {}
    for edge in graph.edges:
        if edge.source.startswith("__") or edge.target.startswith("__"):
            continue
        adjacency.setdefault(edge.source, []).append(edge.target)
    return kahn_topological_order(adjacency)


def test_classify_architecture_layers_after_compose_leaf_modules() -> None:
    order = _pipeline_execution_order()
    assert "compose_leaf_modules" in order
    assert "classify_architecture_layers" in order
    assert order.index("compose_leaf_modules") < order.index("classify_architecture_layers")


def test_classify_architecture_layers_before_graph_domain_decompose() -> None:
    order = _pipeline_execution_order()
    assert "classify_architecture_layers" in order
    assert "graph_domain_decompose" in order
    assert order.index("classify_architecture_layers") < order.index("graph_domain_decompose")


def test_compose_leaf_modules_routes_to_classify_architecture_layers() -> None:
    pipeline = build_wiki_pipeline(checkpointer=False)
    edges = pipeline.get_graph().edges
    assert any(
        e.source == "compose_leaf_modules" and e.target == "classify_architecture_layers"
        for e in edges
    )


def test_classify_architecture_layers_routes_to_graph_domain_decompose() -> None:
    pipeline = build_wiki_pipeline(checkpointer=False)
    edges = pipeline.get_graph().edges
    assert any(
        e.source == "classify_architecture_layers" and e.target == "graph_domain_decompose"
        for e in edges
    )


def test_classify_architecture_layers_phase_between_leaf_and_domain_decompose() -> None:
    leaf_pct = _NODE_PHASE_MAP["compose_leaf_modules"][1]
    arch_pct = _NODE_PHASE_MAP["classify_architecture_layers"][1]
    domain_pct = _NODE_PHASE_MAP["graph_domain_decompose"][1]
    assert leaf_pct < arch_pct < domain_pct
