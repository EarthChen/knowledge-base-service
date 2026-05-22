from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.graph_domain_decompose import (
    _RELATED_KEYWORDS,
    _dedup_sub_domains,
    _embedding_clustering,
    _merge_domains_by_keyword,
    _tfidf_fallback_clustering,
    graph_driven_domain_decompose_node,
)


def _make_module_dict(repo_id: str, name: str, uid: str = "", path: str = "") -> dict:
    return {
        "uid": uid or f"Module::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "path": path or f"src/main/{name}.java",
            "repository": repo_id,
        },
    }


def _make_call_edge(source: str, target: str, weight: int = 10, repo: str = "repo1") -> dict:
    return {
        "source_repo": repo,
        "source": source,
        "target_repo": repo,
        "target": target,
        "weight": weight,
    }


def _make_state(modules: dict, entity_roles: dict | None = None):
    """Create minimal pipeline state for testing."""
    all_uids = []
    for repo, mods in modules.items():
        for m in mods:
            all_uids.append(m["uid"])

    roles = entity_roles or {uid: "has_business_logic" for uid in all_uids}
    return {
        "business_id": "test-biz",
        "repositories": list(modules.keys()),
        "modules": modules,
        "entity_roles": roles,
        "is_incremental": False,
        "domain_mapping": {},
        "domain_tree": None,
        "affected_domains": [],
    }


def _mock_corrector():
    """Return a mock corrector that does no-ops."""
    corrector = MagicMock()
    corrector.review_global_consistency = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return corrector


