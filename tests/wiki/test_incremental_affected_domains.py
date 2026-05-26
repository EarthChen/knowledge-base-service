# tests/wiki/test_incremental_affected_domains.py
"""Tests for P0.1: incremental generation uses affected_domains to filter compose."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.pipeline_nodes import compose_leaf_pages_node


class TestClassifyIncrementalReturnsAffected:
    @pytest.mark.asyncio
    async def test_returns_tuple_with_affected_set(self):
        """classify_incremental should return (mapping, affected_domains)."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        existing_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "OldService", "business_domain": "Payment"},
            uid="Module::OldService:0",
        )
        new_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "NewService"},
            uid="Module::NewService:0",
        )

        all_modules = {"repo1": [existing_mod, new_mod]}

        with patch.object(planner, "_triage_new_modules") as mock_triage:
            from wiki.cross_repo_domain_planner import _TriageResult

            mock_triage.return_value = _TriageResult(
                assignments={("repo1", "NewService"): "Payment"},
                new_domains={},
                reclassify_domains=[],
            )

            result = await planner.classify_incremental("biz1", all_modules)

        assert isinstance(result, tuple), f"Expected tuple, got {type(result)}"
        assert len(result) == 2
        mapping, affected = result
        assert isinstance(mapping, dict)
        assert isinstance(affected, set)
        assert "Payment" in affected

    @pytest.mark.asyncio
    async def test_no_new_modules_returns_empty_affected(self):
        """When no new modules, affected_domains should be empty."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        existing_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "OldService", "business_domain": "Payment"},
            uid="Module::OldService:0",
        )

        result = await planner.classify_incremental("biz1", {"repo1": [existing_mod]})

        assert isinstance(result, tuple)
        mapping, affected = result
        assert affected == set()

    @pytest.mark.asyncio
    async def test_new_domain_in_affected(self):
        """New domains created during triage should be in affected set."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        new_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "BrandNew"},
            uid="Module::BrandNew:0",
        )

        with patch.object(planner, "_triage_new_modules") as mock_triage:
            from wiki.cross_repo_domain_planner import _TriageResult

            mock_triage.return_value = _TriageResult(
                assignments={},
                new_domains={"NewDomain": [("repo1", "BrandNew")]},
                reclassify_domains=[],
            )

            result = await planner.classify_incremental("biz1", {"repo1": [new_mod]})

        mapping, affected = result
        assert "NewDomain" in affected

    @pytest.mark.asyncio
    async def test_reclassify_domains_in_affected(self):
        """Reclassified domains should be in affected set."""
        llm = AsyncMock()
        planner = CrossRepoBusinessDomainPlanner(llm)

        from store.schema import GraphNode, NodeLabel

        existing_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "OldService", "business_domain": "Payment"},
            uid="Module::OldService:0",
        )
        new_mod = GraphNode(
            label=NodeLabel.MODULE,
            properties={"name": "NewService"},
            uid="Module::NewService:0",
        )

        with (
            patch.object(planner, "_triage_new_modules") as mock_triage,
            patch.object(planner, "_reclassify_affected_domains") as mock_reclass,
        ):
            from wiki.cross_repo_domain_planner import _TriageResult

            mock_triage.return_value = _TriageResult(
                assignments={},
                new_domains={},
                reclassify_domains=["Payment"],
            )
            mock_reclass.return_value = {
                "Payment-v2": [("repo1", "OldService"), ("repo1", "NewService")]
            }

            result = await planner.classify_incremental("biz1", {"repo1": [existing_mod, new_mod]})

        mapping, affected = result
        assert "Payment" in affected
        assert "Payment-v2" in affected


@pytest.mark.filterwarnings("ignore::DeprecationWarning")
class TestComposeLeafPagesFiltering:
    """compose_leaf_pages_node should include nested leaves whose parent is affected."""

    @pytest.mark.asyncio
    async def test_light_reorg_includes_child_of_affected_parent(self):
        """Leaves under an affected parent domain should be included."""
        state = {
            "domain_tree": [
                {
                    "name": "Payment",
                    "modules": [],
                    "children": [
                        {"name": "PaymentCore", "modules": ["PaySvc"], "children": []},
                        {"name": "PaymentGateway", "modules": ["GatewaySvc"], "children": []},
                    ],
                },
                {"name": "Meeting", "modules": ["MeetSvc"], "children": []},
            ],
            "domain_mapping": {
                "Payment": [("r", "PaySvc"), ("r", "GatewaySvc")],
                "Meeting": [("r", "MeetSvc")],
            },
            "modules": {"r": [
                {"uid": "m1", "label": "Module", "properties": {"name": "PaySvc", "path": "a.java"}},
                {"uid": "m2", "label": "Module", "properties": {"name": "GatewaySvc", "path": "b.java"}},
                {"uid": "m3", "label": "Module", "properties": {"name": "MeetSvc", "path": "c.java"}},
            ]},
            "entity_roles": {},
            "module_summaries": {},
            "reorg_type": "light",
            "affected_domains": ["Payment"],
        }

        config = {"configurable": {"llm": AsyncMock(), "graph_store": None, "wiki_store": None}}

        with patch("wiki.pipeline_nodes._compose_single_leaf_domain") as mock_compose:
            mock_compose.return_value = ([], [])
            await compose_leaf_pages_node(state, config)

        composed_names = [call.args[0]["name"] for call in mock_compose.call_args_list]
        # Small leaves (<3 modules) merge at compose; PaymentCore absorbs siblings + Meeting.
        assert composed_names == ["PaymentCore"]
        merged_modules = set(mock_compose.call_args_list[0].args[0]["modules"])
        assert merged_modules == {"PaySvc", "GatewaySvc", "MeetSvc"}
        assert "PaymentGateway" not in composed_names
        assert "Meeting" not in composed_names

    @pytest.mark.asyncio
    async def test_light_reorg_direct_leaf_match(self):
        """Flat leaf domains directly matching affected_domains should be included."""
        state = {
            "domain_tree": [
                {"name": "Payment", "modules": ["PaySvc"], "children": []},
                {"name": "Meeting", "modules": ["MeetSvc"], "children": []},
            ],
            "domain_mapping": {
                "Payment": [("r", "PaySvc")],
                "Meeting": [("r", "MeetSvc")],
            },
            "modules": {"r": [
                {"uid": "m1", "label": "Module", "properties": {"name": "PaySvc", "path": "a.java"}},
                {"uid": "m2", "label": "Module", "properties": {"name": "MeetSvc", "path": "b.java"}},
            ]},
            "entity_roles": {},
            "module_summaries": {},
            "reorg_type": "light",
            "affected_domains": ["Payment"],
        }

        config = {"configurable": {"llm": AsyncMock(), "graph_store": None, "wiki_store": None}}

        with patch("wiki.pipeline_nodes._compose_single_leaf_domain") as mock_compose:
            mock_compose.return_value = ([], [])
            await compose_leaf_pages_node(state, config)

        composed_names = [call.args[0]["name"] for call in mock_compose.call_args_list]
        assert "Payment" in composed_names
        assert "Meeting" not in composed_names
