"""Tests for domain tree module deduplication and slug uniqueness."""

from wiki.nodes.classify import _assign_slugs_to_tree, _dedup_tree_modules


class TestDedupTreeModules:
    def test_dedup_removes_parent_modules_in_children(self):
        tree = [
            {
                "name": "parent",
                "modules": ["A", "B", "C"],
                "children": [
                    {"name": "child", "modules": ["B", "C"], "children": []},
                ],
            }
        ]
        _dedup_tree_modules(tree)
        assert tree[0]["modules"] == ["A"]
        assert tree[0]["children"][0]["modules"] == ["B", "C"]

    def test_dedup_handles_deep_nesting(self):
        tree = [
            {
                "name": "grandparent",
                "modules": ["A", "B", "C", "D"],
                "children": [
                    {
                        "name": "parent",
                        "modules": ["B", "C", "D"],
                        "children": [
                            {"name": "child", "modules": ["C", "D"], "children": []},
                        ],
                    }
                ],
            }
        ]
        _dedup_tree_modules(tree)
        assert tree[0]["modules"] == ["A"]
        assert tree[0]["children"][0]["modules"] == ["B"]
        assert tree[0]["children"][0]["children"][0]["modules"] == ["C", "D"]

    def test_empty_tree_no_error(self):
        _dedup_tree_modules([])


class TestSlugUniqueness:
    def test_slug_uniqueness_child_differs_from_parent(self):
        tree = [
            {
                "name": "[im]",
                "display_name": "[im]",
                "modules": ["ModuleA"],
                "children": [
                    {
                        "name": "[im]",
                        "display_name": "[im]",
                        "modules": ["IntimacyTaskHandler"],
                        "children": [],
                    }
                ],
            }
        ]
        domain_mapping = {
            "im": [("repo", "ModuleA"), ("repo", "IntimacyTaskHandler")],
        }
        domain_display_names = {"im": "[im]"}

        _assign_slugs_to_tree(tree, domain_mapping, domain_display_names)

        parent_slug = tree[0]["name"]
        child_slug = tree[0]["children"][0]["name"]
        assert parent_slug == "im"
        assert child_slug != "im"
        assert child_slug.startswith("im-")


class TestPruneEmptyNodes:
    def test_prune_removes_empty_leaf(self):
        from wiki.nodes.classify import _prune_empty_nodes

        tree = [
            {
                "name": "parent",
                "modules": ["A"],
                "children": [
                    {"name": "empty_child", "modules": [], "children": []},
                    {"name": "full_child", "modules": ["B"], "children": []},
                ],
            }
        ]
        _prune_empty_nodes(tree)
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["name"] == "full_child"

    def test_prune_keeps_node_with_children(self):
        from wiki.nodes.classify import _prune_empty_nodes

        tree = [
            {
                "name": "parent",
                "modules": [],
                "children": [
                    {
                        "name": "mid",
                        "modules": [],
                        "children": [
                            {"name": "leaf", "modules": ["X"], "children": []},
                        ],
                    },
                ],
            }
        ]
        _prune_empty_nodes(tree)
        assert len(tree[0]["children"]) == 1
        assert tree[0]["children"][0]["name"] == "mid"

    def test_prune_deep_empty_cascade(self):
        from wiki.nodes.classify import _prune_empty_nodes

        tree = [
            {
                "name": "root",
                "modules": ["A"],
                "children": [
                    {
                        "name": "mid",
                        "modules": [],
                        "children": [
                            {"name": "leaf", "modules": [], "children": []},
                        ],
                    },
                ],
            }
        ]
        _prune_empty_nodes(tree)
        # mid has no modules and after pruning its children is empty → gets pruned
        assert tree[0]["children"] == []
