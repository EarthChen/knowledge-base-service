"""Tests for _review_subdomain_placement reparenting (SB3)."""
from __future__ import annotations


class TestReviewSubdomainPlacement:
    def test_family_under_intimacy_gets_reparented(self):
        from wiki.nodes.graph_domain_decompose import _review_subdomain_placement

        tree = [
            {
                "name": "intimacy-task",
                "display_name": "亲密度任务",
                "modules": [],
                "children": [
                    {
                        "name": "family-core",
                        "display_name": "家族核心",
                        "modules": [("r", "FamilyService")],
                        "children": [],
                    },
                ],
            },
        ]
        result = _review_subdomain_placement(tree, infrastructure_keywords=[])
        # family-core should be reparented to root
        assert len(result) == 1
        assert result[0]["child"] == "family-core"
        # Tree should have 2 root nodes now
        assert len(tree) == 2
        assert tree[0]["name"] == "intimacy-task"
        assert len(tree[0]["children"]) == 0
        assert tree[1]["name"] == "family-core"

    def test_intimacy_under_family_gets_reparented(self):
        from wiki.nodes.graph_domain_decompose import _review_subdomain_placement

        tree = [
            {
                "name": "family-operations",
                "display_name": "家族运营",
                "modules": [],
                "children": [
                    {
                        "name": "intimacy-data",
                        "display_name": "亲密度数据",
                        "modules": [],
                        "children": [],
                    },
                ],
            },
        ]
        result = _review_subdomain_placement(tree, infrastructure_keywords=[])
        assert len(result) == 1
        assert result[0]["child"] == "intimacy-data"
        assert len(tree) == 2

    def test_matching_child_not_reparented(self):
        from wiki.nodes.graph_domain_decompose import _review_subdomain_placement

        tree = [
            {
                "name": "family-group",
                "display_name": "家族",
                "modules": [],
                "children": [
                    {
                        "name": "family-chest",
                        "display_name": "家族宝箱",
                        "modules": [],
                        "children": [],
                    },
                ],
            },
        ]
        result = _review_subdomain_placement(tree, infrastructure_keywords=[])
        assert len(result) == 0
        assert len(tree) == 1
        assert len(tree[0]["children"]) == 1

    def test_user_modified_child_not_reparented(self):
        from wiki.nodes.graph_domain_decompose import _review_subdomain_placement

        tree = [
            {
                "name": "intimacy-area",
                "display_name": "亲密度",
                "modules": [],
                "children": [
                    {
                        "name": "family-special",
                        "display_name": "家族特殊",
                        "modules": [],
                        "children": [],
                        "user_modified": True,
                    },
                ],
            },
        ]
        result = _review_subdomain_placement(tree, infrastructure_keywords=[])
        assert len(result) == 0
        assert len(tree[0]["children"]) == 1

    def test_user_growth_family_mismatch(self):
        from wiki.nodes.graph_domain_decompose import _review_subdomain_placement

        tree = [
            {
                "name": "user-growth",
                "display_name": "用户成长",
                "modules": [],
                "children": [
                    {
                        "name": "family-rewards",
                        "display_name": "家族奖励",
                        "modules": [],
                        "children": [],
                    },
                ],
            },
        ]
        result = _review_subdomain_placement(tree, infrastructure_keywords=[])
        assert len(result) == 1
        assert result[0]["child"] == "family-rewards"
