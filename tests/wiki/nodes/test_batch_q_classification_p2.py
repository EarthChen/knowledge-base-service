"""Tests for Batch Q backend classification P2 improvements."""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.graph_semantic_corrector import GraphSemanticCorrector, build_global_review_prompt
from wiki.nodes.aggregate import _compute_cross_domain_call_stats
from wiki.nodes.domain_filters import is_data_model
from wiki.nodes.graph_domain_decompose import (
    _compound_key,
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


class TestGlobalReviewLanguagePrompt:
    def test_english_wiki_uses_english_display_name_guidelines(self):
        prompt = build_global_review_prompt(
            business_id="biz",
            domain_listing="- auth (Auth) — 1 modules",
            language="en",
        )
        assert "2-4 word English" in prompt or "English business name" in prompt
        assert "2-6 Chinese characters" not in prompt
        assert "Chinese business terminology" not in prompt

    def test_chinese_wiki_keeps_chinese_display_name_guidelines(self):
        prompt = build_global_review_prompt(
            business_id="biz",
            domain_listing="- auth (认证) — 1 modules",
            language="简体中文",
        )
        assert "2-6 Chinese characters" in prompt
        assert "Chinese business terminology" in prompt

    @pytest.mark.asyncio
    async def test_english_rename_accepted(self):
        llm = AsyncMock()
        llm.generate.return_value = json.dumps({
            "merges": [],
            "renames": [{"slug": "auth-login", "new_display_name": "User Authentication", "reason": "clearer"}],
            "moves": [],
        })
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "auth-login": [("r", "LoginService")],
            "billing": [("r", "BillService")],
        }
        domain_display = {"auth-login": "auth-login", "billing": "Billing"}
        _, new_display = await corrector.review_global_consistency(
            domain_mapping,
            domain_display,
            module_paths={},
            module_summaries={},
            language="English",
        )
        assert new_display["auth-login"] == "User Authentication"


class TestModuleCallEdgesRepoRetention:
    @pytest.mark.asyncio
    async def test_module_call_edges_retain_repo_identifiers(self):
        modules = {
            "repo-a": [_make_module_dict("repo-a", "PaySvc")],
            "repo-b": [_make_module_dict("repo-b", "BillSvc")],
        }
        state = {
            "business_id": "test-biz",
            "repositories": ["repo-a", "repo-b"],
            "modules": modules,
            "entity_roles": {
                "Module::PaySvc:0": "has_business_logic",
                "Module::BillSvc:0": "has_business_logic",
            },
            "is_incremental": False,
            "domain_mapping": {},
            "domain_tree": None,
            "affected_domains": [],
        }

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("PaySvc", "BillSvc", 5, repo="repo-a"),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)

        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}

        with patch(
            "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
            new=AsyncMock(return_value=([
                (("repo-a", "PaySvc"), ("repo-b", "BillSvc"), 5),
            ], [])),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            new=AsyncMock(return_value=([{("repo-a", "PaySvc"), ("repo-b", "BillSvc")}], None)),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
        ) as mock_namer_cls, patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
        ) as mock_corrector_cls:
            mock_namer = MagicMock()
            mock_namer.name_community = AsyncMock(return_value={
                "slug": "commerce",
                "display_name": "Commerce",
                "description": "",
            })
            mock_namer_cls.return_value = mock_namer
            mock_corrector = MagicMock()
            mock_corrector.review_global_consistency = AsyncMock(
                side_effect=lambda dm, dn, *_a, **_k: (dm, dn),
            )
            mock_corrector_cls.return_value = mock_corrector

            result = await graph_driven_domain_decompose_node(state, config)

        edges = result["module_call_edges"]
        assert len(edges) == 1
        edge = edges[0]
        assert edge["source_repo"] == "repo-a"
        assert edge["source"] == "PaySvc"
        assert edge["target_repo"] == "repo-b"
        assert edge["target"] == "BillSvc"
        assert edge["source_key"] == _compound_key("repo-a", "PaySvc")
        assert edge["target_key"] == _compound_key("repo-b", "BillSvc")


