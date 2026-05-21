from __future__ import annotations

from unittest.mock import patch

from wiki.graph_community_detector import GraphCommunityDetector, _ngram_similarity


def _node(repo: str, name: str) -> tuple[str, str]:
    return (repo, name)


class TestDetect:
    def test_empty_graph_returns_single_community(self):
        """Empty graph (no edges) with modules returns each module as its own community or one big one."""
        detector = GraphCommunityDetector(seed=42)
        nodes = [_node("repo1", "ModA"), _node("repo1", "ModB")]
        communities = detector.detect(nodes, [])
        assert len(communities) == 1
        assert {_node("repo1", "ModA"), _node("repo1", "ModB")} == communities[0]

    def test_empty_nodes_returns_empty(self):
        detector = GraphCommunityDetector(seed=42)
        assert detector.detect([], []) == []

    def test_two_disconnected_subgraphs_produce_two_communities(self):
        """Two fully disconnected clusters should produce at least 2 communities."""
        nodes = [
            _node("r", "A"),
            _node("r", "B"),
            _node("r", "C"),
            _node("r", "D"),
            _node("r", "E"),
            _node("r", "F"),
        ]
        edges = [
            (_node("r", "A"), _node("r", "B"), 5),
            (_node("r", "B"), _node("r", "C"), 5),
            (_node("r", "D"), _node("r", "E"), 5),
            (_node("r", "E"), _node("r", "F"), 5),
        ]
        detector = GraphCommunityDetector(target_min=2, target_max=10, seed=42)
        communities = detector.detect(nodes, edges)
        assert len(communities) >= 2
        comm_sets = [frozenset(c) for c in communities]
        cluster1 = {_node("r", "A"), _node("r", "B"), _node("r", "C")}
        cluster2 = {_node("r", "D"), _node("r", "E"), _node("r", "F")}
        assert any(cluster1 <= c for c in comm_sets)
        assert any(cluster2 <= c for c in comm_sets)

    def test_weighted_edges_influence_community_detection(self):
        """Higher weight edges should keep modules together."""
        group_a = [_node("r", "A0"), _node("r", "A1"), _node("r", "A2")]
        group_b = [_node("r", "B0"), _node("r", "B1"), _node("r", "B2")]
        nodes = group_a + group_b
        edges = [
            (group_a[i], group_a[j], 50)
            for i in range(3)
            for j in range(i + 1, 3)
        ] + [
            (group_b[i], group_b[j], 50)
            for i in range(3)
            for j in range(i + 1, 3)
        ] + [(_node("r", "A2"), _node("r", "B0"), 1)]
        detector = GraphCommunityDetector(target_min=1, target_max=10, seed=42)
        communities = detector.detect(nodes, edges)
        comm_sets = [frozenset(c) for c in communities]
        assert set(group_a) in comm_sets
        assert set(group_b) in comm_sets

    def test_adaptive_resolution_increases_when_too_few_communities(self):
        """When initial Louvain produces < target_min communities, resolution increases."""
        nodes: list[tuple[str, str]] = []
        edges: list[tuple[tuple[str, str], tuple[str, str], int]] = []
        clique_centers: list[tuple[str, str]] = []
        for group in range(5):
            group_nodes = [_node("r", f"G{group}N{i}") for i in range(3)]
            nodes.extend(group_nodes)
            clique_centers.append(group_nodes[0])
            for i in range(3):
                for j in range(i + 1, 3):
                    edges.append((group_nodes[i], group_nodes[j], 10))
        for i in range(4):
            edges.append((clique_centers[i], clique_centers[i + 1], 20))

        detector = GraphCommunityDetector(target_min=5, target_max=15, seed=42)

        with patch.object(detector, "_louvain_communities", wraps=detector._louvain_communities) as mock_louvain:
            communities = detector.detect(nodes, edges)
            resolutions = [call.kwargs.get("resolution", 1.0) for call in mock_louvain.call_args_list]
            assert any(r > 1.0 for r in resolutions)

        assert len(communities) >= 5

    def test_adaptive_resolution_decreases_when_too_many_communities(self):
        """When initial Louvain produces > target_max communities, resolution decreases."""
        # 20 isolated pairs → 20 micro-communities before merge; use star to get many communities
        nodes = [_node("r", f"N{i}") for i in range(20)]
        edges = [(_node("r", f"N{i}"), _node("r", f"N{i + 1}"), 1) for i in range(19)]
        detector = GraphCommunityDetector(target_min=2, target_max=3, seed=42)

        with patch.object(detector, "_louvain_communities", wraps=detector._louvain_communities) as mock_louvain:
            communities = detector.detect(nodes, edges)
            resolutions = [call.kwargs.get("resolution", 1.0) for call in mock_louvain.call_args_list]
            assert any(r < 1.0 for r in resolutions)

        assert len(communities) <= 3

    def test_micro_community_merged_to_nearest_neighbor(self):
        """Communities with ≤2 modules get merged into the community with most shared edges."""
        nodes = [
            _node("r", "BigA"),
            _node("r", "BigB"),
            _node("r", "BigC"),
            _node("r", "Tiny"),
        ]
        edges = [
            (_node("r", "BigA"), _node("r", "BigB"), 10),
            (_node("r", "BigB"), _node("r", "BigC"), 10),
            (_node("r", "BigA"), _node("r", "BigC"), 10),
            (_node("r", "Tiny"), _node("r", "BigA"), 5),
        ]
        detector = GraphCommunityDetector(target_min=1, target_max=10, seed=42)
        communities = detector.detect(nodes, edges)
        comm_sets = [frozenset(c) for c in communities]
        big_cluster = {_node("r", "BigA"), _node("r", "BigB"), _node("r", "BigC"), _node("r", "Tiny")}
        assert any(big_cluster <= c for c in comm_sets)

    def test_deterministic_with_same_seed(self):
        """Same input + same seed → same output."""
        nodes = [_node("r", f"X{i}") for i in range(8)]
        edges = [
            (_node("r", "X0"), _node("r", "X1"), 2),
            (_node("r", "X1"), _node("r", "X2"), 2),
            (_node("r", "X3"), _node("r", "X4"), 2),
            (_node("r", "X4"), _node("r", "X5"), 2),
        ]
        det1 = GraphCommunityDetector(seed=42)
        det2 = GraphCommunityDetector(seed=42)
        result1 = [frozenset(c) for c in det1.detect(nodes, edges)]
        result2 = [frozenset(c) for c in det2.detect(nodes, edges)]
        assert sorted(result1) == sorted(result2)

    def test_nodes_as_repo_module_tuples(self):
        """Nodes are (repo_id, module_name) tuples — cross-repo support."""
        nodes = [
            _node("repo-a", "Service"),
            _node("repo-b", "Client"),
            _node("repo-a", "Helper"),
        ]
        edges = [
            (_node("repo-a", "Service"), _node("repo-b", "Client"), 8),
            (_node("repo-a", "Service"), _node("repo-a", "Helper"), 8),
        ]
        detector = GraphCommunityDetector(target_min=1, target_max=10, seed=42)
        communities = detector.detect(nodes, edges)
        all_nodes = {n for c in communities for n in c}
        assert all_nodes == set(nodes)


