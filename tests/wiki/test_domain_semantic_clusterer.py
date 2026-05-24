"""Tests for DomainSemanticClusterer."""

import numpy as np
import pytest

from wiki.domain_semantic_clusterer import DomainSemanticClusterer


class TestDistanceMatrix:
    def test_cosine_distance_identical_vectors(self):
        embeddings = np.array([[1.0, 0.0], [1.0, 0.0]])
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_cosine_distance(embeddings)
        assert dist[0, 1] == pytest.approx(0.0, abs=1e-6)

    def test_cosine_distance_orthogonal_vectors(self):
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_cosine_distance(embeddings)
        assert dist[0, 1] == pytest.approx(1.0, abs=1e-6)

    def test_call_graph_discount(self):
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        modules = [("repo", "A"), ("repo", "B"), ("repo", "C")]
        edges = [(("repo", "A"), ("repo", "B"), 1)]
        clusterer = DomainSemanticClusterer(call_graph_discount=0.85)
        dist = clusterer._compute_distance_matrix(embeddings, modules, edges)
        # A-B should have discounted distance
        assert dist[0, 1] < dist[0, 2]
        assert dist[0, 1] == pytest.approx(dist[0, 2] * 0.85, abs=0.01)
        # Discount is symmetric
        assert dist[0, 1] == pytest.approx(dist[1, 0], abs=1e-6)

    def test_discount_constructor_param_affects_distance(self):
        """call_graph_discount constructor param must affect distance matrix, not hardcoded 0.15."""
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        modules = [("repo", "A"), ("repo", "B"), ("repo", "C")]
        edges = [(("repo", "A"), ("repo", "B"), 1)]
        default_clusterer = DomainSemanticClusterer(call_graph_discount=0.85)
        custom_clusterer = DomainSemanticClusterer(call_graph_discount=0.7)
        default_dist = default_clusterer._compute_distance_matrix(embeddings, modules, edges)
        custom_dist = custom_clusterer._compute_distance_matrix(embeddings, modules, edges)
        # Base distance is 1.0; with max weight ratio=1: default → 0.85, custom → 0.7
        assert default_dist[0, 1] == pytest.approx(0.85, abs=0.01)
        assert custom_dist[0, 1] == pytest.approx(0.7, abs=0.01)
        assert custom_dist[0, 1] < default_dist[0, 1]

    def test_weight_aware_discount_high_weight(self):
        """High-weight edge should get stronger discount than low-weight."""
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        modules = [("repo", "A"), ("repo", "B"), ("repo", "C")]
        # A-B has weight 50 (high), A-C has weight 1 (low)
        edges = [
            (("repo", "A"), ("repo", "B"), 50),
            (("repo", "A"), ("repo", "C"), 1),
        ]
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_distance_matrix(embeddings, modules, edges)
        # High-weight edge A-B should be more discounted (smaller distance) than A-C
        assert dist[0, 1] < dist[0, 2]
        # Both should still be discounted from base distance (1.0)
        assert dist[0, 1] < 1.0
        assert dist[0, 2] < 1.0
        # Symmetric
        assert dist[0, 1] == pytest.approx(dist[1, 0], abs=1e-6)

    def test_weight_aware_discount_equal_weight(self):
        """Equal-weight edges should get equal discount."""
        embeddings = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]])
        modules = [("repo", "A"), ("repo", "B"), ("repo", "C")]
        edges = [
            (("repo", "A"), ("repo", "B"), 10),
            (("repo", "A"), ("repo", "C"), 10),
        ]
        clusterer = DomainSemanticClusterer()
        dist = clusterer._compute_distance_matrix(embeddings, modules, edges)
        assert dist[0, 1] == pytest.approx(dist[0, 2], abs=1e-6)


class TestClustering:
    def test_cluster_returns_sets_of_modules(self):
        # 12 modules in 2 clear groups (similar embeddings), N >= 10
        embeddings = np.array([
            [1.0, 0.0], [0.95, 0.05], [0.9, 0.1],
            [0.85, 0.15], [0.8, 0.2], [0.75, 0.25],
            [0.0, 1.0], [0.05, 0.95], [0.1, 0.9],
            [0.15, 0.85], [0.2, 0.8], [0.25, 0.75],
        ])
        modules = [("r", f"M{i}") for i in range(12)]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) >= 2
        all_mods = set()
        for c in clusters:
            all_mods.update(c)
        assert all_mods == set(modules)

    def test_small_n_returns_single_cluster(self):
        # N < 3 → single cluster (threshold lowered from 10 to 3)
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        modules = [("r", "A"), ("r", "B")]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_n_below_threshold_returns_single_cluster(self):
        # N=2 < 3 → single cluster
        embeddings = np.array([[1.0, 0.0], [0.0, 1.0]])
        modules = [("r", "A"), ("r", "B")]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) == 1
        assert len(clusters[0]) == 2

    def test_medium_n_cluster_two_groups(self):
        # N=6 with 2 distinct groups → should cluster, NOT single cluster
        embeddings = np.array([
            [1.0, 0.0], [0.9, 0.1], [0.8, 0.2],
            [0.0, 1.0], [0.1, 0.9], [0.2, 0.8],
        ])
        modules = [("r", f"M{i}") for i in range(6)]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) >= 2
        all_mods = set()
        for c in clusters:
            all_mods.update(c)
        assert all_mods == set(modules)

    def test_n_three_cluster_with_distinct_groups(self):
        # N=3 with 2 distinct groups → should cluster into 2
        embeddings = np.array([
            [1.0, 0.0],
            [0.0, 1.0],
            [0.05, 0.95],
        ])
        modules = [("r", "A"), ("r", "B"), ("r", "C")]
        clusterer = DomainSemanticClusterer()
        clusters = clusterer.cluster(embeddings, modules, edges=[])
        assert len(clusters) >= 2


