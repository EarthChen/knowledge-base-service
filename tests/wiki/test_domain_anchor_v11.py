"""Tests for F7-R: DomainAnchor optional incremental protection."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.graph_semantic_corrector import GraphSemanticCorrector
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node


def _make_module_dict(repo_id: str, name: str) -> dict:
    return {
        "uid": f"Module::{name}:0",
        "label": "Module",
        "properties": {
            "name": name,
            "path": f"src/{name}.java",
            "repository": repo_id,
        },
    }


def _make_state(
    modules: dict,
    *,
    anchor_service: AsyncMock | None = None,
    anchored_slugs: set[str] | None = None,
) -> dict:
    all_uids = [m["uid"] for repo_mods in modules.values() for m in repo_mods]
    state: dict = {
        "business_id": "test-biz",
        "repositories": list(modules.keys()),
        "modules": modules,
        "entity_roles": {uid: "has_business_logic" for uid in all_uids},
        "is_incremental": False,
        "existing_domain_mapping": {},
        "affected_modules": [],
        "domain_mapping": {},
        "domain_tree": None,
        "affected_domains": [],
    }
    if anchor_service is not None:
        state["anchor_service"] = anchor_service
    if anchored_slugs is not None:
        state["anchored_slugs"] = anchored_slugs
    return state


def _mock_corrector():
    corrector = MagicMock()
    corrector.review_global_consistency = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return corrector


def _mock_namer(slug: str = "auth-domain", display: str = "认证"):
    namer = MagicMock()

    async def _name_community(**_kwargs):
        return {"slug": slug, "display_name": display, "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)
    return namer


@contextmanager
def _full_clustering_mocks(*, communities=None, namer=None):
    if communities is None:
        communities = [{("repo1", "UserService"), ("repo1", "AuthService")}]
    if namer is None:
        namer = _mock_namer()
    patches = [
        patch(
            "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
            new_callable=AsyncMock,
            return_value=([], []),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._embedding_clustering",
            new_callable=AsyncMock,
            return_value=(communities, None),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
            return_value=namer,
        ),
        patch(
            "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
            return_value=_mock_corrector(),
        ),
        patch("wiki.domain_stabilizer.DomainStabilizer"),
    ]
    mocks = [p.start() for p in patches]
    mocks[4].return_value.stabilize = AsyncMock(return_value={})
    try:
        yield mocks
    finally:
        for p in patches:
            p.stop()


def _make_review_llm():
    llm = AsyncMock(spec=["complete_json"])
    llm.complete_json = AsyncMock(return_value={"merges": [], "renames": [], "moves": [], "summary": ""})
    return llm


def _get_prompt(llm):
    messages = llm.complete_json.call_args[0][0]
    return next(m["content"] for m in messages if m["role"] == "user")


class TestNoAnchorFreshGeneration:
    @pytest.mark.asyncio
    async def test_no_anchor_fresh_generation_works(self):
        """No anchor_service or empty anchors → normal flow unaffected."""
        modules = {
            "repo1": [
                _make_module_dict("repo1", "UserService"),
                _make_module_dict("repo1", "AuthService"),
            ],
        }
        state = _make_state(modules)
        config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

        with (
            _full_clustering_mocks(),
            patch(
                "wiki.nodes.graph_domain_decompose._structural_quality_check",
                return_value=[],
            ),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_mapping"]
        assert "auth-domain" in result["domain_mapping"]

    @pytest.mark.asyncio
    async def test_empty_anchor_service_returns_empty(self):
        """anchor_service present but get_anchors returns [] → no protection applied."""
        anchor = MagicMock()
        anchor.slug = "family-core"
        anchor_service = AsyncMock()
        anchor_service.get_anchors = AsyncMock(return_value=[])

        modules = {
            "repo1": [
                _make_module_dict("repo1", "UserService"),
                _make_module_dict("repo1", "AuthService"),
            ],
        }
        state = _make_state(modules, anchor_service=anchor_service)
        config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}
        corrector_instance = _mock_corrector()

        with (
            _full_clustering_mocks(),
            patch(
                "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
                return_value=corrector_instance,
            ),
            patch(
                "wiki.nodes.graph_domain_decompose._structural_quality_check",
                return_value=[],
            ),
        ):
            await graph_driven_domain_decompose_node(state, config)

        _, kwargs = corrector_instance.review_global_consistency.call_args
        assert kwargs.get("anchored_slugs") == frozenset()


class TestAnchorPreventsDomainMerge:
    @pytest.mark.asyncio
    async def test_anchor_prevents_domain_merge(self):
        """anchored_slugs contains a domain → corrector does not merge that domain."""
        llm = _make_review_llm()
        llm.complete_json = AsyncMock(
            return_value={
                "merges": [
                    {
                        "sources": ["family-core", "family-tasks"],
                        "target": "family-core",
                        "new_display_name": "家族",
                        "reason": "same business",
                    }
                ],
                "renames": [],
                "moves": [],
                "summary": "",
            },
        )
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "family-core": [("r", "FamilyService")],
            "family-tasks": [("r", "FamilyTaskService")],
        }
        domain_display = {"family-core": "家族核心", "family-tasks": "家族任务"}

        new_mapping, _ = await corrector.review_global_consistency(
            domain_mapping,
            domain_display,
            module_paths={},
            module_summaries={},
            anchored_slugs=frozenset({"family-tasks"}),
        )

        assert "family-core" in new_mapping
        assert "family-tasks" in new_mapping
        assert new_mapping["family-core"] == [("r", "FamilyService")]
        assert new_mapping["family-tasks"] == [("r", "FamilyTaskService")]


class TestAnchoredDomainMissingLogged:
    @pytest.mark.asyncio
    async def test_anchored_domain_missing_logged(self):
        """Clustering result missing anchored domain → warning logged."""
        anchor = MagicMock()
        anchor.slug = "family-core"
        anchor_service = AsyncMock()
        anchor_service.get_anchors = AsyncMock(return_value=[anchor])

        modules = {
            "repo1": [
                _make_module_dict("repo1", "UserService"),
                _make_module_dict("repo1", "AuthService"),
            ],
        }
        state = _make_state(modules, anchor_service=anchor_service)
        config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

        with (
            _full_clustering_mocks(namer=_mock_namer(slug="auth-domain")),
            patch(
                "wiki.nodes.graph_domain_decompose._structural_quality_check",
                return_value=[],
            ),
            patch("wiki.nodes.graph_domain_decompose.log") as mock_log,
        ):
            await graph_driven_domain_decompose_node(state, config)

        warning_calls = [
            c for c in mock_log.warning.call_args_list
            if c[0] and c[0][0] == "anchored_domain_missing_after_cluster"
        ]
        assert len(warning_calls) == 1
        assert warning_calls[0][1]["slug"] == "family-core"


class TestAnchorConstraintInPrompt:
    @pytest.mark.asyncio
    async def test_anchor_constraint_in_prompt(self):
        """When anchored_slugs is set → prompt contains CRITICAL protection instruction."""
        llm = _make_review_llm()
        corrector = GraphSemanticCorrector(llm)
        domain_mapping = {
            "family-core": [("r", "FamilyService")],
            "payment": [("r", "PayService")],
        }
        domain_display = {"family-core": "家族核心", "payment": "支付"}

        await corrector.review_global_consistency(
            domain_mapping,
            domain_display,
            module_paths={},
            module_summaries={},
            anchored_slugs=frozenset({"family-core", "payment"}),
        )

        prompt = _get_prompt(llm)
        assert "CRITICAL" in prompt
        assert "family-core" in prompt
        assert "payment" in prompt
        assert "MUST NOT be merged or removed" in prompt