class TestAssignIsolatedModules:
    def test_isolated_assigned_by_name_similarity(self):
        """Isolated module 'FamilyConfig' should join community containing 'FamilyService'."""
        detector = GraphCommunityDetector(seed=42)
        communities = [
            {_node("r", "FamilyService"), _node("r", "FamilyHandler")},
            {_node("r", "UserProfile"), _node("r", "UserAuth")},
        ]
        isolated = [_node("r", "FamilyConfig")]
        assignments = detector.assign_isolated_modules(isolated, communities, similarity_threshold=0.2)
        assert 0 in assignments
        assert _node("r", "FamilyConfig") in assignments[0]
        assert -1 not in assignments

    def test_all_below_threshold_goes_to_misc(self):
        """When no community has similarity >= threshold, module goes to misc (-1)."""
        detector = GraphCommunityDetector(seed=42)
        communities = [
            {_node("r", "AlphaModule")},
            {_node("r", "BetaModule")},
        ]
        isolated = [_node("r", "XyzQrs")]
        assignments = detector.assign_isolated_modules(isolated, communities, similarity_threshold=0.2)
        assert -1 in assignments
        assert _node("r", "XyzQrs") in assignments[-1]

    def test_empty_isolated_list_returns_empty(self):
        """No isolated modules → empty result."""
        detector = GraphCommunityDetector(seed=42)
        communities = [{_node("r", "A")}]
        assert detector.assign_isolated_modules([], communities) == {}


