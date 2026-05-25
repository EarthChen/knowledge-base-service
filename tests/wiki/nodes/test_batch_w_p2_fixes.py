"""Tests for Batch W backend incremental + compound key P2 fixes."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.flow_baseline import ENTRY_POINT_CY, CROSS_DOMAIN_CY
from wiki.nodes.graph_domain_decompose import (
    _prune_deleted_modules_from_mapping,
    graph_driven_domain_decompose_node,
)


class TestPruneDeletedModulesCompoundKey:
    def test_prune_only_deletes_module_from_deleted_repo(self):
        """Repo A deletes Foo but repo B retains Foo — only repo A's Foo is pruned."""
        domain_mapping = {
            "shared-domain": [
                ("repo_a", "Foo"),
                ("repo_b", "Foo"),
            ],
        }
        current_modules = {("repo_b", "Foo")}

        _prune_deleted_modules_from_mapping(domain_mapping, current_modules)

        assert domain_mapping == {"shared-domain": [("repo_b", "Foo")]}


@pytest.mark.asyncio
async def test_incremental_no_change_skips_edge_fetch():
    """When no changed modules and existing tree present, edge fetch is not called."""
    modules = {
        "repo1": [
            {
                "uid": "Module::FamilyService:0",
                "label": "Module",
                "properties": {"name": "FamilyService", "path": "src/FamilyService.java", "repository": "repo1"},
            },
        ],
    }
    existing_mapping = {"family-domain": [("repo1", "FamilyService")]}
    state = {
        "business_id": "test-biz",
        "repositories": ["repo1"],
        "modules": modules,
        "entity_roles": {"Module::FamilyService:0": "has_business_logic"},
        "is_incremental": True,
        "existing_domain_mapping": existing_mapping,
        "affected_modules": [],
        "pinned_modules": {},
        "domain_tree": [{"name": "family-domain", "modules": ["FamilyService"], "children": []}],
        "domain_mapping": {},
        "affected_domains": [],
    }
    config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

    with patch(
        "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
        new_callable=AsyncMock,
        return_value=([], []),
    ) as mock_fetch:
        await graph_driven_domain_decompose_node(state, config)

    mock_fetch.assert_not_awaited()


@pytest.mark.asyncio
async def test_classify_architecture_layers_compound_keys():
    """Two repos with same module name preserve distinct architecture layers."""
    from wiki.architecture_classifier import LayerResult
    from wiki.nodes.classify_architecture import classify_architecture_layers_node

    modules_state = {
        "modules": {
            "repo_a": [{"properties": {"name": "UserService", "path": "a/UserService.java"}}],
            "repo_b": [{"properties": {"name": "UserService", "path": "b/UserService.java"}}],
        },
    }
    config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

    async def _classify(name: str, path: str) -> LayerResult:
        layer = "api" if path.startswith("a/") else "service"
        return LayerResult(layer=layer, confidence=0.9, votes=[])

    mock_classifier = MagicMock()
    mock_classifier.classify_module = AsyncMock(side_effect=_classify)

    with patch(
        "wiki.architecture_classifier.ArchitectureLayerClassifier",
        return_value=mock_classifier,
    ):
        result = await classify_architecture_layers_node(modules_state, config)

    layers = result["architecture_layers"]
    assert layers["repo_a|UserService"] == {"layer": "api", "confidence": 0.9}
    assert layers["repo_b|UserService"] == {"layer": "service", "confidence": 0.9}


def test_build_layer_summary_compound_key_lookup():
    """Domain compose resolves layers by compound key with bare-name fallback."""
    from wiki.nodes.domain_compose import _build_layer_summary

    module_names = ["UserService", "UserService"]
    architecture_layers = {
        "repo_a|UserService": {"layer": "api", "confidence": 0.9},
        "repo_b|UserService": {"layer": "service", "confidence": 0.85},
    }

    summary = _build_layer_summary(
        module_names,
        architecture_layers,
        module_repo_pairs=[("repo_a", "UserService"), ("repo_b", "UserService")],
    )

    assert "- api (1 modules): UserService" in summary
    assert "- service (1 modules): UserService" in summary


