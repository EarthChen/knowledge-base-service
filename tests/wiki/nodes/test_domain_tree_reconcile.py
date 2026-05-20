"""Tests for reconciling domain_tree with flat domain_mapping."""

from wiki.nodes.classify import _reconcile_tree_with_mapping


class TestReconcileTreeWithMapping:
    def test_module_moved_to_correct_domain(self):
        tree = [
            {
                "name": "infrastructure",
                "display_name": "Infrastructure",
                "modules": ["TaskService", "ConfigLoader"],
                "children": [],
            },
            {
                "name": "tasksystem",
                "display_name": "Task System",
                "modules": [],
                "children": [],
            },
        ]
        domain_mapping = {
            "infrastructure": [("repo", "ConfigLoader")],
            "tasksystem": [("repo", "TaskService")],
        }

        _reconcile_tree_with_mapping(tree, domain_mapping)

        infra = next(n for n in tree if n["name"] == "infrastructure")
        task = next(n for n in tree if n["name"] == "tasksystem")
        assert "TaskService" not in infra["modules"]
        assert "ConfigLoader" in infra["modules"]
        assert "TaskService" in task["modules"]

    def test_module_in_correct_domain_stays(self):
        tree = [
            {
                "name": "tasksystem",
                "display_name": "Task System",
                "modules": ["TaskService", "TaskHandler"],
                "children": [],
            },
        ]
        domain_mapping = {
            "tasksystem": [("repo", "TaskService"), ("repo", "TaskHandler")],
        }

        _reconcile_tree_with_mapping(tree, domain_mapping)

        assert tree[0]["modules"] == ["TaskService", "TaskHandler"]

    def test_missing_domain_creates_node(self):
        tree = [
            {
                "name": "infrastructure",
                "display_name": "Infrastructure",
                "modules": ["ConfigLoader"],
                "children": [],
            },
        ]
        domain_mapping = {
            "infrastructure": [("repo", "ConfigLoader")],
            "tasksystem": [("repo", "TaskService")],
        }

        _reconcile_tree_with_mapping(tree, domain_mapping)

        slugs = {n["name"] for n in tree}
        assert "tasksystem" in slugs
        task = next(n for n in tree if n["name"] == "tasksystem")
        assert "TaskService" in task["modules"]

    def test_modules_not_in_mapping_stay(self):
        tree = [
            {
                "name": "infrastructure",
                "display_name": "Infrastructure",
                "modules": ["ConfigLoader", "UnknownModule"],
                "children": [],
            },
        ]
        domain_mapping = {
            "infrastructure": [("repo", "ConfigLoader")],
        }

        _reconcile_tree_with_mapping(tree, domain_mapping)

        assert "UnknownModule" in tree[0]["modules"]
        assert "ConfigLoader" in tree[0]["modules"]

    def test_empty_mapping_no_crash(self):
        _reconcile_tree_with_mapping([], {})
        _reconcile_tree_with_mapping(
            [{"name": "x", "modules": ["A"], "children": []}],
            {},
        )
