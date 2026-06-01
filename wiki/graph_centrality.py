"""Graph centrality helpers for wiki domain clustering."""
from __future__ import annotations

import networkx as nx

from core.log import get_logger

log = get_logger(__name__)

Node = tuple[str, str]
Edge = tuple[Node, Node, float]


def compute_hub_weights(
    modules: list[tuple[str, str]],
    edges: list[tuple[tuple[str, str], tuple[str, str], float]],
    *,
    hub_threshold: float = 0.15,
) -> dict[tuple[str, str], float]:
    """Compute betweenness centrality and return hub attenuation factors.

    Returns dict mapping module node → attenuation factor in [0.0, 1.0].
    Non-hub modules get 1.0 (no attenuation).
    Hub modules get values < 1.0 proportional to their centrality.
    """
    if not edges:
        return {}

    graph = nx.Graph()
    for module in modules:
        graph.add_node(module)
    for src, dst, weight in edges:
        if src not in graph or dst not in graph:
            continue
        abs_weight = abs(float(weight))
        if graph.has_edge(src, dst):
            existing = graph[src][dst].get("weight", 0.0)
            graph[src][dst]["weight"] = max(existing, abs_weight)
        else:
            graph.add_edge(src, dst, weight=max(abs_weight, 1e-10))

    betweenness = nx.betweenness_centrality(graph, weight="weight", normalized=True)
    hub_weights: dict[tuple[str, str], float] = {}
    for module in modules:
        normalized = betweenness.get(module, 0.0)
        attenuation = 1.0 - min(normalized / hub_threshold, 1.0) * 0.7
        hub_weights[module] = attenuation

    log.debug(
        "hub_weights_computed",
        n_modules=len(modules),
        n_hubs=sum(1 for w in hub_weights.values() if w < 1.0),
    )
    return hub_weights
