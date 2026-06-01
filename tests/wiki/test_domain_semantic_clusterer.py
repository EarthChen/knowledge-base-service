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
        """dependencies and callers from compose summaries should enrich embedding text.
        With 1 module, infra threshold=max(3, ceil(1*0.1))=3 → all deps/callers count=1 < 3,
        but threshold is >= (appears in >= threshold modules is infra), so 1 < 3 means NOT infra.
        Wait — test needs update: with 1 module, threshold=3, each dep appears in 1 module,
        1 < 3 → NOT infra → deps should be kept.
        """
        # Need more modules so deps aren't all filtered.
        # Use 10 modules where target deps appear in only 1 → kept.
        modules = [("repo", "PaymentGateway")] + [("repo", f"Other{i}") for i in range(9)]
        summaries = {
            "PaymentGateway": {
                "summary_text": "支付网关",
                "dependencies": ["OrderService", "UserService", "ConfigLoader"],
                "callers": ["CheckoutController", "RefundHandler"],
            }
        }
        for i in range(9):
            summaries[f"Other{i}"] = {"summary_text": f"其他模块{i}"}
        paths = {"PaymentGateway": "payment/gateway/PaymentGateway.java"}
        paths.update({f"Other{i}": f"other{i}/Other{i}.java" for i in range(9)})
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 10
        pg_text = texts[0]
        assert "depends: OrderService, UserService, ConfigLoader" in pg_text
        assert "callers: CheckoutController, RefundHandler" in pg_text


