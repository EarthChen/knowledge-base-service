"""Tests for Batch AD domain classification P2+P3 fixes."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.nodes.classify import get_pinned_domain_slug, is_module_pinned
from wiki.nodes.graph_domain_decompose import (
    _assign_pinned_modules,
    _merge_domains_by_embedding,
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


def _make_state(modules: dict, **overrides):
    all_uids = []
    for repo, mods in modules.items():
        for m in mods:
            all_uids.append(m["uid"])
    state = {
        "business_id": "test-biz",
        "repositories": list(modules.keys()),
        "modules": modules,
        "entity_roles": {uid: "has_business_logic" for uid in all_uids},
        "is_incremental": False,
        "domain_mapping": {},
        "domain_tree": None,
        "affected_domains": [],
        "pinned_modules": {},
    }
    state.update(overrides)
    return state


class TestClassifyRemainingEnrichedSignals:
    """AD-1: _classify_remaining should include enriched module summaries."""

    @pytest.mark.asyncio
    async def test_classify_remaining_includes_enriched_summary(self):
        llm = AsyncMock()
        captured: dict[str, str] = {}

        async def _complete_json(messages, _schema):
            for m in messages:
                if m.get("role") == "user":
                    captured["prompt"] = str(m.get("content", ""))
            return {"OrphanSvc": "payments"}

        llm.complete_json = AsyncMock(side_effect=_complete_json)
        planner = CrossRepoBusinessDomainPlanner(llm)
        planner._metadata_cache = {
            ("repo_a", "OrphanSvc"): {"business_summary": "Base summary"},
        }

        enriched = {
            ("repo_a", "OrphanSvc"): {
                "summary_text": "Handles orphan payment reconciliation",
                "key_methods": ["reconcile"],
                "callees": [],
                "fan_in": 0,
            },
        }

        result = await planner._classify_remaining(
            [("repo_a", "OrphanSvc")],
            ["payments"],
            enriched_signals=enriched,
        )

        assert result[("repo_a", "OrphanSvc")] == "payments"
        prompt = captured.get("prompt", "")
        assert "Base summary" in prompt
        assert "Handles orphan payment reconciliation" in prompt


class TestParallelCommunityNamingDedup:
    """AD-2: Top-level community naming coordinates used_names across parallel calls."""

    @pytest.mark.asyncio
    async def test_parallel_community_naming_dedups_colliding_slugs(self):
        modules = {
            "repo1": [
                _make_module_dict("repo1", "AlphaService"),
                _make_module_dict("repo1", "AlphaDao"),
                _make_module_dict("repo1", "BetaService"),
                _make_module_dict("repo1", "BetaDao"),
            ],
        }
        state = _make_state(modules)
        config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}
        edges = []

        namer = MagicMock()
        namer.name_community = AsyncMock(
            return_value={"slug": "shared-domain", "display_name": "Shared", "description": ""},
        )

        with patch(
            "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
            new_callable=AsyncMock,
            return_value=(edges, []),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            new_callable=AsyncMock,
            return_value=([
                {("repo1", "AlphaService"), ("repo1", "AlphaDao")},
                {("repo1", "BetaService"), ("repo1", "BetaDao")},
            ], None),
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=MagicMock(
                review_global_consistency=AsyncMock(
                    side_effect=lambda dm, dn, *_a, **_k: (dm, dn),
                ),
            ),
        ), patch(
            "wiki.nodes.graph_domain_decompose.acquire_llm_quota",
            new_callable=AsyncMock,
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        slugs = list(result["domain_mapping"].keys())
        assert len(slugs) == 2
        assert len(set(slugs)) == 2
        assert slugs.count("shared-domain") == 1
        assert any(s.startswith("shared-domain-") for s in slugs)


class TestEmbeddingMergeThresholdConfig:
    """AD-3: embedding merge threshold is configurable via settings."""

    @pytest.mark.asyncio
    async def test_custom_embedding_merge_threshold_from_settings(self, monkeypatch):
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
        emb_b = [0.9, 0.436]
        emb_c = [0.0, 1.0]

        mock_generator = MagicMock()
        mock_generator.generate = AsyncMock(return_value=[emb_a, emb_b, emb_c])
        monkeypatch.setattr(
            "core.config.get_settings",
            lambda: MagicMock(
                embedding=MagicMock(),
                wiki=MagicMock(embedding_merge_threshold=0.95),
            ),
        )
        monkeypatch.setattr(
            "indexer.embedding_generator.EmbeddingGenerator.shared",
            lambda _config: mock_generator,
        )

        result_mapping, _ = await _merge_domains_by_embedding(domain_mapping, domain_display)
        assert len(result_mapping) == 3


class TestPinnedModulesCompoundKeys:
    """AD-4: pinned_modules accepts repo|name compound keys."""

    def test_is_module_pinned_compound_key_scoped_to_repo(self):
        pinned = {"repo_a|UserService": "users"}
        assert is_module_pinned(pinned, "repo_a", "UserService") is True
        assert is_module_pinned(pinned, "repo_b", "UserService") is False

    def test_get_pinned_domain_slug_prefers_compound_key(self):
        pinned = {"repo_a|UserService": "users", "UserService": "legacy"}
        assert get_pinned_domain_slug(pinned, "repo_a", "UserService") == "users"
        assert get_pinned_domain_slug(pinned, "repo_b", "UserService") == "legacy"

    def test_assign_pinned_modules_compound_key_only_moves_matching_repo(self):
        modules = {
            "repo_a": [_make_module_dict("repo_a", "UserService")],
            "repo_b": [_make_module_dict("repo_b", "UserService")],
        }
        domain_mapping = {
            "misc": [
                ("repo_a", "UserService"),
                ("repo_b", "UserService"),
            ],
            "users-domain": [],
        }
        _assign_pinned_modules({"repo_a|UserService": "users-domain"}, modules, domain_mapping)

        users_pairs = domain_mapping.get("users-domain", [])
        misc_pairs = domain_mapping.get("misc", [])
        assert ("repo_a", "UserService") in users_pairs
        assert ("repo_b", "UserService") in misc_pairs
        assert ("repo_a", "UserService") not in misc_pairs

    @pytest.mark.asyncio
    async def test_compound_pin_excludes_only_matching_repo_from_clustering(self):
        modules = {
            "repo_a": [
                _make_module_dict("repo_a", "UserService"),
                _make_module_dict("repo_a", "OrderService"),
            ],
            "repo_b": [
                _make_module_dict("repo_b", "UserService"),
                _make_module_dict("repo_b", "BillingService"),
            ],
        }
        state = _make_state(
            modules,
            pinned_modules={"repo_a|UserService": "users-domain"},
        )
        config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

        clustered_modules: list[tuple[str, str]] = []

        async def _capture_clustering(biz_modules, *_args, **_kwargs):
            clustered_modules.extend(biz_modules)
            return [
                set(biz_modules[:2]) if len(biz_modules) >= 2 else set(biz_modules),
            ], None

        namer = MagicMock()

        async def _name_community(**kwargs):
            names = {i.get("name") for i in kwargs.get("module_infos", [])}
            if "OrderService" in names:
                return {"slug": "orders", "display_name": "Orders", "description": ""}
            return {"slug": "billing", "display_name": "Billing", "description": ""}

        namer.name_community = AsyncMock(side_effect=_name_community)

        with patch(
            "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
            new_callable=AsyncMock,
            return_value=([], []),
        ), patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            new_callable=AsyncMock,
            side_effect=_capture_clustering,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=namer,
        ), patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=MagicMock(
                review_global_consistency=AsyncMock(
                    side_effect=lambda dm, dn, *_a, **_k: (dm, dn),
                ),
            ),
        ), patch(
            "wiki.nodes.graph_domain_decompose.acquire_llm_quota",
            new_callable=AsyncMock,
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert ("repo_a", "UserService") not in clustered_modules
        assert ("repo_b", "UserService") in clustered_modules

        mapping = result["domain_mapping"]
        pinned_found = any(
            slug == "users-domain" and ("repo_a", "UserService") in pairs
            for slug, pairs in mapping.items()
        )
        assert pinned_found
