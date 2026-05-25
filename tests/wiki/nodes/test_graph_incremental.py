"""Test incremental graph domain decomposition."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.nodes.graph_domain_decompose import graph_driven_domain_decompose_node


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


def _make_state(
    modules: dict,
    *,
    entity_roles: dict | None = None,
    is_incremental: bool = False,
    existing_domain_mapping: dict | None = None,
    affected_modules: list[str] | None = None,
    pinned_modules: dict[str, str] | None = None,
    domain_tree: list | None = None,
):
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
        "is_incremental": is_incremental,
        "existing_domain_mapping": existing_domain_mapping or {},
        "affected_modules": affected_modules or [],
        "pinned_modules": pinned_modules or {},
        "domain_tree": domain_tree,
        "domain_mapping": {},
        "affected_domains": [],
    }


def _mock_corrector():
    corrector = MagicMock()
    corrector.review_global_consistency = AsyncMock(
        side_effect=lambda dm, dn, *_args, **_kw: (dm, dn),
    )
    return corrector


def _mock_namer():
    namer = MagicMock()
    _call_counter = [0]

    async def _name_community(**kwargs):
        infos = kwargs.get("module_infos") or []
        names = [i.get("name", "") for i in infos]
        _call_counter[0] += 1
        slug_base = names[0].lower().replace("service", "") if names else "unnamed"
        slug = f"{slug_base}-{_call_counter[0]}"
        return {"slug": slug, "display_name": f"域{_call_counter[0]}", "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)
    return namer


def _edge_tuple(source: str, target: str, weight: int = 10, repo: str = "repo1"):
    return ((repo, source), (repo, target), weight)


@pytest.mark.asyncio
async def test_incremental_no_changes_preserves_mapping():
    """When no affected_modules, existing mapping is preserved."""
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
        domain_tree=[{"name": "family-domain", "modules": ["FamilyService", "FamilyDao"], "children": []}],
    )

    mock_graph_store = MagicMock()
    config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}

    with patch(
        "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
        new_callable=AsyncMock,
        return_value=([], []),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    assert result["domain_mapping"] == existing_mapping
    assert result["affected_domains"] == []
    assert result["domain_tree"] == state["domain_tree"]


@pytest.mark.asyncio
async def test_incremental_new_module_assigned_via_edge():
    """New module is assigned to domain of its call-edge neighbor."""
    modules = {
        "repo1": [
            _make_module_dict("repo1", "FamilyService"),
            _make_module_dict("repo1", "FamilyDao"),
            _make_module_dict("repo1", "NewHelper"),
        ],
    }
    existing_mapping = {
        "family-domain": [("repo1", "FamilyService"), ("repo1", "FamilyDao")],
    }
    state = _make_state(
        modules,
        is_incremental=True,
        existing_domain_mapping=existing_mapping,
        affected_modules=["NewHelper"],
    )

    mock_graph_store = MagicMock()
    config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
    edges = [
        _edge_tuple("NewHelper", "FamilyService", 15),
    ]

    with patch(
        "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
        new_callable=AsyncMock,
        return_value=(edges, []),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    mapping = result["domain_mapping"]
    family_mods = [name for _, name in mapping["family-domain"]]
    assert "NewHelper" in family_mods
    assert "family-domain" in result["affected_domains"]


@pytest.mark.asyncio
async def test_pinned_modules_forced_to_target_domain():
    """Pinned modules bypass clustering and go to specified domain."""
    modules = {
        "repo1": [
            _make_module_dict("repo1", "FamilyService"),
            _make_module_dict("repo1", "FamilyDao"),
            _make_module_dict("repo1", "PinnedSvc"),
            _make_module_dict("repo1", "IntimacyService"),
            _make_module_dict("repo1", "IntimacyDao"),
        ],
    }
    state = _make_state(
        modules,
        pinned_modules={"PinnedSvc": "family-domain"},
    )

    mock_graph_store = MagicMock()
    config = {"configurable": {"graph_store": mock_graph_store, "llm": MagicMock()}}
    edges = [
        _edge_tuple("FamilyService", "FamilyDao", 10),
        _edge_tuple("IntimacyService", "IntimacyDao", 12),
    ]

    namer = MagicMock()

    async def _name_community(**kwargs):
        infos = kwargs.get("module_infos") or []
        names = {i.get("name", "") for i in infos}
        if "FamilyService" in names:
            return {"slug": "family-domain", "display_name": "Family", "description": ""}
        return {"slug": "intimacy-domain", "display_name": "Intimacy", "description": ""}

    namer.name_community = AsyncMock(side_effect=_name_community)

    with patch(
        "wiki.nodes.graph_domain_decompose.fetch_module_call_edges",
        new_callable=AsyncMock,
        return_value=(edges, []),
    ), patch(
        "wiki.nodes.graph_domain_decompose._embedding_clustering",
        new_callable=AsyncMock,
        return_value=([
            {("repo1", "FamilyService"), ("repo1", "FamilyDao")},
            {("repo1", "IntimacyService"), ("repo1", "IntimacyDao")},
        ], None),
    ), patch(
        "wiki.nodes.graph_domain_decompose.GraphDomainNamer",
        return_value=namer,
    ), patch(
        "wiki.nodes.graph_domain_decompose.GraphSemanticCorrector",
        return_value=_mock_corrector(),
    ):
        result = await graph_driven_domain_decompose_node(state, config)

    mapping = result["domain_mapping"]
    pinned_found = False
    for slug, pairs in mapping.items():
        mod_names = [name for _, name in pairs]
        if "PinnedSvc" in mod_names:
            assert slug == "family-domain"
            pinned_found = True
    assert pinned_found
