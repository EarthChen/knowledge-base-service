"""Tests for domain theme aggregation."""
from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

from wiki.domain_merger import (
    _apply_aggregation,
    _build_aggregation_prompt,
    _parse_aggregation_result,
    _tree_depth,
    aggregate_domains_recursive,
)


def _make_node(name: str, display_name: str = "", modules: list | None = None, children: list | None = None) -> dict:
    return {
        "name": name,
        "display_name": display_name or name,
        "description": "",
        "modules": modules or [],
        "children": children or [],
    }


class TestParseAggregationResult:
    def test_valid_new_groups(self):
        nodes = [
            _make_node("family-core", "家族核心管理"),
            _make_node("family-task", "家族任务系统"),
            _make_node("gift-order", "礼物订单"),
        ]
        response = json.dumps({
            "new_groups": [
                {
                    "parent_display_name": "家族",
                    "parent_slug": "family",
                    "children_slugs": ["family-core", "family-task"],
                }
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order"],
        })
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert len(groups) == 1
        assert groups[0]["parent_slug"] == "family"
        assert set(groups[0]["children_slugs"]) == {"family-core", "family-task"}
        assert standalones == ["gift-order"]

    def test_assign_to_existing(self):
        nodes = [
            _make_node("family-task", "家族任务系统"),
            _make_node("gift-order", "礼物订单"),
        ]
        response = json.dumps({
            "new_groups": [],
            "assign_to_existing": {"family": ["family-task"]},
            "standalone_slugs": ["gift-order"],
        })
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert len(groups) == 0
        assert assigns == {"family": ["family-task"]}

    def test_invalid_json_returns_empty(self):
        nodes = [_make_node("a", "A")]
        groups, assigns, standalones = _parse_aggregation_result("not json", nodes)
        assert groups == []
        assert assigns == {}
        assert standalones == []

    def test_unknown_slug_ignored(self):
        nodes = [_make_node("family-core", "家族核心管理")]
        response = json.dumps({
            "new_groups": [
                {
                    "parent_display_name": "家族",
                    "parent_slug": "family",
                    "children_slugs": ["family-core", "nonexistent"],
                }
            ],
            "assign_to_existing": {},
            "standalone_slugs": [],
        })
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        # Only 1 valid child, so group should be dropped (needs >= 2)
        assert groups == []

    def test_markdown_fenced_json(self):
        nodes = [
            _make_node("family-core", "家族核心管理"),
            _make_node("family-task", "家族任务系统"),
        ]
        inner = json.dumps({
            "new_groups": [
                {
                    "parent_display_name": "家族",
                    "parent_slug": "family",
                    "children_slugs": ["family-core", "family-task"],
                }
            ],
            "assign_to_existing": {},
            "standalone_slugs": [],
        })
        response = f"```json\n{inner}\n```"
        groups, assigns, standalones = _parse_aggregation_result(response, nodes)
        assert len(groups) == 1


class TestTreeDepth:
    def test_flat_tree(self):
        nodes = [_make_node("a"), _make_node("b")]
        assert _tree_depth(nodes) == 1

    def test_nested_tree(self):
        child = _make_node("c")
        parent = _make_node("p", children=[child])
        assert _tree_depth([parent]) == 2

    def test_empty(self):
        assert _tree_depth([]) == 0

    def test_deep_tree(self):
        leaf = _make_node("leaf")
        mid = _make_node("mid", children=[leaf])
        root = _make_node("root", children=[mid])
        assert _tree_depth([root]) == 3


class TestApplyAggregation:
    def test_creates_parent_with_children(self):
        nodes = [
            _make_node("family-core", "家族核心管理", modules=["m1"]),
            _make_node("family-task", "家族任务系统", modules=["m2"]),
            _make_node("gift-order", "礼物订单", modules=["m3"]),
        ]
        groups = [
            {
                "parent_display_name": "家族",
                "parent_slug": "family",
                "children_slugs": ["family-core", "family-task"],
            }
        ]
        result = _apply_aggregation(nodes, groups, {})
        parent_names = [n["name"] for n in result]
        assert "family" in parent_names
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 2
        assert family["modules"] == []
        assert "gift-order" in parent_names

    def test_assign_to_existing_parent(self):
        existing_parent = _make_node("family", "家族", children=[_make_node("family-core", "家族核心管理")])
        orphan = _make_node("family-task", "家族任务系统", modules=["m2"])
        nodes = [existing_parent, orphan]
        assigns = {"family": ["family-task"]}
        result = _apply_aggregation(nodes, [], assigns)
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 2

    def test_dedup_new_group_with_existing(self):
        existing_parent = _make_node("family", "家族", children=[_make_node("family-core", "家族核心管理")])
        orphan1 = _make_node("family-task", "家族任务系统")
        orphan2 = _make_node("family-combat", "家族战力")
        nodes = [existing_parent, orphan1, orphan2]
        groups = [
            {
                "parent_display_name": "家族",
                "parent_slug": "family",
                "children_slugs": ["family-task", "family-combat"],
            }
        ]
        result = _apply_aggregation(nodes, groups, {})
        family_nodes = [n for n in result if n["name"] == "family"]
        assert len(family_nodes) == 1
        assert len(family_nodes[0]["children"]) == 3


class TestBuildAggregationPrompt:
    def test_includes_domain_info(self):
        nodes = [_make_node("family-core", "家族核心管理", modules=["m1", "m2"])]
        prompt = _build_aggregation_prompt(nodes, [])
        assert "家族核心管理" in prompt
        assert "family-core" in prompt

    def test_includes_existing_parents(self):
        nodes = [_make_node("gift-order", "礼物订单")]
        existing = [{"slug": "family", "display_name": "家族", "children": ["家族核心管理"]}]
        prompt = _build_aggregation_prompt(nodes, existing)
        assert "家族" in prompt
        assert "已有父域" in prompt


class TestAggregateDomainRecursive:
    def test_skips_small_sibling_count(self):
        nodes = [_make_node("a"), _make_node("b")]
        llm = AsyncMock()
        result = asyncio.run(aggregate_domains_recursive(nodes, llm))
        assert result == nodes
        llm.generate.assert_not_called()

    def test_groups_siblings_by_theme(self):
        nodes = [
            _make_node("family-core", "家族核心管理", modules=["m1"]),
            _make_node("family-task", "家族任务系统", modules=["m2"]),
            _make_node("family-combat", "家族战力", modules=["m3"]),
            _make_node("gift-order", "礼物订单", modules=["m4"]),
        ]
        llm = AsyncMock()
        llm.generate.return_value = json.dumps({
            "new_groups": [
                {"parent_display_name": "家族", "parent_slug": "family",
                 "children_slugs": ["family-core", "family-task", "family-combat"]}
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order"],
        })
        result = asyncio.run(aggregate_domains_recursive(nodes, llm))
        names = [n["name"] for n in result]
        assert "family" in names
        assert "gift-order" in names
        family = next(n for n in result if n["name"] == "family")
        assert len(family["children"]) == 3

    def test_skips_user_modified_domains(self):
        nodes = [
            _make_node("family-core", "家族核心管理"),
            _make_node("family-task", "家族任务系统"),
            _make_node("family-combat", "家族战力"),
            _make_node("gift-order", "礼物订单"),
        ]
        nodes[0]["user_modified"] = True
        llm = AsyncMock()
        llm.generate.return_value = json.dumps({
            "new_groups": [
                {"parent_display_name": "家族", "parent_slug": "family",
                 "children_slugs": ["family-task", "family-combat"]}
            ],
            "assign_to_existing": {},
            "standalone_slugs": ["gift-order"],
        })
        result = asyncio.run(aggregate_domains_recursive(nodes, llm))
        top_names = [n["name"] for n in result]
        assert "family-core" in top_names

    def test_llm_failure_preserves_original(self):
        nodes = [
            _make_node("a", modules=["m1"]),
            _make_node("b", modules=["m2"]),
            _make_node("c", modules=["m3"]),
        ]
        llm = AsyncMock()
        llm.generate.side_effect = RuntimeError("LLM down")
        result = asyncio.run(aggregate_domains_recursive(nodes, llm))
        assert len(result) == 3

    def test_depth_limit_prevents_aggregation(self):
        nodes = [_make_node("a"), _make_node("b"), _make_node("c")]
        llm = AsyncMock()
        result = asyncio.run(aggregate_domains_recursive(nodes, llm, max_tree_depth=1))
        assert len(result) == 3
        llm.generate.assert_not_called()