class TestDetectSubCommunities:
    def test_small_community_not_split(self):
        """Community with ≤ max_leaf_size modules is not split."""
        detector = GraphCommunityDetector(seed=42)
        nodes = {_node("r", f"S{i}") for i in range(5)}
        edges = [
            (_node("r", "S0"), _node("r", "S1"), 1),
            (_node("r", "S1"), _node("r", "S2"), 1),
        ]
        result = detector.detect_sub_communities(nodes, edges, max_leaf_size=8)
        assert len(result) == 1
        assert len(result[0]["modules"]) == 5
        assert result[0]["children"] == []

    def test_large_community_split_recursively(self):
        """Community with > max_leaf_size modules gets split."""
        detector = GraphCommunityDetector(seed=42)
        # Two dense sub-clusters connected by a weak bridge
        group_a = [_node("r", f"A{i}") for i in range(6)]
        group_b = [_node("r", f"B{i}") for i in range(6)]
        nodes = set(group_a + group_b)
        edges: list[tuple[tuple[str, str], tuple[str, str], int]] = []
        for i in range(6):
            for j in range(i + 1, 6):
                edges.append((_node("r", f"A{i}"), _node("r", f"A{j}"), 10))
                edges.append((_node("r", f"B{i}"), _node("r", f"B{j}"), 10))
        edges.append((_node("r", "A0"), _node("r", "B0"), 1))
        result = detector.detect_sub_communities(nodes, edges, max_leaf_size=8, max_depth=3)
        assert len(result) == 1
        root = result[0]
        assert len(root["modules"]) == 12
        assert root["children"]
        child_module_count = sum(len(child["modules"]) for child in root["children"])
        assert child_module_count == 12

    def test_high_density_community_not_split(self):
        """Community with edge_density > 0.5 is not split even if large."""
        detector = GraphCommunityDetector(seed=42)
        nodes = {_node("r", f"D{i}") for i in range(10)}
        # Complete graph → density = 1.0
        edges = [
            (_node("r", f"D{i}"), _node("r", f"D{j}"), 1)
            for i in range(10)
            for j in range(i + 1, 10)
        ]
        result = detector.detect_sub_communities(nodes, edges, max_leaf_size=8, max_depth=3)
        assert len(result) == 1
        assert result[0]["children"] == []
        assert len(result[0]["modules"]) == 10

    def test_max_depth_stops_recursion(self):
        """Recursion stops at max_depth."""
        detector = GraphCommunityDetector(seed=42)
        group_a = [_node("r", f"X{i}") for i in range(6)]
        group_b = [_node("r", f"Y{i}") for i in range(6)]
        nodes = set(group_a + group_b)
        edges: list[tuple[tuple[str, str], tuple[str, str], int]] = []
        for i in range(5):
            edges.append((_node("r", f"X{i}"), _node("r", f"X{i + 1}"), 10))
            edges.append((_node("r", f"Y{i}"), _node("r", f"Y{i + 1}"), 10))
        edges.append((_node("r", "X0"), _node("r", "Y0"), 1))

        def _max_depth(node: dict, depth: int = 0) -> int:
            if not node.get("children"):
                return depth
            return max(_max_depth(child, depth + 1) for child in node["children"])

        result = detector.detect_sub_communities(nodes, edges, max_leaf_size=4, max_depth=1)
        max_tree_depth = max(_max_depth(r) for r in result)
        assert max_tree_depth <= 1

    def test_louvain_single_community_stops(self):
        """If Louvain can't split further, recursion stops."""
        detector = GraphCommunityDetector(seed=42)
        # Sparse chain — Louvain may not split meaningfully at small size
        nodes = {_node("r", f"L{i}") for i in range(10)}
        edges = [(_node("r", f"L{i}"), _node("r", f"L{i + 1}"), 1) for i in range(9)]
        # Low density chain, but Louvain at r=1.0 often yields 1 community for a path
        with patch.object(detector, "_louvain_communities", return_value=[nodes]):
            result = detector.detect_sub_communities(
                nodes,
                edges,
                max_leaf_size=4,
                max_depth=3,
            )
        assert len(result) == 1
        assert result[0]["children"] == []


class TestNgramSimilarity:
    def test_similar_names_score_high(self):
        assert _ngram_similarity("FamilyService", "FamilyConfig") > 0.2

    def test_dissimilar_names_score_low(self):
        assert _ngram_similarity("Alpha", "Beta") < 0.2
