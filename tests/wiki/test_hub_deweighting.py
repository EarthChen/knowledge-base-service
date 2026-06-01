"""Tests for hub/bridge module de-weighting via betweenness centrality."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest

from wiki.domain_semantic_clusterer import DomainSemanticClusterer
from wiki.graph_centrality import compute_hub_weights

REPO = "repo"


def _mod(name: str) -> tuple[str, str]:
    return (REPO, name)


class TestComputeHubWeights:
    def test_compute_hub_weights_identifies_hub(self):
        hub = _mod("EventBus")
        leaves = [_mod(f"Leaf{i}") for i in range(4)]
        modules = [hub, *leaves]
        edges = [(hub, leaf, 10.0) for leaf in leaves]

        weights = compute_hub_weights(modules, edges)

        assert weights[hub] < 1.0
        assert weights[hub] >= 0.3  # max 70% attenuation → floor 0.3

    def test_compute_hub_weights_non_hub_stays_1(self):
        hub = _mod("EventBus")
        leaf = _mod("OrderService")
        modules = [hub, leaf]
        edges = [(hub, leaf, 5.0)]

        weights = compute_hub_weights(modules, edges)

        assert weights[leaf] == pytest.approx(1.0)

    def test_compute_hub_weights_empty_edges(self):
        modules = [_mod("A"), _mod("B")]
        weights = compute_hub_weights(modules, [])
        assert weights == {}


class TestHubDeweightingClustering:
    def test_hub_deweighting_reduces_cluster_pull(self):
        """Hub attenuation should weaken call-graph edge discounts on hub-spoke pairs."""
        hub = _mod("Hub")
        group_a = [_mod("AlphaOne"), _mod("AlphaTwo")]
        group_b = [_mod("BetaOne"), _mod("BetaTwo")]
        modules = [hub, *group_a, *group_b]

        embeddings = np.array(
            [
                [0.5, 0.5, 0.0],  # hub — between groups
                [1.0, 0.0, 0.0],
                [0.95, 0.05, 0.0],
                [0.0, 1.0, 0.0],
                [0.05, 0.95, 0.0],
            ],
            dtype=np.float32,
        )
        edges = [(hub, mod, 100.0) for mod in group_a + group_b]

        clusterer = DomainSemanticClusterer(call_graph_discount=0.85)
        hub_weights = compute_hub_weights(modules, edges)
        base_dist = clusterer._compute_cosine_distance(embeddings)

        dist_no_hub = clusterer._compute_distance_matrix(
            embeddings, modules, edges, hub_weights=None
        )
        dist_with_hub = clusterer._compute_distance_matrix(
            embeddings, modules, edges, hub_weights=hub_weights
        )

        hub_idx = 0
        for spoke_idx in range(1, len(modules)):
            base = base_dist[hub_idx, spoke_idx]
            no_atten = dist_no_hub[hub_idx, spoke_idx]
            with_atten = dist_with_hub[hub_idx, spoke_idx]

            # Hub de-weighting moves hub-spoke distance closer to semantic baseline
            assert with_atten > no_atten
            assert with_atten <= base
            assert (base - with_atten) < (base - no_atten)

        assert hub_weights[hub] < 1.0

    def test_hub_weights_passed_through_cluster(self):
        embeddings = np.array(
            [[1.0, 0.0], [0.0, 1.0], [0.1, 0.9]],
            dtype=np.float32,
        )
        modules = [_mod("A"), _mod("B"), _mod("C")]
        edges = [(modules[0], modules[2], 10.0)]
        hub_weights = {_mod("A"): 0.5}

        clusterer = DomainSemanticClusterer()
        with patch.object(
            clusterer,
            "_compute_distance_matrix",
            wraps=clusterer._compute_distance_matrix,
        ) as mock_dist:
            clusterer.cluster(
                embeddings,
                modules,
                edges,
                hub_weights=hub_weights,
                enable_prefix_cannot_link=False,
            )
            mock_dist.assert_called_once()
            _, kwargs = mock_dist.call_args
            assert kwargs.get("hub_weights") == hub_weights
