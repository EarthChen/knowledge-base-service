"""Tests for F9-C3/C4 helper wiring in graph_driven_domain_decompose_node."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

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
    domain_baseline: dict | None = None,
    anchored_slugs: set[str] | None = None,
    anchor_display_names: dict | None = None,
    embedding_cache: dict | None = None,
    is_incremental: bool = False,
    existing_domain_mapping: dict | None = None,
    affected_modules: list[str] | None = None,
) -> dict:
    all_uids = [m["uid"] for repo_mods in modules.values() for m in repo_mods]
    state: dict = {
        "business_id": "test-biz",
        "repositories": list(modules.keys()),
        "modules": modules,
        "entity_roles": {uid: "has_business_logic" for uid in all_uids},
        "is_incremental": is_incremental,
        "existing_domain_mapping": existing_domain_mapping or {},
        "affected_modules": affected_modules or [],
        "domain_mapping": {},
        "domain_tree": None,
        "affected_domains": [],
    }
    if domain_baseline is not None:
        state["domain_baseline"] = domain_baseline
    if anchored_slugs is not None:
        state["anchored_slugs"] = anchored_slugs
    if anchor_display_names is not None:
        state["anchor_display_names"] = anchor_display_names
    if embedding_cache is not None:
        state["embedding_cache"] = embedding_cache
    return state


def _mock_reviewer():
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return reviewer


def _mock_namer(slug: str = "auth-domain", display: str = "认证"):
    namer = MagicMock()

    async def _name_community(**_kwargs):
        return {"slug": slug, "display_name": display, "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)
    return namer


@contextmanager
def _full_clustering_mocks(*, communities=None):
    """Patch heavy deps so graph_driven_domain_decompose_node takes the full path."""
    if communities is None:
        communities = [{("repo1", "UserService"), ("repo1", "AuthService")}]
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
            return_value=_mock_namer(),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose.DomainReviewAgent",
            return_value=_mock_reviewer(),
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


@pytest.mark.asyncio
async def test_full_path_calls_structural_quality_check():
    """Full clustering path runs structural quality check after corrector."""
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
        ) as mock_struct,
        patch(
            "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
            new_callable=AsyncMock,
            return_value=("acceptable", []),
        ),
    ):
        await graph_driven_domain_decompose_node(state, config)
        mock_struct.assert_called_once()


@pytest.mark.asyncio
async def test_full_path_calls_agent_review():
    """Full clustering path invokes agent semantic review when LLM is available."""
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
        patch(
            "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
            new_callable=AsyncMock,
            return_value=("good", []),
        ) as mock_agent,
    ):
        await graph_driven_domain_decompose_node(state, config)
        mock_agent.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_path_quality_gate_fallback_to_baseline():
    """When quality gate fails and baseline exists, mapping reverts to baseline."""
    modules = {
        "repo1": [
            _make_module_dict("repo1", "UserService"),
            _make_module_dict("repo1", "AuthService"),
            _make_module_dict("repo1", "NewModule"),
        ],
    }
    baseline = {
        "auth": [("repo1", "UserService")],
        "payment": [("repo1", "PayService")],
    }
    state = _make_state(
        modules,
        domain_baseline=baseline,
        embedding_cache={"NewModule": [1.0, 0.0, 0.0], "UserService": [0.9, 0.1, 0.0]},
    )
    config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

    with (
        _full_clustering_mocks(
            communities=[{("repo1", "UserService"), ("repo1", "AuthService"), ("repo1", "NewModule")}],
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._structural_quality_check",
            return_value=[],
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
            new_callable=AsyncMock,
            return_value=("needs_revision", ["AGENT_REVIEW(warning): auth — test"]),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._domain_decomposition_quality_check",
            return_value=(True, []),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._assign_new_modules_to_nearest",
        ) as mock_assign,
    ):
        result = await graph_driven_domain_decompose_node(state, config)

        assert result["domain_mapping"]["auth"] == [("repo1", "UserService")]
        assert result["domain_mapping"]["payment"] == [("repo1", "PayService")]
        mock_assign.assert_called_once()


@pytest.mark.asyncio
async def test_full_path_domain_recovery():
    """Anchored domains missing from HAC output are recovered from persistence."""
    modules = {
        "repo1": [
            _make_module_dict("repo1", "UserService"),
            _make_module_dict("repo1", "AuthService"),
        ],
    }
    persistence = AsyncMock()
    persistence.list_domain_modules = AsyncMock(
        return_value=[
            {"repository": "repo1", "module_name": "FamilyService"},
            {"repository": "repo1", "module_name": "FamilyMemberService"},
        ],
    )
    state = _make_state(
        modules,
        anchored_slugs={"family-core"},
        anchor_display_names={"family-core": "家族核心"},
    )
    config = {
        "configurable": {
            "graph_store": MagicMock(),
            "llm": None,
            "persistence": persistence,
        },
    }

    with (
        _full_clustering_mocks(),
        patch(
            "wiki.nodes.graph_domain_decompose._structural_quality_check",
            return_value=[],
        ),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    assert "family-core" in result["domain_mapping"]
    assert len(result["domain_mapping"]["family-core"]) == 2
    assert result["domain_display_names"]["family-core"] == "家族核心"
    persistence.list_domain_modules.assert_awaited_once_with("test-biz", "family-core")


@pytest.mark.asyncio
async def test_incremental_no_quality_gate():
    """Incremental path skips quality gate and agent review."""
    modules = {
        "repo1": [
            _make_module_dict("repo1", "FamilyService"),
            _make_module_dict("repo1", "FamilyDao"),
        ],
    }
    existing_mapping = {
        "family-domain": [("repo1", "FamilyService"), ("repo1", "FamilyDao")],
    }
    state = _make_state(
        modules,
        is_incremental=True,
        existing_domain_mapping=existing_mapping,
        affected_modules=[],
    )
    config = {"configurable": {"graph_store": MagicMock(), "llm": MagicMock()}}

    with (
        patch(
            "wiki.nodes.graph_domain_decompose._structural_quality_check",
            return_value=[],
        ) as mock_struct,
        patch(
            "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
            new_callable=AsyncMock,
            return_value=("good", []),
        ) as mock_agent,
        patch(
            "wiki.nodes.graph_domain_decompose._domain_decomposition_quality_check",
            return_value=(True, []),
        ) as mock_baseline,
    ):
        await graph_driven_domain_decompose_node(state, config)

    mock_struct.assert_not_called()
    mock_agent.assert_not_awaited()
    mock_baseline.assert_not_called()
