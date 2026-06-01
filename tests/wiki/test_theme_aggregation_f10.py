"""Tests for F10: theme aggregation wired into graph_domain_decompose pipeline."""
from __future__ import annotations

import json
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


def _make_state(modules: dict) -> dict:
    all_uids = [m["uid"] for repo_mods in modules.values() for m in repo_mods]
    return {
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


def _mock_reviewer():
    reviewer = MagicMock()
    reviewer.review = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return reviewer


def _sequential_namer(slug_pairs: list[tuple[str, str]]):
    """Return a namer that assigns slugs in order, one per community."""
    namer = MagicMock()
    counter = [0]

    async def _name_community(**_kwargs):
        idx = counter[0]
        counter[0] += 1
        slug, display = slug_pairs[idx]
        return {"slug": slug, "display_name": display, "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)
    return namer


def _six_domain_communities() -> list[set[tuple[str, str]]]:
    names = [
        "FamilyEventSvc",
        "FamilyTaskSvc",
        "GiftSvc",
        "PaymentSvc",
        "UserSvc",
        "AuthSvc",
    ]
    return [{( "repo1", n)} for n in names]


def _six_domain_slug_pairs() -> list[tuple[str, str]]:
    return [
        ("family-event-processing", "家族事件"),
        ("family-task", "家族关系"),
        ("gift-order", "礼物订单"),
        ("payment", "支付"),
        ("user", "用户"),
        ("auth", "认证"),
    ]


def _modules_for_six_domains() -> dict:
    return {
        "repo1": [_make_module_dict("repo1", n) for n, _ in zip(
            ["FamilyEventSvc", "FamilyTaskSvc", "GiftSvc", "PaymentSvc", "UserSvc", "AuthSvc"],
            range(6),
            strict=True,
        )],
    }


@contextmanager
def _pipeline_mocks(*, communities, slug_pairs):
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
            return_value=_sequential_namer(slug_pairs),
        ),
        patch(
            "wiki.nodes.graph_domain_decompose.DomainReviewAgent",
            return_value=_mock_reviewer(),
        ),
        patch("wiki.domain_stabilizer.DomainStabilizer"),
        patch(
            "wiki.nodes.graph_domain_decompose._structural_quality_check",
            return_value=[],
        ),
        patch(
            "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
            new_callable=AsyncMock,
            return_value=("acceptable", []),
        ),
    ]
    mocks = [p.start() for p in patches]
    mocks[4].return_value.stabilize = AsyncMock(return_value={})
    try:
        yield mocks
    finally:
        for p in patches:
            p.stop()


def _mock_wiki_settings(*, theme_aggregation_min_domains: int = 5):
    wiki = MagicMock()
    wiki.theme_aggregation_min_domains = theme_aggregation_min_domains
    wiki.skip_llm_merge_when_corrector_enabled = True
    wiki.infrastructure_slug_keywords = []
    wiki.domain_budget_max = 50
    wiki.term_overrides = {}
    settings = MagicMock()
    settings.wiki = wiki
    return settings


@pytest.mark.asyncio
async def test_theme_aggregation_in_pipeline():
    """When L1 domain count exceeds threshold, aggregate_domains_recursive runs."""
    modules = _modules_for_six_domains()
    state = _make_state(modules)
    llm = MagicMock()
    config = {"configurable": {"graph_store": MagicMock(), "llm": llm}}

    with (
        _pipeline_mocks(communities=_six_domain_communities(), slug_pairs=_six_domain_slug_pairs()),
        patch("wiki.nodes.graph_domain_decompose.get_settings", return_value=_mock_wiki_settings()),
        patch(
            "wiki.domain_merger.aggregate_domains_recursive",
            new_callable=AsyncMock,
            side_effect=lambda tree, _llm, **kw: tree,
        ) as mock_aggregate,
    ):
        await graph_driven_domain_decompose_node(state, config)

    mock_aggregate.assert_awaited_once()
    call_tree = mock_aggregate.await_args[0][0]
    assert len(call_tree) == 6


@pytest.mark.asyncio
async def test_theme_aggregation_skipped_below_threshold():
    """When L1 domain count is at or below threshold, aggregation is not invoked."""
    communities = _six_domain_communities()[:3]
    slug_pairs = _six_domain_slug_pairs()[:3]
    modules = {
        "repo1": [
            _make_module_dict("repo1", "FamilyEventSvc"),
            _make_module_dict("repo1", "FamilyTaskSvc"),
            _make_module_dict("repo1", "GiftSvc"),
        ],
    }
    state = _make_state(modules)
    llm = MagicMock()
    config = {"configurable": {"graph_store": MagicMock(), "llm": llm}}

    with (
        _pipeline_mocks(communities=communities, slug_pairs=slug_pairs),
        patch("wiki.nodes.graph_domain_decompose.get_settings", return_value=_mock_wiki_settings()),
        patch(
            "wiki.domain_merger.aggregate_domains_recursive",
            new_callable=AsyncMock,
        ) as mock_aggregate,
    ):
        await graph_driven_domain_decompose_node(state, config)

    mock_aggregate.assert_not_awaited()


@pytest.mark.asyncio
async def test_family_domains_aggregated_to_hub():
    """family-event-processing and family-task merge under a family L1 hub."""
    modules = _modules_for_six_domains()
    state = _make_state(modules)
    llm = AsyncMock()
    llm.generate = AsyncMock(
        return_value=json.dumps({
            "new_groups": [
                {
                    "parent_display_name": "家族",
                    "parent_slug": "family",
                    "children_slugs": ["family-event-processing", "family-task"],
                },
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order", "payment", "user", "auth"],
        }),
    )
    config = {"configurable": {"graph_store": MagicMock(), "llm": llm}}

    with (
        _pipeline_mocks(communities=_six_domain_communities(), slug_pairs=_six_domain_slug_pairs()),
        patch(
            "wiki.nodes.graph_domain_decompose.get_settings",
            return_value=_mock_wiki_settings(theme_aggregation_min_domains=5),
        ),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    tree = result["domain_tree"]
    top_names = [n["name"] for n in tree]
    assert "family" in top_names
    family_hub = next(n for n in tree if n["name"] == "family")
    child_names = {c["name"] for c in family_hub["children"]}
    assert child_names == {"family-event-processing", "family-task"}
    assert "gift-order" in top_names
