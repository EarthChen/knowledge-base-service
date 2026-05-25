"""Tests verifying LLM classification path removal from the wiki pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.classify import classify_entities_node, detect_reorg_node
from wiki.nodes.classify_architecture import classify_architecture_layers_node
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node
from wiki.pipeline_graph import build_wiki_pipeline


def _make_module_dict(repo_id: str, name: str) -> dict:
    return {
        "uid": f"Module::{name}:0",
        "label": "Module",
        "properties": {"name": name, "path": f"src/{name}.java", "repository": repo_id},
    }


def _mock_corrector():
    corrector = MagicMock()
    corrector.review_global_consistency = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return corrector


def _mock_namer():
    namer = MagicMock()
    namer.name_community = AsyncMock(
        return_value={"slug": "test-domain", "display_name": "Test Domain", "description": ""},
    )
    return namer


class TestLLMPathRemoval:
    def test_pipeline_does_not_contain_classify_domains_node(self) -> None:
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "classify_domains" not in node_names

    def test_pipeline_contains_graph_domain_decompose_node(self) -> None:
        pipeline = build_wiki_pipeline(checkpointer=False)
        node_names = set(pipeline.get_graph().nodes.keys())
        assert "graph_domain_decompose" in node_names

    def test_compose_leaf_modules_routes_to_graph_domain_decompose(self) -> None:
        pipeline = build_wiki_pipeline(checkpointer=False)
        edges = pipeline.get_graph().edges
        assert any(
            e.source == "compose_leaf_modules" and e.target == "graph_domain_decompose"
            for e in edges
        )

    def test_classify_nodes_still_exist(self) -> None:
        assert callable(classify_entities_node)
        assert callable(classify_architecture_layers_node)
        assert callable(detect_reorg_node)

    @pytest.mark.asyncio
    async def test_no_llm_fallback_when_graph_store_missing(self) -> None:
        """Graph path returns empty classification when graph_store is absent."""
        modules = {"repo1": [_make_module_dict("repo1", "ServiceA")]}
        state = {
            "business_id": "test-biz",
            "repositories": ["repo1"],
            "modules": modules,
            "entity_roles": {"Module::ServiceA:0": "has_business_logic"},
        }
        config = {"configurable": {"graph_store": None, "llm": MagicMock()}}

        result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_mapping"] == {}
        assert result["domain_tree"] == []
        assert result["affected_domains"] == []

    @pytest.mark.asyncio
    async def test_graph_driven_path_still_works_with_mock_graph_store(self) -> None:
        """Production graph path produces domain_mapping when graph_store is available."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "ModA"),
                _make_module_dict("repo1", "ModB"),
            ],
        }
        state = {
            "business_id": "test-biz",
            "repositories": ["repo1"],
            "modules": modules,
            "entity_roles": {
                "Module::ModA:0": "has_business_logic",
                "Module::ModB:0": "has_business_logic",
            },
            "module_summaries": {
                "repo1|ModA": {"summary_text": "Module A"},
                "repo1|ModB": {"summary_text": "Module B"},
            },
            "is_incremental": False,
            "domain_mapping": {},
            "domain_tree": None,
            "affected_domains": [],
        }
        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [_make_call_edge("ModA", "ModB", 5)]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)
        config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}

        with patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=_mock_namer(),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert "domain_mapping" in result
        assert "domain_tree" in result
        assert result["domain_mapping"]


def _make_call_edge(source: str, target: str, weight: int = 10, repo: str = "repo1") -> dict:
    return {
        "source_repo": repo,
        "source": source,
        "target_repo": repo,
        "target": target,
        "weight": weight,
    }