class TestBuildEmbeddingTexts:
    def test_with_summary(self):
        modules = [("repo", "IntimacyService")]
        summaries = {"IntimacyService": {"summary_text": "亲密关系核心服务"}}
        paths = {"IntimacyService": "intimacy/service/IntimacyService.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "IntimacyService" in texts[0]
        assert "亲密关系核心服务" in texts[0]
        assert "intimacy/service" in texts[0]

    def test_without_summary_fallback(self):
        modules = [("repo", "FooHandler")]
        summaries = {}
        paths = {"FooHandler": "foo/handler/FooHandler.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "FooHandler" in texts[0]
        assert "foo/handler" in texts[0]

    def test_path_keeps_four_levels(self):
        """Default shorten_path should keep 4 directory levels, not 2."""
        modules = [("repo", "UserService")]
        summaries = {"UserService": {"summary_text": "用户服务"}}
        paths = {"UserService": "com/example/biz/user/service/UserService.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        # Should contain 4 levels: example/biz/user/service
        assert "example/biz/user/service" in texts[0]
        # Should NOT be truncated to just 2 levels
        assert "user/service" in texts[0]

    def test_with_methods_and_docstring(self):
        """Embedding text should include method signatures and docstring when available."""
        modules = [("repo", "FamilyService")]
        summaries = {
            "FamilyService": {
                "summary_text": "家族系统核心服务",
                "methods": ["createFamily", "joinFamily", "disbandFamily"],
                "docstring": "Manage family group lifecycle.",
            }
        }
        paths = {"FamilyService": "family/service/FamilyService.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "FamilyService" in texts[0]
        assert "家族系统核心服务" in texts[0]
        assert "createFamily" in texts[0]
        assert "joinFamily" in texts[0]

    def test_empty_summary_fallback_uses_methods(self):
        """When summary_text is empty, use method names as fallback."""
        modules = [("repo", "GuildManager")]
        summaries = {
            "GuildManager": {
                "summary_text": "",
                "methods": ["addMember", "removeMember", "getGuildInfo"],
            }
        }
        paths = {"GuildManager": "guild/manager/GuildManager.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "GuildManager" in texts[0]
        assert "addMember" in texts[0]
        assert "removeMember" in texts[0]

    def test_build_embedding_texts_reads_key_methods(self):
        """compose_leaf_modules returns key_methods, not methods — both must work."""
        modules = [("repo", "OrderService")]
        summaries = {
            "OrderService": {
                "summary_text": "订单处理服务",
                "key_methods": ["createOrder", "cancelOrder", "refundOrder"],
            }
        }
        paths = {"OrderService": "order/service/OrderService.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "createOrder" in texts[0]
        assert "cancelOrder" in texts[0]
        assert "refundOrder" in texts[0]

    def test_build_embedding_texts_includes_dependencies_and_callers(self):
        """dependencies and callers from compose summaries should enrich embedding text."""
        modules = [("repo", "PaymentGateway")]
        summaries = {
            "PaymentGateway": {
                "summary_text": "支付网关",
                "dependencies": ["OrderService", "UserService", "ConfigLoader"],
                "callers": ["CheckoutController", "RefundHandler"],
            }
        }
        paths = {"PaymentGateway": "payment/gateway/PaymentGateway.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        assert "depends: OrderService, UserService, ConfigLoader" in texts[0]
        assert "callers: CheckoutController, RefundHandler" in texts[0]


class TestShortenPath:
    def test_default_keeps_four_levels(self):
        from wiki.domain_semantic_clusterer import _shorten_path
        result = _shorten_path("com/example/biz/user/service/UserService.java")
        assert "example/biz/user/service" in result

    def test_short_path_unchanged(self):
        from wiki.domain_semantic_clusterer import _shorten_path
        result = _shorten_path("user/service/UserService.java")
        assert "user/service" in result

    def test_custom_levels(self):
        from wiki.domain_semantic_clusterer import _shorten_path
        result = _shorten_path("a/b/c/d/e/f/G.java", levels=2)
        assert result == "e/f"
