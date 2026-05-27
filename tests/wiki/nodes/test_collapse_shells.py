"""Tests for empty shell domain collapse in decomposition pipeline."""

from __future__ import annotations

from wiki.nodes.graph_domain_decompose import _collapse_empty_shells


def _node(
    name: str,
    *,
    modules: list[str] | None = None,
    children: list[dict] | None = None,
    display_name: str | None = None,
) -> dict:
    return {
        "name": name,
        "display_name": display_name or name,
        "modules": modules if modules is not None else [],
        "children": children or [],
    }


class TestCollapseEmptyShells:
    def test_single_child_collapses(self):
        parent = _node("parent-shell", children=[_node("child-real", modules=["m1", "m2", "m3", "m4", "m5"])])
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        assert result[0]["name"] == "child-real"
        assert len(result[0]["modules"]) == 5
        assert result[0].get("children") == []

    def test_multi_child_does_not_collapse(self):
        parent = _node(
            "parent-shell",
            children=[
                _node("child-one", modules=["a"]),
                _node("child-two", modules=["b"]),
            ],
        )
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        assert result[0]["name"] == "parent-shell"
        assert len(result[0]["children"]) == 2

    def test_deep_chain_collapses(self):
        inner = _node("real-c", modules=["m1", "m2", "m3", "m4", "m5"])
        mid = _node("shell-b", children=[inner])
        a = _node("shell-a", children=[mid])
        result = _collapse_empty_shells([a])
        assert len(result) == 1
        assert result[0]["name"] == "real-c"
        assert len(result[0]["modules"]) == 5

    def test_parent_with_modules_keeps(self):
        parent = _node("parent-with-modules", modules=["p1", "p2", "p3"], children=[_node("child", modules=["c1"] * 5)])
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        assert result[0]["name"] == "parent-with-modules"
        assert len(result[0]["modules"]) == 3
        assert len(result[0]["children"]) == 1

    def test_leaf_with_no_modules_keeps(self):
        leaf = _node("overview-only-leaf")
        result = _collapse_empty_shells([leaf])
        assert len(result) == 1
        assert result[0]["name"] == "overview-only-leaf"
        assert result[0]["modules"] == []

    def test_mixed_tree(self):
        """Some branches collapse; others stay."""
        tree = [
            _node(
                "collapsible-shell",
                children=[_node("real-domain", modules=["x", "y"])],
            ),
            _node(
                "branching-shell",
                children=[
                    _node("branch-a", modules=["a"]),
                    _node("branch-b", modules=["b"]),
                ],
            ),
            _node("leaf-overview"),
            _node("parent-with-mods", modules=["p"], children=[_node("child", modules=["c"])]),
        ]
        result = _collapse_empty_shells(tree)
        assert len(result) == 4
        names = [n["name"] for n in result]
        assert "real-domain" in names
        assert "branching-shell" in names
        assert "leaf-overview" in names
        assert "parent-with-mods" in names
        assert "collapsible-shell" not in names
        real = next(n for n in result if n["name"] == "real-domain")
        assert real["modules"] == ["x", "y"]
        branching = next(n for n in result if n["name"] == "branching-shell")
        assert len(branching["children"]) == 2

    def test_collapsed_from_metadata(self):
        parent = _node("intimacy-relationship", display_name="亲密关系", children=[
            _node("intimacy-relations", display_name="亲密度关系", children=[
                _node("intimacy-relations-0d4c", display_name="亲密度关系核心", modules=["m1"]),
            ]),
        ])
        result = _collapse_empty_shells([parent])
        assert len(result) == 1
        node = result[0]
        assert node["name"] == "intimacy-relations-0d4c"
        assert node["display_name"] == "亲密度关系核心"
        collapsed_from = node.get("collapsed_from", [])
        assert "intimacy-relationship" in collapsed_from
        assert "intimacy-relations" in collapsed_from