class TestInfraFiltering:
    """Frequency-based filtering of shared infrastructure from depends/callers."""

    def test_high_frequency_dep_filtered(self):
        """Dependencies appearing in >= threshold modules should be filtered as infra."""
        # 15 modules: threshold = max(3, ceil(15*0.1)) = 3
        # RedisSelectDao appears in 5 modules' depends → infra → filtered
        # FamilyMemberService appears in 2 modules' depends → kept
        modules = [("repo", f"Mod{i}") for i in range(15)]
        summaries = {}
        for i in range(5):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "dependencies": ["RedisSelectDao", "FamilyMemberService"] if i < 2 else ["RedisSelectDao"],
            }
        for i in range(5, 15):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "dependencies": ["SomeOtherDep"],
            }
        paths = {f"Mod{i}": f"mod{i}/Mod{i}.java" for i in range(15)}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        # RedisSelectDao (5 >= 3) → filtered
        for text in texts:
            assert "RedisSelectDao" not in text
        # FamilyMemberService (2 < 3) → kept in Mod0-1
        for i in range(2):
            assert "FamilyMemberService" in texts[i]

    def test_high_frequency_caller_filtered(self):
        """Callers appearing in >= threshold modules should be filtered as infra."""
        # 20 modules: threshold = max(3, ceil(20*0.1)) = 3
        # DataResponse appears as caller in 6 modules → infra → filtered
        # IntimacyController appears in 2 modules → kept
        modules = [("repo", f"Mod{i}") for i in range(20)]
        summaries = {}
        for i in range(6):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "callers": ["DataResponse", "IntimacyController"] if i < 2 else ["DataResponse"],
            }
        for i in range(6, 20):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "callers": ["OtherCaller"],
            }
        paths = {f"Mod{i}": f"mod{i}/Mod{i}.java" for i in range(20)}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        # DataResponse (6 >= 3) → filtered
        for text in texts:
            assert "DataResponse" not in text
        # IntimacyController (2 < 3) → kept in Mod0-1
        for i in range(2):
            assert "IntimacyController" in texts[i]

    def test_all_deps_unique_no_filtering(self):
        """When all deps are unique (each appears once), nothing should be filtered."""
        # 20 modules, each with unique deps → threshold=3, each dep count=1 < 3
        modules = [("repo", f"Mod{i}") for i in range(20)]
        summaries = {
            f"Mod{i}": {
                "summary_text": f"模块{i}",
                "dependencies": [f"UniqueDep{i}A", f"UniqueDep{i}B"],
            }
            for i in range(20)
        }
        paths = {f"Mod{i}": f"mod{i}/Mod{i}.java" for i in range(20)}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        for i in range(20):
            assert f"UniqueDep{i}A" in texts[i]
            assert f"UniqueDep{i}B" in texts[i]

    def test_single_module_filters_everything(self):
        """With 1 module, threshold=max(3,1)=3, all deps/callers count=1 < 3 → kept (not infra)."""
        modules = [("repo", "OnlyModule")]
        summaries = {
            "OnlyModule": {
                "summary_text": "唯一的模块",
                "dependencies": ["DepA", "DepB", "DepC"],
                "callers": ["CallerX"],
            }
        }
        paths = {"OnlyModule": "only/OnlyModule.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 1
        # With 1 module each dep/caller appears once, threshold=3, 1 < 3 → NOT infra → kept
        assert "DepA" in texts[0]
        assert "DepC" in texts[0]
        assert "CallerX" in texts[0]
        assert "唯一的模块" in texts[0]

    def test_mixed_dep_frequencies(self):
        """Only deps exceeding threshold are filtered; others preserved."""
        # 30 modules: threshold = max(3, ceil(30*0.1)) = 3
        # MultiLangProxy in 8 modules → filtered
        # GiftOrderService in 2 modules → kept
        # ChatMessageRouter in 1 module → kept
        modules = [("repo", f"Mod{i}") for i in range(30)]
        summaries = {}
        for i in range(8):
            dep = ["MultiLangProxy", "GiftOrderService"] if i < 2 else ["MultiLangProxy"]
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "dependencies": dep,
            }
        for i in range(8, 10):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "dependencies": ["ChatMessageRouter"] if i == 8 else ["RandomDep"],
            }
        for i in range(10, 30):
            summaries[f"Mod{i}"] = {
                "summary_text": f"模块{i}",
                "dependencies": ["RandomDep"],
            }
        paths = {f"Mod{i}": f"mod{i}/Mod{i}.java" for i in range(30)}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        # MultiLangProxy (8 >= 3) → filtered everywhere
        for text in texts:
            assert "MultiLangProxy" not in text
        # GiftOrderService (2 < 3) → kept in Mod0-1
        for i in range(2):
            assert "GiftOrderService" in texts[i]
        # ChatMessageRouter (1 < 3) → kept in Mod8
        assert "ChatMessageRouter" in texts[8]

    def test_no_summary_data_still_works(self):
        """Modules without summary data should not crash infra filtering."""
        modules = [("repo", "ModA"), ("repo", "ModB")]
        summaries = {}
        paths = {"ModA": "a/ModA.java", "ModB": "b/ModB.java"}
        texts = DomainSemanticClusterer.build_embedding_texts(modules, summaries, paths)
        assert len(texts) == 2
        assert "ModA" in texts[0]
        assert "ModB" in texts[1]


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