@pytest.mark.asyncio
async def test_reassemble_skipped_on_incremental_no_affected_domains():
    """Incremental run with no affected domains should skip reassembly."""
    from wiki.nodes.reassemble_domains import reassemble_domains_node

    state = {
        "is_incremental": True,
        "affected_domains": [],
        "pages": [{"path": "domain-a/_overview", "content": "Overview " * 50}],
        "domain_mapping": {"domain-a": [("repo", "ModA")]},
        "domain_tree": [{"name": "domain-a"}],
        "config": {},
    }

    mock_generator = AsyncMock()
    with patch("wiki.nodes.reassemble_domains._get_embedding_generator", return_value=mock_generator), \
         patch("wiki.nodes.reassemble_domains._extract_domain_embeddings", new_callable=AsyncMock) as mock_embed, \
         patch("wiki.nodes.reassemble_domains.get_settings") as mock_settings:
        mock_settings.return_value.wiki.domain_reassembly_enabled = True
        mock_settings.return_value.wiki.reassembly_merge_threshold = 0.85
        mock_settings.return_value.wiki.reassembly_orphan_threshold = 0.60
        mock_settings.return_value.wiki.reassembly_max_moves_pct = 0.30
        mock_settings.return_value.wiki.reassembly_respect_user_modified = True
        result = await reassemble_domains_node(state)

    assert result == {}
    mock_embed.assert_not_awaited()


@pytest.mark.asyncio
async def test_flow_baseline_scoped_by_compound_pairs():
    """Two repos with same module name return correct entry points per domain."""
    from wiki.flow_baseline import extract_flow_baseline

    mock_graph = AsyncMock()

    async def _query(cypher: str, params: dict):
        result = MagicMock()
        pairs = set(params.get("valid_pairs", []))
        rows = []
        if "repo_a|Foo" in pairs:
            rows.append(
                {"name": "handleA", "module": "Foo", "file_path": "a/Foo.java", "annotations": ["GetMapping"]},
            )
        if "repo_b|Foo" in pairs:
            rows.append(
                {"name": "handleB", "module": "Foo", "file_path": "b/Foo.java", "annotations": ["PostMapping"]},
            )
        result.data = rows
        return result

    mock_graph.execute_query = AsyncMock(side_effect=_query)

    baseline_a = await extract_flow_baseline(
        mock_graph, "domain-a", valid_pairs=["repo_a|Foo"],
    )
    baseline_b = await extract_flow_baseline(
        mock_graph, "domain-b", valid_pairs=["repo_b|Foo"],
    )

    assert len(baseline_a.entry_points) == 1
    assert baseline_a.entry_points[0].function_name == "handleA"
    assert len(baseline_b.entry_points) == 1
    assert baseline_b.entry_points[0].function_name == "handleB"


def test_flow_baseline_cypher_uses_valid_pairs():
    """Flow baseline Cypher queries filter by compound repo|name pairs."""
    assert "(m.repository + '|' + m.name) IN $valid_pairs" in ENTRY_POINT_CY
    assert "m.name IN $bare_names" in ENTRY_POINT_CY
    assert "(m1.repository + '|' + m1.name) IN $valid_pairs" in CROSS_DOMAIN_CY
    assert "m1.name IN $bare_names" in CROSS_DOMAIN_CY


@pytest.mark.asyncio
async def test_flow_baseline_bare_module_names_backward_compat():
    """Legacy callers passing bare module names still query by m.name."""
    from wiki.flow_baseline import extract_flow_baseline

    mock_graph = AsyncMock()

    async def _query(cypher: str, params: dict):
        result = MagicMock()
        if params.get("bare_names") == ["OrderController"]:
            result.data = [
                {"name": "createOrder", "module": "OrderController", "file_path": "src/Order.java", "annotations": []},
            ]
        else:
            result.data = []
        return result

    mock_graph.execute_query = AsyncMock(side_effect=_query)

    baseline = await extract_flow_baseline(mock_graph, "order", ["OrderController"])
    assert len(baseline.entry_points) == 1
    assert baseline.entry_points[0].function_name == "createOrder"


def test_should_heal_counts_outer_cycles_not_inner_attempts():
    """4 CORE pages × 3 inner rounds should not exhaust limit after 1 outer cycle."""
    from wiki.pipeline_graph import should_heal

    pages = [f"page/core-{i}" for i in range(4)]
    state = {
        "pages_to_heal": pages,
        "heal_attempts": {p: 3 for p in pages},
        "heal_cycles": {p: 1 for p in pages},
        "config": {"heal_loop_max_total_attempts": 10},
    }
    assert should_heal(state) == "heal_pages"


def test_should_heal_falls_back_to_heal_attempts_without_cycles():
    """When heal_cycles is absent, budget uses inner heal_attempts totals."""
    from wiki.pipeline_graph import should_heal

    state = {
        "pages_to_heal": ["page/a", "page/b"],
        "heal_attempts": {"page/a": 6, "page/b": 6},
        "config": {"heal_loop_max_total_attempts": 10},
    }
    assert should_heal(state) == "create_links"