def test_cross_domain_call_stats_with_repo_scoped_edges():
    parent = {
        "name": "commerce",
        "children": [
            {
                "name": "payment",
                "display_name": "Payment",
                "modules": ["repo-a|PaySvc", "PaySvc"],
            },
            {
                "name": "billing",
                "display_name": "Billing",
                "modules": ["repo-b|BillSvc"],
            },
        ],
    }
    edges = [{
        "source_repo": "repo-a",
        "source": "PaySvc",
        "target_repo": "repo-b",
        "target": "BillSvc",
        "source_key": "repo-a|PaySvc",
        "target_key": "repo-b|BillSvc",
        "weight": 5,
    }]
    result = _compute_cross_domain_call_stats(parent, edges)
    assert "Payment → Billing: 5" in result


class TestSharedDomainFilters:
    def test_is_data_model_from_shared_module(self):
        assert is_data_model("UserDTO", "src/user.py") is True
        assert is_data_model("OrderService", "src/order/service.py") is False

    def test_graph_domain_decompose_uses_shared_filter(self):
        from wiki.nodes.domain_filters import is_data_model as filter_from_shared
        from wiki.nodes import graph_domain_decompose as gdd

        assert filter_from_shared("UserDTO", "src/user.py") is True
        assert filter_from_shared("OrderService", "src/order/service.py") is False
        assert gdd.is_data_model is filter_from_shared


class TestSkipLlmMergeWhenCorrectorEnabled:
    @pytest.mark.asyncio
    async def test_skips_llm_merge_when_corrector_enabled(self):
        modules = {
            "repo1": [
                _make_module_dict("repo1", "ModA"),
                _make_module_dict("repo1", "ModB"),
                _make_module_dict("repo1", "ModC"),
            ],
        }
        state = {
            "business_id": "test-biz",
            "repositories": ["repo1"],
            "modules": modules,
            "entity_roles": {
                "Module::ModA:0": "has_business_logic",
                "Module::ModB:0": "has_business_logic",
                "Module::ModC:0": "has_business_logic",
            },
            "is_incremental": False,
            "domain_mapping": {},
            "domain_tree": None,
            "affected_domains": [],
        }

        mock_graph_store = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [
            _make_call_edge("ModA", "ModB", 5),
            _make_call_edge("ModB", "ModC", 3),
        ]
        mock_graph_store.execute_query = AsyncMock(return_value=mock_result)
        mock_llm = MagicMock()
        config = {"configurable": {"graph_store": mock_graph_store, "llm": mock_llm}}

        with patch(
            "wiki.nodes.graph_domain_decompose._merge_domains_by_llm",
            new=AsyncMock(),
        ) as mock_llm_merge, patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
        ) as mock_namer_cls, patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
        ) as mock_corrector_cls, patch(
            "wiki.nodes.graph_domain_decompose.get_settings",
        ) as mock_settings:
            wiki_cfg = MagicMock()
            wiki_cfg.skip_llm_merge_when_corrector_enabled = True
            wiki_cfg.classify_include_supporting = False
            wiki_cfg.domain_budget_max = 50
            wiki_cfg.infrastructure_slug_keywords = [
                "configuration", "typehandler", "aspect", "package-info", "wrapper",
                "handler", "executor", "debug", "groovy", "impl",
            ]
            mock_settings.return_value = MagicMock(wiki=wiki_cfg)

            mock_namer = MagicMock()
            mock_namer.name_community = AsyncMock(return_value={
                "slug": "domain-1",
                "display_name": "Domain 1",
                "description": "",
            })
            mock_namer_cls.return_value = mock_namer
            mock_corrector = MagicMock()
            mock_corrector.review_global_consistency = AsyncMock(
                side_effect=lambda dm, dn, *_a, **_k: (dm, dn),
            )
            mock_corrector_cls.return_value = mock_corrector

            await graph_driven_domain_decompose_node(state, config)

        mock_llm_merge.assert_not_awaited()
        mock_corrector.review_global_consistency.assert_awaited_once()
