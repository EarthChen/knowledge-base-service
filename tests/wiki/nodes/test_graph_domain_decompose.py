from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.graph_domain_decompose import (
    _dedup_sub_domains,
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
        # Family modules call each other, Intimacy modules call each other
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
        mock_llm.generate = AsyncMock(side_effect=[
            '{"slug": "family-system", "display_name": "家族系统", "description": "family"}',
            '{"slug": "intimacy", "display_name": "亲密关系", "description": "intimacy"}',
        ])

        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
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

        # Should not crash; should produce valid output
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
        mock_llm.generate = AsyncMock(
            return_value='{"slug": "mod-group", "display_name": "模块组", "description": "test"}',
        )

        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        result = await graph_driven_domain_decompose_node(state, config)

        tree = result["domain_tree"]
        assert isinstance(tree, list)
        for domain in tree:
            assert "name" in domain
            assert "display_name" in domain
            assert "modules" in domain
            assert "children" in domain
            # modules should be strings, not tuples
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
        mock_result.data = []  # no edges
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value='{"slug": "misc", "display_name": "其他", "description": "misc"}')

        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
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
        mock_llm.generate = AsyncMock(return_value='{"slug": "family", "display_name": "家族", "description": "f"}')

        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}
        result = await graph_driven_domain_decompose_node(state, config)

        # Only FamilyService should be in domain_mapping (DTO and Req are data models)
        all_modules_in_mapping = [m for pairs in result["domain_mapping"].values() for _, m in pairs]
        assert "FamilyService" in all_modules_in_mapping
        assert "FamilyDTO" not in all_modules_in_mapping
        assert "FamilyReq" not in all_modules_in_mapping


class TestDedupSubDomains:
    def test_merges_duplicate_display_names(self):
        """Sub-domains with identical display_name should be merged."""
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
        """Child should not have the same display_name as its parent."""
        subs = [
            {"slug": "core", "display_name": "亲密关系", "modules": [("r1", "A")]},
            {"slug": "gift", "display_name": "送礼", "modules": [("r1", "B")]},
        ]
        result = _dedup_sub_domains(subs, "亲密关系")
        for s in result:
            assert s["display_name"] != "亲密关系"

    def test_dedup_slugs_within_batch(self):
        """Slugs should be unique after dedup."""
        subs = [
            {"slug": "mgmt", "display_name": "管理A", "modules": [("r1", "A")]},
            {"slug": "mgmt", "display_name": "管理B", "modules": [("r1", "B")]},
        ]
        result = _dedup_sub_domains(subs, "父域")
        slugs = [s["slug"] for s in result]
        assert len(slugs) == len(set(slugs))
