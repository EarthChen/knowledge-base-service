"""Unit tests for WikiService._sort_by_depth (incremental generation ordering)."""


class TestDepthOrdering:
    def test_leaves_processed_before_parents(self) -> None:
        from wiki.service import WikiService

        contains_edges = [
            {"source": "module_root", "target": "class_a"},
            {"source": "class_a", "target": "method_1"},
        ]
        sorted_uids = WikiService._sort_by_depth(
            ["module_root", "class_a", "method_1"],
            contains_edges,
        )
        assert sorted_uids.index("method_1") < sorted_uids.index("class_a")
        assert sorted_uids.index("class_a") < sorted_uids.index("module_root")

    def test_flat_list_unchanged(self) -> None:
        from wiki.service import WikiService

        sorted_uids = WikiService._sort_by_depth(["a", "b", "c"], [])
        assert set(sorted_uids) == {"a", "b", "c"}

    def test_cycle_handled(self) -> None:
        from wiki.service import WikiService

        edges = [
            {"source": "a", "target": "b"},
            {"source": "b", "target": "a"},
        ]
        sorted_uids = WikiService._sort_by_depth(["a", "b"], edges)
        assert set(sorted_uids) == {"a", "b"}
