"""Tests for GraphDomainNamer fingerprint cache (N1 — naming stability)."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.graph_domain_namer import GraphDomainNamer
from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node
from wiki.persistence import compute_domain_module_signature


def _module_infos(repo: str = "repo1") -> list[dict[str, str]]:
    return [
        {"repository": repo, "name": "FriendService", "path": "friend/service/"},
        {"repository": repo, "name": "FriendDao", "path": "friend/dao/"},
    ]


def _module_signature(repo: str = "repo1") -> str:
    return compute_domain_module_signature([
        (repo, "FriendDao"),
        (repo, "FriendService"),
    ])


@pytest.mark.asyncio
async def test_namer_cache_hit_skips_llm():
    cached = {"slug": "friend-relation", "display_name": "好友关系", "description": "cached desc"}
    sig = _module_signature()
    mock_llm = AsyncMock()
    namer = GraphDomainNamer(mock_llm, naming_cache={sig: cached})

    result = await namer.name_community(module_infos=_module_infos())

    assert result == cached
    mock_llm.generate.assert_not_called()


@pytest.mark.asyncio
async def test_namer_cache_miss_calls_llm_and_stores():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"slug": "friend-relation", "display_name": "好友关系", "description": "fresh"}'
    )
    naming_cache: dict[str, dict[str, str]] = {}
    namer = GraphDomainNamer(mock_llm, naming_cache=naming_cache)

    result = await namer.name_community(module_infos=_module_infos())

    mock_llm.generate.assert_awaited_once()
    assert result["slug"] == "friend-relation"
    assert len(naming_cache) == 1
    assert list(naming_cache.values())[0]["slug"] == "friend-relation"


@pytest.mark.asyncio
async def test_namer_cache_key_is_module_signature():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"slug": "friend-relation", "display_name": "好友关系", "description": ""}'
    )
    naming_cache: dict[str, dict[str, str]] = {}
    namer = GraphDomainNamer(mock_llm, naming_cache=naming_cache)

    await namer.name_community(module_infos=_module_infos())

    assert _module_signature() in naming_cache


@pytest.mark.asyncio
async def test_namer_cache_order_independent():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"slug": "friend-relation", "display_name": "好友关系", "description": ""}'
    )
    naming_cache: dict[str, dict[str, str]] = {}
    namer = GraphDomainNamer(mock_llm, naming_cache=naming_cache)

    ordered_a = [
        {"repository": "repo1", "name": "FriendService"},
        {"repository": "repo1", "name": "FriendDao"},
    ]
    ordered_b = list(reversed(ordered_a))

    await namer.name_community(module_infos=ordered_a)
    assert mock_llm.generate.await_count == 1

    result = await namer.name_community(module_infos=ordered_b)
    assert mock_llm.generate.await_count == 1
    assert result["slug"] == "friend-relation"


@pytest.mark.asyncio
async def test_namer_without_cache_still_works():
    mock_llm = AsyncMock()
    mock_llm.generate = AsyncMock(
        return_value='{"slug": "test-slug", "display_name": "测试", "description": ""}'
    )
    namer = GraphDomainNamer(mock_llm)

    result = await namer.name_community(module_names=["FooService", "BarHandler"])

    assert result["slug"] == "test-slug"
    mock_llm.generate.assert_awaited_once()


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


def _make_state(modules: dict, *, naming_cache: dict | None = None) -> dict:
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
    if naming_cache is not None:
        state["naming_cache"] = naming_cache
    return state


@contextmanager
def _full_clustering_mocks(*, communities=None, llm=None):
    if communities is None:
        communities = [{("repo1", "UserService"), ("repo1", "AuthService")}]
    if llm is None:
        llm = MagicMock()
        llm.generate = AsyncMock(
            return_value='{"slug": "auth-domain", "display_name": "认证", "description": ""}'
        )

    reviewer = MagicMock()
    reviewer.review = AsyncMock(side_effect=lambda dm, dn, *_a, **_k: (dm, dn))

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
        patch("wiki.domain_stabilizer.DomainStabilizer"),
    ]
    started = [p.start() for p in patches]
    started[2].return_value.stabilize = AsyncMock(return_value={})
    try:
        yield llm
    finally:
        for p in patches:
            p.stop()


@pytest.mark.asyncio
async def test_namer_cache_persisted_in_pipeline_state():
    modules = {
        "repo1": [
            _make_module_dict("repo1", "UserService"),
            _make_module_dict("repo1", "AuthService"),
        ],
    }
    naming_cache: dict[str, dict[str, str]] = {}
    state = _make_state(modules, naming_cache=naming_cache)
    config = {"configurable": {"graph_store": MagicMock(), "llm": None}}

    with _full_clustering_mocks() as mock_llm:
        config["configurable"]["llm"] = mock_llm
        with (
            patch(
                "wiki.nodes.graph_domain_decompose._structural_quality_check",
                return_value=[],
            ),
            patch(
                "wiki.nodes.graph_domain_decompose._agent_review_decomposition",
                new_callable=AsyncMock,
                return_value=("acceptable", []),
            ),
            patch(
                "wiki.nodes.graph_domain_decompose.DomainReviewAgent",
                return_value=MagicMock(review=AsyncMock(side_effect=lambda dm, dn, *_a, **_k: (dm, dn))),
            ),
        ):
            result = await graph_driven_domain_decompose_node(state, config)

    assert "naming_cache" in result
    assert len(result["naming_cache"]) >= 1
