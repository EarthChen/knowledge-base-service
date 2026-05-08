# tests/wiki/test_decompose_rebalance.py
"""Tests for P0.2 Sub-B+C: oversized leaf detection and secondary decomposition."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from wiki.pipeline_nodes import _detect_oversized_leaves, decompose_hierarchy_node


class TestDetectOversizedLeaves:
    def test_no_oversized(self):
        tree = [
            {"name": "Small", "modules": ["A", "B", "C"], "children": []},
        ]
        result = _detect_oversized_leaves(tree)
        assert result == []

    def test_detects_oversized(self):
        tree = [
            {"name": "Big", "modules": [f"M{i}" for i in range(20)], "children": []},
            {"name": "Small", "modules": ["A"], "children": []},
        ]
        result = _detect_oversized_leaves(tree)
        assert len(result) == 1
        assert result[0]["name"] == "Big"

    def test_nested_leaf_detected(self):
        tree = [
            {
                "name": "Parent",
                "modules": [],
                "children": [
                    {"name": "BigChild", "modules": [f"M{i}" for i in range(20)], "children": []},
                ],
            },
        ]
        result = _detect_oversized_leaves(tree)
        assert len(result) == 1
        assert result[0]["name"] == "BigChild"


class TestDecomposeRebalance:
    @pytest.mark.asyncio
    async def test_small_leaf_not_rebalanced(self):
        """Leaf with <= 15 modules should not trigger rebalancing."""
        state = {
            "domain_mapping": {"SmallDomain": [("repo1", f"M{i}") for i in range(10)]},
            "modules": {"repo1": [
                {"uid": f"Module::M{i}:0", "label": "Module", "properties": {"name": f"M{i}", "path": f"src/M{i}.java"}}
                for i in range(10)
            ]},
        }

        from wiki.dependency_graph import DomainNode, ModuleInfo

        main_modules = [ModuleInfo(name=f"M{i}", path=f"src/M{i}.java", uid=f"Module::M{i}:0") for i in range(10)]
        main_result = [DomainNode(name="SmallDomain", description="small", modules=main_modules, children=[])]

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as mock_hd:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(return_value=main_result)
            mock_hd.return_value = mock_instance

            config = {"configurable": {"llm": AsyncMock()}}
            result = await decompose_hierarchy_node(state, config)

        tree = result["domain_tree"]
        domain = next(d for d in tree if d["name"] == "SmallDomain")
        assert domain["children"] == [] or not domain.get("children")
        # HierarchicalDecomposer should only be instantiated once (for main decomposition)
        assert mock_hd.call_count == 1

    @pytest.mark.asyncio
    async def test_large_leaf_triggers_rebalance(self):
        """Leaf with > 15 modules should be split into sub-domains."""
        state = {
            "domain_mapping": {"BigDomain": [("repo1", f"M{i}") for i in range(20)]},
            "modules": {"repo1": [
                {"uid": f"Module::M{i}:0", "label": "Module", "properties": {"name": f"M{i}", "path": f"src/M{i}.java"}}
                for i in range(20)
            ]},
        }

        from wiki.dependency_graph import DomainNode, ModuleInfo

        all_mods = [ModuleInfo(name=f"M{i}", path=f"src/M{i}.java", uid=f"Module::M{i}:0") for i in range(20)]

        main_result = [DomainNode(name="BigDomain", description="big", modules=all_mods, children=[])]
        sub_result = [
            DomainNode(name="SubA", description="sub a", modules=all_mods[:10], children=[]),
            DomainNode(name="SubB", description="sub b", modules=all_mods[10:], children=[]),
        ]

        call_count = {"n": 0}

        async def side_effect(mods, graph):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_result
            return sub_result

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as mock_hd:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(side_effect=side_effect)
            mock_hd.return_value = mock_instance

            config = {"configurable": {"llm": AsyncMock()}}
            result = await decompose_hierarchy_node(state, config)

        tree = result["domain_tree"]
        big = next(d for d in tree if d["name"] == "BigDomain")
        assert len(big["children"]) == 2
        # Modules should have moved to children
        assert big["modules"] == []

    @pytest.mark.asyncio
    async def test_rebalance_failure_preserves_original(self):
        """If rebalance LLM call fails, keep the original oversized leaf."""
        state = {
            "domain_mapping": {"BigDomain": [("repo1", f"M{i}") for i in range(20)]},
            "modules": {"repo1": [
                {"uid": f"Module::M{i}:0", "label": "Module", "properties": {"name": f"M{i}", "path": f"src/M{i}.java"}}
                for i in range(20)
            ]},
        }

        from wiki.dependency_graph import DomainNode, ModuleInfo

        all_mods = [ModuleInfo(name=f"M{i}", path=f"src/M{i}.java", uid=f"Module::M{i}:0") for i in range(20)]
        main_result = [DomainNode(name="BigDomain", description="big", modules=all_mods, children=[])]

        call_count = {"n": 0}

        async def side_effect(mods, graph):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_result
            raise RuntimeError("LLM failed")

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as mock_hd:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(side_effect=side_effect)
            mock_hd.return_value = mock_instance

            config = {"configurable": {"llm": AsyncMock()}}
            result = await decompose_hierarchy_node(state, config)

        tree = result["domain_tree"]
        big = next(d for d in tree if d["name"] == "BigDomain")
        # Original structure preserved — still has modules, no children
        assert len(big.get("modules", [])) == 20
        assert big.get("children") == [] or not big.get("children")

    @pytest.mark.asyncio
    async def test_single_sub_result_no_split(self):
        """If rebalance returns only 1 sub-domain, don't split (no benefit)."""
        state = {
            "domain_mapping": {"BigDomain": [("repo1", f"M{i}") for i in range(20)]},
            "modules": {"repo1": [
                {"uid": f"Module::M{i}:0", "label": "Module", "properties": {"name": f"M{i}", "path": f"src/M{i}.java"}}
                for i in range(20)
            ]},
        }

        from wiki.dependency_graph import DomainNode, ModuleInfo

        all_mods = [ModuleInfo(name=f"M{i}", path=f"src/M{i}.java", uid=f"Module::M{i}:0") for i in range(20)]
        main_result = [DomainNode(name="BigDomain", description="big", modules=all_mods, children=[])]
        # Rebalance returns just 1 domain — no meaningful split
        sub_result = [DomainNode(name="BigDomain", description="still big", modules=all_mods, children=[])]

        call_count = {"n": 0}

        async def side_effect(mods, graph):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return main_result
            return sub_result

        with patch("wiki.pipeline_nodes.HierarchicalDecomposer") as mock_hd:
            mock_instance = MagicMock()
            mock_instance.decompose = AsyncMock(side_effect=side_effect)
            mock_hd.return_value = mock_instance

            config = {"configurable": {"llm": AsyncMock()}}
            result = await decompose_hierarchy_node(state, config)

        tree = result["domain_tree"]
        big = next(d for d in tree if d["name"] == "BigDomain")
        # No split happened (single result)
        assert big.get("children") == [] or not big.get("children")
        assert len(big.get("modules", [])) == 20