class TestExtractBusinessPrefix:
    def test_kebab_case_strips_relation_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("relation-family-service", None) == "family"

    def test_kebab_case_strips_user_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("user-wealth-dao", None) == "wealth"

    def test_kebab_case_no_common_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("guild-artist-consumer", None) == "guild"

    def test_camelcase_extracts_first_business_word(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("FamilyChestService", None) == "family"

    def test_camelcase_skips_interface_prefix(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("IFamilyService", None) == "family"

    def test_uses_path_slug_when_available(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert (
            _extract_business_prefix(
                "FamilyChestService",
                "ultron/ultron-relation/relation-family-chest-service",
            )
            == "family"
        )

    def test_returns_none_for_generic_names(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("BaseService", None) is None

    def test_returns_none_for_empty_string(self):
        from wiki.domain_semantic_clusterer import _extract_business_prefix

        assert _extract_business_prefix("", None) is None


class TestApplyPrefixPenalty:
    def test_same_prefix_unchanged(self):
        dist = np.array([[0.0, 0.5], [0.5, 0.0]])
        modules = [("repo", "relation-family-service"), ("repo", "relation-family-dao")]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths)
        np.testing.assert_array_almost_equal(result, dist)

    def test_different_prefix_increases_distance(self):
        dist = np.array([[0.0, 0.5, 0.5], [0.5, 0.0, 0.5], [0.5, 0.5, 0.0]])
        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-intimacy-task-service"),
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths, penalty_factor=1.5)
        # family-family pair unchanged
        assert result[0, 1] == pytest.approx(0.5, abs=1e-6)
        # family-intimacy pair penalized
        assert result[0, 2] == pytest.approx(0.75, abs=1e-6)
        assert result[1, 2] == pytest.approx(0.75, abs=1e-6)

    def test_no_prefix_no_penalty(self):
        dist = np.array([[0.0, 0.5], [0.5, 0.0]])
        modules = [("repo", "BaseService"), ("repo", "relation-family-service")]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_penalty(dist.copy(), modules, paths, penalty_factor=1.5)
        # BaseService has no prefix → no penalty applied
        np.testing.assert_array_almost_equal(result, dist)


class TestPrefixCannotLink:
    def test_different_prefix_gets_max_distance(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.1, 0.3], [0.1, 0.0, 0.2], [0.3, 0.2, 0.0]])
        modules = [("repo", "FamilyChestService"), ("repo", "IntimacyTaskService"), ("repo", "FamilyMemberDao")]
        paths = {
            "repo|FamilyChestService": "com/family/chest",
            "repo|IntimacyTaskService": "com/intimacy/task",
            "repo|FamilyMemberDao": "com/family/member",
        }
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_cannot_link(dist.copy(), modules, paths)
        # family vs intimacy → 2.0
        assert result[0, 1] == pytest.approx(2.0)
        assert result[1, 0] == pytest.approx(2.0)
        assert result[1, 2] == pytest.approx(2.0)
        # family vs family → unchanged
        assert result[0, 2] == pytest.approx(0.3)

    def test_no_prefix_modules_unchanged(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.5], [0.5, 0.0]])
        modules = [("repo", "BaseService"), ("repo", "CommonUtil")]
        paths = {"repo|BaseService": "com/base", "repo|CommonUtil": "com/util"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_cannot_link(dist.copy(), modules, paths)
        # No recognizable prefix → unchanged
        assert result[0, 1] == pytest.approx(0.5)

    def test_prefix_cannot_link_bare_name_path_fallback(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("repo", "ServiceA"), ("repo", "ServiceB")]
        # Paths keyed by bare name (no compound key); prefixes only derivable from path slugs
        paths = {"ServiceA": "com/pkg/family-core", "ServiceB": "com/pkg/intimacy-core"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_prefix_cannot_link(dist.copy(), modules, paths)
        assert result[0, 1] == pytest.approx(2.0)

    def test_config_flag_controls_cannot_link(self):
        from core.config import AppWikiFlags

        flags = AppWikiFlags()
        assert flags.enable_prefix_cannot_link is True
        assert flags.cluster_prefix_penalty_factor == 2.0


class TestReviewClusterPlacement:
    def test_misplaced_module_reparented(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-intimacy-task-service"),
            ("repo", "relation-intimacy-online-service"),
            ("repo", "relation-family-task-handler"),
        ]
        clusters = [
            {("repo", "relation-family-service"), ("repo", "relation-family-dao")},
            {
                ("repo", "relation-intimacy-task-service"),
                ("repo", "relation-intimacy-online-service"),
                ("repo", "relation-family-task-handler"),
            },
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        # family-task-handler should be reparented to cluster 0 (family-dominant)
        assert ("repo", "relation-family-task-handler") in result[0]
        assert ("repo", "relation-family-task-handler") not in result[1]

    def test_no_prefix_module_stays(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "BaseUtils"),
        ]
        clusters = [
            {("repo", "relation-family-service"), ("repo", "BaseUtils")},
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        assert ("repo", "BaseUtils") in result[0]

    def test_single_module_stays_if_no_target_cluster(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [
            ("repo", "relation-family-service"),
            ("repo", "relation-family-dao"),
            ("repo", "relation-guild-consumer"),
        ]
        clusters = [
            {
                ("repo", "relation-family-service"),
                ("repo", "relation-family-dao"),
                ("repo", "relation-guild-consumer"),
            },
        ]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        # guild-consumer has no matching cluster → stays
        assert ("repo", "relation-guild-consumer") in result[0]

    def test_single_cluster_returns_unchanged(self):
        from wiki.domain_semantic_clusterer import DomainSemanticClusterer

        modules = [("repo", "relation-family-service")]
        clusters = [{("repo", "relation-family-service")}]
        paths = {}
        clusterer = DomainSemanticClusterer()
        result = clusterer._review_cluster_placement(clusters, modules, paths)
        assert result == clusters


class TestAnchorConstraints:
    def test_different_anchor_domains_cannot_link(self):
        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("repo", "ModA"), ("repo", "ModB")]
        pinned = {("repo", "ModA"): "domain-x", ("repo", "ModB"): "domain-y"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, pinned)
        assert result[0, 1] == pytest.approx(2.0)
        assert result[1, 0] == pytest.approx(2.0)

    def test_same_anchor_domain_unchanged(self):
        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("repo", "ModA"), ("repo", "ModB")]
        pinned = {("repo", "ModA"): "domain-x", ("repo", "ModB"): "domain-x"}
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, pinned)
        assert result[0, 1] == pytest.approx(0.3, abs=1e-6)

    def test_unpinned_modules_unchanged(self):
        dist = np.array([[0.0, 0.5, 0.3], [0.5, 0.0, 0.4], [0.3, 0.4, 0.0]])
        modules = [("r", "A"), ("r", "B"), ("r", "C")]
        pinned = {("r", "A"): "domain-x"}  # Only A is pinned
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, pinned)
        # B and C are unpinned, so dist[1,2] unchanged
        assert result[1, 2] == pytest.approx(0.4, abs=1e-6)
        # A vs B: A pinned, B not pinned → unchanged
        assert result[0, 1] == pytest.approx(0.5, abs=1e-6)

    def test_empty_pinned_returns_unchanged(self):
        dist = np.array([[0.0, 0.3], [0.3, 0.0]])
        modules = [("r", "A"), ("r", "B")]
        clusterer = DomainSemanticClusterer()
        result = clusterer._apply_anchor_constraints(dist.copy(), modules, {})
        assert np.array_equal(result, dist)


def test_cluster_sub_domains_applies_cannot_link():
    """Sub-domain clustering should respect prefix cannot-link."""
    clusterer = DomainSemanticClusterer()
    modules = [
        ("repo", "FamilyA"),
        ("repo", "FamilyB"),
        ("repo", "FamilyC"),
        ("repo", "IntimacyX"),
        ("repo", "IntimacyY"),
        ("repo", "IntimacyZ"),
    ]
    np.random.seed(42)
    embeddings = np.random.rand(6, 10)
    paths = {
        "repo|FamilyA": "com/family/a",
        "repo|FamilyB": "com/family/b",
        "repo|FamilyC": "com/family/c",
        "repo|IntimacyX": "com/intimacy/x",
        "repo|IntimacyY": "com/intimacy/y",
        "repo|IntimacyZ": "com/intimacy/z",
    }

    # With cannot-link, family and intimacy should NOT merge
    result = clusterer.cluster_sub_domains(
        modules=modules,
        embeddings=embeddings,
        edges=[],
        paths=paths,
        enable_prefix_cannot_link=True,
    )
    # Should have at least 2 clusters (family separate from intimacy)
    assert len(result) >= 2
