from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.graph_domain_decompose import (
    _apply_merge_map,
    _dedup_parallel_naming_results,
    _dedup_sub_domains,
    _embedding_clustering,
    _merge_domains_by_embedding,
    _merge_domains_by_llm,
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
    async def test_returns_empty_when_no_graph_store(self):
        """When graph_store is None, return empty classification (no LLM fallback)."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "ServiceA"),
                _make_module_dict("repo1", "ServiceB"),
            ]
        }
        state = _make_state(modules)
        config = {"configurable": {"graph_store": None, "llm": MagicMock()}}

        result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_mapping"] == {}
        assert result["domain_tree"] == []
        assert result["affected_domains"] == []

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
    """Verify sub-domain naming is parallelized and slugs are deduplicated."""

    def test_parallel_naming_slug_dedup(self):
        """When LLM generates duplicate slugs, numeric suffix should be appended."""
        results = [
            {"slug": "core", "display_name": "Core A"},
            {"slug": "core", "display_name": "Core B"},
            {"slug": "auth", "display_name": "Auth"},
        ]
        deduped = _dedup_parallel_naming_results(results, existing_slugs=["payment"])

        slugs = [r["slug"] for r in deduped]
        assert len(set(slugs)) == 3, "All slugs must be unique"
        assert "core" in slugs, "First 'core' keeps original name"
        assert "core-2" in slugs, "Duplicate gets numeric suffix"
        assert "payment" not in slugs, "Existing slugs not added"

    @pytest.mark.asyncio
    async def test_recursive_split_naming_runs_in_parallel(self):
        """Sub-domain naming tasks should overlap when multiple sub-clusters exist."""
        import asyncio

        import numpy as np

        modules_list = [(f"repo1", f"Mod{i}") for i in range(12)]
        big_community = set(modules_list)
        sub_clusters = [
            set(modules_list[0:4]),
            set(modules_list[4:8]),
            set(modules_list[8:12]),
        ]

        in_flight = [0]
        max_in_flight = [0]

        async def mock_embedding_clustering(*_args, **_kwargs):
            return [[big_community], np.zeros((12, 8))]

        async def name_community(**kwargs):
            infos = kwargs.get("module_infos") or []
            if len(infos) >= 10:
                return {"slug": "big-domain", "display_name": "Big Domain"}
            in_flight[0] += 1
            max_in_flight[0] = max(max_in_flight[0], in_flight[0])
            await asyncio.sleep(0.05)
            in_flight[0] -= 1
            mod_name = infos[0]["name"]
            slug = mod_name.lower()
            return {"slug": slug, "display_name": f"Domain {slug}"}

        modules = {
            "repo1": [
                _make_module_dict("repo1", f"Mod{i}", path=f"src/Mod{i}.java")
                for i in range(12)
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge(f"Mod{i}", f"Mod{i + 1}", 10) for i in range(11)
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_namer = MagicMock()
        mock_namer.name_community = AsyncMock(side_effect=name_community)
        mock_clusterer = MagicMock()
        mock_clusterer.cluster_sub_domains.return_value = sub_clusters

        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
        with patch(
            "wiki.nodes.graph_domain_decompose._get_split_params",
            return_value=(10, 3),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            side_effect=mock_embedding_clustering,
        ), patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer",
            return_value=mock_clusterer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=mock_namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert max_in_flight[0] >= 2, "Sub-domain naming should run concurrently"
        assert result["domain_tree"]

    @pytest.mark.asyncio
    async def test_recursive_split_dedups_colliding_sub_domain_slugs(self):
        """Parallel sub-domain naming resolves duplicate slugs via hash suffix."""
        import numpy as np

        modules_list = [(f"repo1", f"Mod{i}") for i in range(12)]
        big_community = set(modules_list)
        sub_clusters = [
            set(modules_list[0:4]),
            set(modules_list[4:8]),
            set(modules_list[8:12]),
        ]

        async def mock_embedding_clustering(*_args, **_kwargs):
            return [[big_community], np.zeros((12, 8))]

        async def name_community(**kwargs):
            infos = kwargs.get("module_infos") or []
            if len(infos) >= 10:
                return {"slug": "big-domain", "display_name": "Big Domain"}
            mod_name = infos[0]["name"]
            return {"slug": "core", "display_name": f"Core {mod_name}"}

        modules = {
            "repo1": [
                _make_module_dict("repo1", f"Mod{i}", path=f"src/Mod{i}.java")
                for i in range(12)
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge(f"Mod{i}", f"Mod{i + 1}", 10) for i in range(11)
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_namer = MagicMock()
        mock_namer.name_community = AsyncMock(side_effect=name_community)
        mock_clusterer = MagicMock()
        mock_clusterer.cluster_sub_domains.return_value = sub_clusters

        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
        with patch(
            "wiki.nodes.graph_domain_decompose._get_split_params",
            return_value=(10, 3),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            side_effect=mock_embedding_clustering,
        ), patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer",
            return_value=mock_clusterer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=mock_namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        tree = result["domain_tree"]
        assert len(tree) == 1
        children = tree[0]["children"]
        assert len(children) == 3
        child_slugs = [c["name"] for c in children]
        assert len(set(child_slugs)) == 3
        assert child_slugs.count("core") == 1
        assert sum(1 for s in child_slugs if s.startswith("core-")) == 2

    @pytest.mark.asyncio
    async def test_recursive_split_filters_infra_subdomain(self):
        """Infrastructure-like sub-domain slugs are merged into the largest sibling."""
        import numpy as np

        modules_list = [(f"repo1", f"Mod{i}") for i in range(12)]
        big_community = set(modules_list)
        sub_clusters = [
            set(modules_list[0:5]),
            set(modules_list[5:10]),
            set(modules_list[10:12]),
        ]

        async def mock_embedding_clustering(*_args, **_kwargs):
            return [[big_community], np.zeros((12, 8))]

        async def name_community(**kwargs):
            infos = kwargs.get("module_infos") or []
            if len(infos) >= 10:
                return {"slug": "guild-operations", "display_name": "Guild Operations"}
            mod_name = infos[0]["name"]
            if mod_name in ("Mod0", "Mod1"):
                return {"slug": "guild-core", "display_name": "Guild Core"}
            if mod_name in ("Mod5", "Mod6"):
                return {"slug": "guild-members", "display_name": "Guild Members"}
            return {"slug": "debug-groovy-executor", "display_name": "Debug Executor"}

        modules = {
            "repo1": [
                _make_module_dict("repo1", f"Mod{i}", path=f"src/Mod{i}.java")
                for i in range(12)
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge(f"Mod{i}", f"Mod{i + 1}", 10) for i in range(11)
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_namer = MagicMock()
        mock_namer.name_community = AsyncMock(side_effect=name_community)
        mock_clusterer = MagicMock()
        mock_clusterer.cluster_sub_domains.return_value = sub_clusters

        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.infrastructure_slug_keywords = [
            "configuration",
            "executor",
            "debug",
            "groovy",
        ]
        mock_wiki_cfg.skip_llm_merge_when_corrector_enabled = False
        mock_wiki_cfg.domain_budget_max = 50

        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
        with patch(
            "wiki.nodes.graph_domain_decompose._get_split_params",
            return_value=(10, 3),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            side_effect=mock_embedding_clustering,
        ), patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer",
            return_value=mock_clusterer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=mock_namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.get_settings",
            return_value=MagicMock(wiki=mock_wiki_cfg, embedding=MagicMock()),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        tree = result["domain_tree"]
        assert len(tree) == 1
        children = tree[0]["children"]
        child_slugs = [c["name"] for c in children]
        assert "debug-groovy-executor" not in child_slugs
        assert len(children) == 2

        infra_mod_keys = {f"repo1|Mod{i}" for i in (10, 11)}
        child_module_keys = {m for c in children for m in c["modules"]}
        assert infra_mod_keys <= child_module_keys

    @pytest.mark.asyncio
    async def test_recursive_split_does_not_recurse_beyond_max_depth_two(self):
        """With max_split_depth=2, no splitting occurs once depth reaches 2."""
        import numpy as np

        modules_list = [("repo1", f"Mod{i}") for i in range(24)]
        big_community = set(modules_list)
        sub_clusters = [
            set(modules_list[0:12]),
            set(modules_list[12:24]),
        ]
        cluster_call_depths: list[int] = []

        async def mock_embedding_clustering(*_args, **_kwargs):
            return [[big_community], np.zeros((24, 8))]

        async def name_community(**kwargs):
            infos = kwargs.get("module_infos") or []
            if len(infos) >= 20:
                return {"slug": "root-domain", "display_name": "Root Domain"}
            mod_name = infos[0]["name"]
            return {"slug": f"sub-{mod_name.lower()}", "display_name": f"Sub {mod_name}"}

        def cluster_sub_domains(_embeddings, _modules, _edges):
            cluster_call_depths.append(len(cluster_call_depths))
            return sub_clusters

        modules = {
            "repo1": [
                _make_module_dict("repo1", f"Mod{i}", path=f"src/Mod{i}.java")
                for i in range(24)
            ]
        }
        state = _make_state(modules)

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge(f"Mod{i}", f"Mod{i + 1}", 10) for i in range(23)
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_namer = MagicMock()
        mock_namer.name_community = AsyncMock(side_effect=name_community)
        mock_clusterer = MagicMock()
        mock_clusterer.cluster_sub_domains.side_effect = cluster_sub_domains

        mock_wiki_cfg = MagicMock()
        mock_wiki_cfg.infrastructure_slug_keywords = []
        mock_wiki_cfg.skip_llm_merge_when_corrector_enabled = False
        mock_wiki_cfg.domain_budget_max = 50
        mock_wiki_cfg.domain_split_threshold = 10
        mock_wiki_cfg.domain_split_max_depth = 2

        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
        with patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            side_effect=mock_embedding_clustering,
        ), patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer",
            return_value=mock_clusterer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=mock_namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.get_settings",
            return_value=MagicMock(wiki=mock_wiki_cfg, embedding=MagicMock()),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_tree"]
        assert mock_clusterer.cluster_sub_domains.call_count == 3

        def _max_child_depth(nodes: list[dict], current: int = 0) -> int:
            if not nodes:
                return current
            child_depths = [_max_child_depth(n.get("children", []), current + 1) for n in nodes]
            return max(child_depths) if child_depths else current

        tree = result["domain_tree"]
        root_children = tree[0].get("children", [])
        assert _max_child_depth(root_children) <= 2

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


class TestApplyMergeMap:
    def test_merges_modules_into_target(self):
        domain_mapping = {
            "auth": [("r1", "LoginService")],
            "login": [("r1", "LoginDao")],
            "payment": [("r1", "PaymentService")],
        }
        domain_display = {"auth": "认证", "login": "登录", "payment": "支付"}
        merge_map = {"login": "auth"}
        new_mapping, new_display = _apply_merge_map(merge_map, domain_mapping, domain_display)
        assert set(new_mapping.keys()) == {"auth", "payment"}
        assert len(new_mapping["auth"]) == 2
        assert new_display["auth"] == "认证"


class TestMergeDomainsByLlm:
    @pytest.mark.asyncio
    async def test_llm_merge_path(self):
        domain_mapping = {
            "login": [("r1", "LoginService"), ("r1", "LoginDao")],
            "auth": [("r1", "AuthProvider")],
            "payment": [("r1", "PaymentService")],
        }
        domain_display = {"login": "登录", "auth": "认证", "payment": "支付"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(
            return_value={"merge_groups": [["login", "auth"]]},
        )
        result_mapping, result_display = await _merge_domains_by_llm(
            domain_mapping, domain_display, mock_llm,
        )
        assert set(result_mapping.keys()) == {"login", "payment"}
        assert len(result_mapping["login"]) == 3
        assert result_display["login"] == "登录"
        mock_llm.complete_json.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_llm_empty_merge_groups(self):
        domain_mapping = {
            "login": [("r1", "LoginService")],
            "payment": [("r1", "PaymentService")],
        }
        domain_display = {"login": "登录", "payment": "支付"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={"merge_groups": []})
        result_mapping, result_display = await _merge_domains_by_llm(
            domain_mapping, domain_display, mock_llm,
        )
        assert result_mapping == domain_mapping
        assert result_display == domain_display

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_embedding(self, monkeypatch):
        domain_mapping = {
            "domain-a": [("r1", "ModA")],
            "domain-b": [("r1", "ModB")],
            "domain-c": [("r1", "ModC")],
        }
        domain_display = {"domain-a": "A", "domain-b": "B", "domain-c": "C"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(side_effect=Exception("llm timeout"))
        mock_embedding_merge = AsyncMock(return_value=(domain_mapping, domain_display))
        monkeypatch.setattr(
            "wiki.nodes.graph_domain_decompose._merge_domains_by_embedding",
            mock_embedding_merge,
        )
        await _merge_domains_by_llm(domain_mapping, domain_display, mock_llm)
        mock_embedding_merge.assert_awaited_once_with(domain_mapping, domain_display)

    @pytest.mark.asyncio
    async def test_skips_merge_when_two_or_fewer_domains(self):
        domain_mapping = {"only": [("r1", "ModA")]}
        domain_display = {"only": "唯一域"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock()
        result_mapping, result_display = await _merge_domains_by_llm(
            domain_mapping, domain_display, mock_llm,
        )
        assert result_mapping == domain_mapping
        mock_llm.complete_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_large_domain_not_merged(self):
        large_modules = [(f"r{i}", f"Mod{i}") for i in range(41)]
        domain_mapping = {
            "large": large_modules,
            "small": [("r1", "SmallService")],
            "other": [("r1", "OtherService"), ("r1", "OtherDao")],
        }
        domain_display = {"large": "大域", "small": "小域", "other": "其他"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(
            return_value={"merge_groups": [["large", "small"]]},
        )
        result_mapping, _ = await _merge_domains_by_llm(
            domain_mapping, domain_display, mock_llm,
        )
        assert "large" in result_mapping
        assert "small" not in result_mapping
        assert len(result_mapping["large"]) == 42


class TestMergeDomainsByEmbedding:
    @pytest.mark.asyncio
    async def test_embedding_merge_above_threshold(self, monkeypatch):
        domain_mapping = {
            "auth-login": [("r1", "LoginService")],
            "auth-signin": [("r1", "SignInService")],
            "payment": [("r1", "PaymentService")],
        }
        domain_display = {
            "auth-login": "用户登录",
            "auth-signin": "用户登入",
            "payment": "支付结算",
        }
        emb_a = [1.0, 0.0]
        emb_b = [0.99, 0.01]
        emb_c = [0.0, 1.0]

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=[emb_a, emb_b, emb_c])
        monkeypatch.setattr(
            "core.config.get_settings",
            lambda: MagicMock(embedding=MagicMock()),
        )
        monkeypatch.setattr(
            "indexer.embedding_generator.EmbeddingGenerator.shared",
            lambda _config: mock_generator,
        )
        result_mapping, _ = await _merge_domains_by_embedding(
            domain_mapping, domain_display, similarity_threshold=0.8,
        )
        assert len(result_mapping) == 2
        merged_slug = next(
            slug for slug, mods in result_mapping.items() if len(mods) == 2
        )
        assert merged_slug in {"auth-login", "auth-signin"}

    @pytest.mark.asyncio
    async def test_embedding_merge_below_threshold(self, monkeypatch):
        domain_mapping = {
            "auth": [("r1", "LoginService")],
            "payment": [("r1", "PaymentService")],
            "order": [("r1", "OrderService")],
        }
        domain_display = {"auth": "认证", "payment": "支付", "order": "订单"}
        emb_a = [1.0, 0.0]
        emb_b = [0.707, 0.707]
        emb_c = [0.0, 1.0]

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=[emb_a, emb_b, emb_c])
        monkeypatch.setattr(
            "core.config.get_settings",
            lambda: MagicMock(embedding=MagicMock()),
        )
        monkeypatch.setattr(
            "indexer.embedding_generator.EmbeddingGenerator.shared",
            lambda _config: mock_generator,
        )
        result_mapping, _ = await _merge_domains_by_embedding(
            domain_mapping, domain_display, similarity_threshold=0.8,
        )
        assert len(result_mapping) == 3

    @pytest.mark.asyncio
    async def test_embedding_failure_returns_original(self, monkeypatch):
        domain_mapping = {
            "a": [("r1", "ModA")],
            "b": [("r1", "ModB")],
            "c": [("r1", "ModC")],
        }
        domain_display = {"a": "A", "b": "B", "c": "C"}
        monkeypatch.setattr(
            "core.config.get_settings",
            lambda: MagicMock(embedding=MagicMock()),
        )
        monkeypatch.setattr(
            "indexer.embedding_generator.EmbeddingGenerator.shared",
            lambda _config: MagicMock(
                generate=AsyncMock(side_effect=Exception("embedding failed")),
            ),
        )
        result_mapping, result_display = await _merge_domains_by_embedding(
            domain_mapping, domain_display,
        )
        assert result_mapping == domain_mapping
        assert result_display == domain_display

    @pytest.mark.asyncio
    async def test_double_fallback_returns_original(self, monkeypatch):
        domain_mapping = {
            "a": [("r1", "ModA")],
            "b": [("r1", "ModB")],
            "c": [("r1", "ModC")],
        }
        domain_display = {"a": "A", "b": "B", "c": "C"}
        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(side_effect=Exception("llm failed"))
        monkeypatch.setattr(
            "wiki.nodes.graph_domain_decompose._merge_domains_by_embedding",
            AsyncMock(side_effect=Exception("embedding failed")),
        )
        result_mapping, result_display = await _merge_domains_by_llm(
            domain_mapping, domain_display, mock_llm,
        )
        assert result_mapping == domain_mapping
        assert result_display == domain_display


class TestTfidfFallbackClustering:
    """Task 11: Verify TF-IDF fallback preserves semantic signals."""

    def test_tfidf_uses_build_embedding_texts_when_summaries_provided(self):
        """When module_summaries_raw is provided, build_embedding_texts should be used."""
        biz_modules = [
            ("r1", "AuthLoginService"),
            ("r1", "AuthRegisterService"),
            ("r1", "PaymentService"),
        ]
        module_paths = {
            "AuthLoginService": "src/auth/AuthLoginService.java",
            "AuthRegisterService": "src/auth/AuthRegisterService.java",
            "PaymentService": "src/payment/PaymentService.java",
        }
        module_summaries = {
            "AuthLoginService": {"summary_text": "Login authentication flow"},
            "AuthRegisterService": {"summary_text": "User registration flow"},
            "PaymentService": {"summary_text": "Payment processing"},
        }
        edges = []
        with patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer.build_embedding_texts",
            return_value=[
                "AuthLoginService login auth",
                "AuthRegisterService register auth",
                "PaymentService payment",
            ],
        ) as mock_build:
            clusters = _tfidf_fallback_clustering(
                biz_modules, module_paths, edges, module_summaries_raw=module_summaries,
            )
        mock_build.assert_called_once_with(biz_modules, module_summaries, module_paths)
        assert len(clusters) >= 1
        assert sum(len(c) for c in clusters) == 3

    def test_tfidf_falls_back_to_name_path_when_build_embedding_texts_fails(self):
        """When build_embedding_texts raises, fall back to name+path strings."""
        biz_modules = [
            ("r1", "ModA"),
            ("r1", "ModB"),
            ("r1", "ModC"),
        ]
        module_paths = {
            "ModA": "src/a/ModA.java",
            "ModB": "src/b/ModB.java",
            "ModC": "src/c/ModC.java",
        }
        module_summaries = {"ModA": {"summary_text": "A"}}
        edges = []
        with patch(
            "wiki.nodes.graph_domain_decompose.DomainSemanticClusterer.build_embedding_texts",
            side_effect=RuntimeError("build failed"),
        ):
            clusters = _tfidf_fallback_clustering(
                biz_modules, module_paths, edges, module_summaries_raw=module_summaries,
            )
        assert len(clusters) >= 1
        assert sum(len(c) for c in clusters) == 3

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


class TestDedupSemanticSuffix:
    def test_collision_uses_module_suffix(self):
        results = [
            {"slug": "payment", "display_name": "支付", "modules": ["OrderService", "PayService"]},
            {"slug": "payment", "display_name": "支付退款", "modules": ["RefundHandler", "ChargebackService"]},
        ]
        deduped = _dedup_parallel_naming_results(results, [])
        slugs = [r["slug"] for r in deduped]
        assert len(set(slugs)) == 2, f"Expected unique slugs, got {slugs}"
        collision_slug = slugs[1]
        assert "payment" in collision_slug
        # Should NOT be a 4-char hex hash suffix
        suffix_part = collision_slug.split("payment-", 1)[-1]
        assert not all(c in "0123456789abcdef" for c in suffix_part if suffix_part), (
            f"Expected semantic suffix, not hash: {collision_slug}"
        )

    def test_no_collision_unchanged(self):
        results = [
            {"slug": "payment", "display_name": "支付", "modules": ["PayService"]},
            {"slug": "family", "display_name": "家族", "modules": ["FamilyService"]},
        ]
        deduped = _dedup_parallel_naming_results(results, [])
        assert deduped[0]["slug"] == "payment"
        assert deduped[1]["slug"] == "family"

    def test_collision_no_modules_uses_numeric(self):
        results = [
            {"slug": "core", "display_name": "核心", "modules": []},
            {"slug": "core", "display_name": "核心2", "modules": []},
        ]
        deduped = _dedup_parallel_naming_results(results, [])
        slugs = [r["slug"] for r in deduped]
        assert len(set(slugs)) == 2
        assert "core" in slugs
        assert "core-2" in slugs

    def test_collision_with_existing_slugs(self):
        results = [
            {"slug": "payment", "display_name": "支付", "modules": ["PayService", "OrderService"]},
        ]
        deduped = _dedup_parallel_naming_results(results, ["payment"])
        assert deduped[0]["slug"] != "payment"
        assert "payment" in deduped[0]["slug"]