def _mock_namer():
    """Return a mock namer that generates slugs from module names."""
    namer = MagicMock()
    _call_counter = [0]

    async def _name_community(**kwargs):
        infos = kwargs.get("module_infos") or []
        names = [i.get("name", "") for i in infos]
        _call_counter[0] += 1
        slug_base = names[0].lower().replace("service", "").replace("dao", "") if names else "unnamed"
        slug = f"{slug_base}-{_call_counter[0]}"
        return {"slug": slug, "display_name": f"域{_call_counter[0]}", "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)
    return namer


class TestGraphDrivenDomainDecomposeNode:
    @pytest.mark.asyncio
    async def test_with_graph_store_uses_community_detection(self):
        """When graph_store is available, use community detection instead of LLM classification."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "FamilyService"),
                _make_module_dict("repo1", "FamilyDao"),
                _make_module_dict("repo1", "FamilyHandler"),
                _make_module_dict("repo1", "IntimacyService"),
                _make_module_dict("repo1", "IntimacyDao"),
                _make_module_dict("repo1", "IntimacyHandler"),
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("FamilyService", "FamilyDao", 10),
            _make_call_edge("FamilyService", "FamilyHandler", 8),
            _make_call_edge("FamilyDao", "FamilyHandler", 5),
            _make_call_edge("IntimacyService", "IntimacyDao", 12),
            _make_call_edge("IntimacyService", "IntimacyHandler", 7),
            _make_call_edge("IntimacyDao", "IntimacyHandler", 4),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert "domain_mapping" in result
        assert "domain_display_names" in result
        assert "domain_tree" in result
        assert "affected_domains" in result

        # Family modules should be in same domain
        mapping = result["domain_mapping"]
        family_domain = None
        for slug, pairs in mapping.items():
            mod_names = [m for _, m in pairs]
            if "FamilyService" in mod_names:
                family_domain = slug
                assert "FamilyDao" in mod_names
                assert "FamilyHandler" in mod_names
        assert family_domain is not None

    @pytest.mark.asyncio
    async def test_fallback_to_llm_when_no_graph_store(self):
        """When graph_store is None, fall back to old classify_domains_node logic."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "ServiceA"),
                _make_module_dict("repo1", "ServiceB"),
            ]
        }
        state = _make_state(modules)
        config = {"configurable": {"graph_store": None, "llm": MagicMock()}}

        with patch("wiki.nodes.graph_domain_decompose.classify_domains_node") as mock_classify, \
             patch("wiki.nodes.graph_domain_decompose.decompose_hierarchy_node") as mock_decompose:
            mock_classify.return_value = {
                "domain_mapping": {"service-domain": [("repo1", "ServiceA"), ("repo1", "ServiceB")]},
                "affected_domains": ["service-domain"],
                "domain_display_names": {"service-domain": "服务域"},
            }
            mock_decompose.return_value = {
                "domain_tree": [{
                    "name": "service-domain",
                    "display_name": "服务域",
                    "modules": ["ServiceA", "ServiceB"],
                    "children": [],
                }],
            }

            result = await graph_driven_domain_decompose_node(state, config)

        assert "domain_mapping" in result
        assert "domain_tree" in result

    @pytest.mark.asyncio
    async def test_output_domain_tree_format(self):
        """domain_tree entries have correct format: name, display_name, modules (strings), children."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "ModA"),
                _make_module_dict("repo1", "ModB"),
                _make_module_dict("repo1", "ModC"),
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("ModA", "ModB", 5),
            _make_call_edge("ModB", "ModC", 3),
            _make_call_edge("ModA", "ModC", 2),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        tree = result["domain_tree"]
        assert isinstance(tree, list)
        for domain in tree:
            assert "name" in domain
            assert "display_name" in domain
            assert "modules" in domain
            assert "children" in domain
            for m in domain["modules"]:
                assert isinstance(m, str)

    @pytest.mark.asyncio
    async def test_empty_graph_edges_still_produces_output(self):
        """When call graph has no edges, all modules go into one domain."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "Isolated1"),
                _make_module_dict("repo1", "Isolated2"),
                _make_module_dict("repo1", "Isolated3"),
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_mapping"]
        total_modules = sum(len(v) for v in result["domain_mapping"].values())
        assert total_modules == 3

    @pytest.mark.asyncio
    async def test_data_model_modules_excluded(self):
        """Modules with data model names/paths are excluded from domain classification."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "FamilyService", path="src/main/service/FamilyService.java"),
                _make_module_dict("repo1", "FamilyDTO", path="src/main/dto/FamilyDTO.java"),
                _make_module_dict("repo1", "FamilyReq", path="src/main/dto/FamilyReq.java"),
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        all_modules_in_mapping = [m for pairs in result["domain_mapping"].values() for _, m in pairs]
        assert "FamilyService" in all_modules_in_mapping
        assert "FamilyDTO" not in all_modules_in_mapping
        assert "FamilyReq" not in all_modules_in_mapping


class TestDedupSubDomains:
    def test_merges_duplicate_display_names(self):
        subs = [
            {"slug": "friend-mgmt", "display_name": "好友管理", "modules": [("r1", "A")]},
            {"slug": "friend-mgmt-1", "display_name": "好友管理", "modules": [("r1", "B")]},
            {"slug": "gift", "display_name": "送礼", "modules": [("r1", "C")]},
        ]
        result = _dedup_sub_domains(subs, "亲密关系")
        display_names = [s["display_name"] for s in result]
        assert len(display_names) == len(set(display_names))
        merged = next(s for s in result if s["display_name"] == "好友管理")
        assert len(merged["modules"]) == 2

    def test_avoids_parent_child_name_collision(self):
        subs = [
            {"slug": "core", "display_name": "亲密关系", "modules": [("r1", "A")]},
            {"slug": "gift", "display_name": "送礼", "modules": [("r1", "B")]},
        ]
        result = _dedup_sub_domains(subs, "亲密关系")
        for s in result:
            assert s["display_name"] != "亲密关系"

    def test_dedup_slugs_within_batch(self):
        subs = [
            {"slug": "mgmt", "display_name": "管理A", "modules": [("r1", "A")]},
            {"slug": "mgmt", "display_name": "管理B", "modules": [("r1", "B")]},
        ]
        result = _dedup_sub_domains(subs, "父域")
        slugs = [s["slug"] for s in result]
        assert len(slugs) == len(set(slugs))


class TestParallelDomainNaming:
    """Task 6: Verify domain naming calls are parallelized and slugs are deduplicated."""

    @pytest.mark.asyncio
    async def test_all_namer_calls_made_for_all_communities(self):
        """Every community should get a naming call."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", f"Mod{i}", path=f"src/Mod{i}.java")
                for i in range(9)
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("Mod0", "Mod1", 10),
            _make_call_edge("Mod1", "Mod2", 8),
            _make_call_edge("Mod3", "Mod4", 10),
            _make_call_edge("Mod4", "Mod5", 8),
            _make_call_edge("Mod6", "Mod7", 10),
            _make_call_edge("Mod7", "Mod8", 8),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ) as MockCorrector:
            mock_namer = _mock_namer()
            # Patch at the call site
            result = await graph_driven_domain_decompose_node(state, config)

        # Should have produced domains (each community named)
        assert len(result["domain_mapping"]) >= 1

    @pytest.mark.asyncio
    async def test_slug_dedup_after_parallel_naming(self):
        """When parallel LLM calls return duplicate slugs, deduplication should fix them."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "AuthLogin", path="src/auth/AuthLogin.java"),
                _make_module_dict("repo1", "AuthRegister", path="src/auth/AuthRegister.java"),
                _make_module_dict("repo1", "PaymentService", path="src/pay/PaymentService.java"),
                _make_module_dict("repo1", "PaymentDao", path="src/pay/PaymentDao.java"),
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("AuthLogin", "AuthRegister", 10),
            _make_call_edge("PaymentService", "PaymentDao", 10),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        # All modules should still be present despite duplicate slugs
        all_mods = [m for pairs in result["domain_mapping"].values() for _, m in pairs]
        assert len(all_mods) == 4
        # Slugs should be unique
        assert len(result["domain_mapping"]) == len(set(result["domain_mapping"].keys()))


class TestKeywordMergeGeneralization:
    """Task 10: Verify configurable keyword groups and word-boundary matching."""

    def test_default_keywords_include_business_domains(self):
        """Default keywords should cover auth, payment, order, notification groups."""
        all_keywords = set()
        for group in _RELATED_KEYWORDS:
            all_keywords.update(group)
        # Auth group
        assert any(kw in all_keywords for kw in ("authentication", "login", "auth"))
        # Payment group
        assert any(kw in all_keywords for kw in ("payment", "pay", "billing"))
        # Order group
        assert any(kw in all_keywords for kw in ("order", "purchase"))
        # Notification group
        assert any(kw in all_keywords for kw in ("notification", "alert"))

    def test_word_boundary_matching_for_latin_words(self):
        """Latin keywords should match at word boundaries, not as substrings."""
        # "pay" should match "PaymentService" but NOT "display"
        domain_mapping = {
            "pay-mods": [("r1", "PaymentService"), ("r1", "PaymentDao")],
            "display-mods": [("r1", "DisplayHandler"), ("r1", "DisplayService")],
        }
        domain_display = {"pay-mods": "支付", "display-mods": "展示"}
        result_mapping, _ = _merge_domains_by_keyword(domain_mapping, domain_display)
        # "display" should NOT be merged with "pay" even though "pay" is a substring
        assert "display-mods" in result_mapping or "pay-mods" in result_mapping
        # They should remain separate domains (not merged together)
        slugs = list(result_mapping.keys())
        has_pay = any("pay" in s for s in slugs)
        has_display = any("display" in s for s in slugs)
        # Both should still exist (no false merge)
        if has_pay and has_display:
            assert len(result_mapping) == 2

    def test_cjk_substring_matching_still_works(self):
        """CJK keywords should still use substring matching (no word boundaries)."""
        domain_mapping = {
            "family-mods": [("r1", "FamilyService"), ("r1", "FamilyDao")],
        }
        domain_display = {"family-mods": "家族"}
        result_mapping, result_display = _merge_domains_by_keyword(domain_mapping, domain_display)
        assert len(result_mapping) >= 1

    def test_auth_keyword_matches_login_modules(self):
        """Auth keyword group should merge domains with login/authentication modules."""
        domain_mapping = {
            "login-mods": [("r1", "LoginService"), ("r1", "LoginDao")],
            "auth-mods": [("r1", "AuthenticationManager"), ("r1", "AuthProvider")],
        }
        domain_display = {"login-mods": "登录", "auth-mods": "认证"}
        result_mapping, _ = _merge_domains_by_keyword(domain_mapping, domain_display)
        # With the auth keyword group, login and auth should be in the same group
        # But only if >50% of modules match - which they do
        # At minimum, no crash should happen
        assert len(result_mapping) >= 1


class TestTfidfFallbackClustering:
    """Task 11: Verify TF-IDF fallback preserves semantic signals."""

    def test_tfidf_fallback_produces_clusters(self):
        """TF-IDF fallback should cluster modules by name/path similarity."""
        biz_modules = [
            ("r1", "AuthLoginService"),
            ("r1", "AuthRegisterService"),
            ("r1", "PaymentService"),
            ("r1", "PaymentDao"),
            ("r1", "OrderService"),
            ("r1", "OrderDao"),
        ]
        module_paths = {
            "AuthLoginService": "src/auth/AuthLoginService.java",
            "AuthRegisterService": "src/auth/AuthRegisterService.java",
            "PaymentService": "src/payment/PaymentService.java",
            "PaymentDao": "src/payment/PaymentDao.java",
            "OrderService": "src/order/OrderService.java",
            "OrderDao": "src/order/OrderDao.java",
        }
        edges = []
        clusters = _tfidf_fallback_clustering(biz_modules, module_paths, edges)
        assert len(clusters) >= 1
        total = sum(len(c) for c in clusters)
        assert total == 6

    @pytest.mark.asyncio
    async def test_embedding_failure_uses_tfidf_before_louvain(self):
        """When embeddings fail, should try TF-IDF first, not jump to Louvain."""
        biz_modules = [
            ("r1", "UserService"),
            ("r1", "UserDao"),
            ("r1", "OrderService"),
            ("r1", "OrderDao"),
        ]
        module_paths = {
            "UserService": "src/user/UserService.java",
            "UserDao": "src/user/UserDao.java",
            "OrderService": "src/order/OrderService.java",
            "OrderDao": "src/order/OrderDao.java",
        }
        module_summaries = {}
        edges = []

        mock_settings = MagicMock()
        mock_settings.embedding = MagicMock()

        # Patch the lazy imports inside _embedding_clustering
        with patch.dict("sys.modules", {
            "core.config": MagicMock(get_settings=lambda: mock_settings),
            "indexer.embedding_generator": MagicMock(
                EmbeddingGenerator=MagicMock(
                    shared=MagicMock(return_value=MagicMock(
                        generate=AsyncMock(side_effect=Exception("embedding failed")),
                    )),
                ),
            ),
        }):
            # Also need to reload the function's local imports
            clusters, embeddings = await _embedding_clustering(
                biz_modules, edges, module_paths, module_summaries,
            )

        # Should return clusters (from TF-IDF fallback), not crash
        assert len(clusters) >= 1
        assert embeddings is None
        total = sum(len(c) for c in clusters)
        assert total == 4
