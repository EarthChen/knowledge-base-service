"""Regression tests: WikiSearchService still works after migration to shared RRF."""

from wiki.search import WikiSearchService


class TestWikiSearchRRFRegression:
    def test_rrf_fusion_empty(self):
        result = WikiSearchService.rrf_fusion([], [])
        assert result == []

    def test_rrf_fusion_single_list(self):
        ranked = [("page/a.md", 0.9), ("page/b.md", 0.5)]
        result = WikiSearchService.rrf_fusion([ranked], [1.0])
        assert len(result) == 2
        assert result[0][0] == "page/a.md"

    def test_rrf_fusion_two_lists(self):
        list1 = [("page/a.md", 0.9), ("page/b.md", 0.5)]
        list2 = [("page/b.md", 0.8), ("page/c.md", 0.6)]
        result = WikiSearchService.rrf_fusion(
            [list1, list2], [2.0, 1.0]
        )
        scores = dict(result)
        assert "page/a.md" in scores
        assert "page/b.md" in scores
        assert "page/c.md" in scores

    def test_rrf_fusion_top_rank_bonus(self):
        ranked = [("p1", 0), ("p2", 0), ("p3", 0)]
        result = WikiSearchService.rrf_fusion([ranked], [1.0])
        scores = dict(result)
        # p1 gets +0.05 bonus, p2/p3 get +0.02
        assert scores["p1"] > scores["p2"] > scores["p3"]

    def test_rrf_fusion_descending(self):
        list1 = [("a", 0), ("b", 0)]
        list2 = [("b", 0), ("c", 0)]
        result = WikiSearchService.rrf_fusion([list1, list2], [1.0, 1.0])
        scores_only = [s for _, s in result]
        assert scores_only == sorted(scores_only, reverse=True)
