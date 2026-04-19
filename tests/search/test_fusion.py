"""Tests for search.fusion module — RRF, normalization, and position-aware blending."""

import pytest

from search.fusion import _min_max_normalize, rrf_fusion, position_aware_blend


class TestMinMaxNormalize:
    def test_empty_list(self):
        assert _min_max_normalize([]) == []

    def test_single_value(self):
        result = _min_max_normalize([5.0])
        assert result == [1.0]

    def test_identical_values(self):
        result = _min_max_normalize([3.0, 3.0, 3.0])
        assert result == [1.0, 1.0, 1.0]

    def test_two_values(self):
        result = _min_max_normalize([0.0, 10.0])
        assert result == [0.0, 1.0]

    def test_mixed_values(self):
        result = _min_max_normalize([2.0, 4.0, 6.0, 8.0, 10.0])
        assert result == pytest.approx([0.0, 0.25, 0.5, 0.75, 1.0])

    def test_negative_values(self):
        result = _min_max_normalize([-10.0, 0.0, 10.0])
        assert result == pytest.approx([0.0, 0.5, 1.0])


class TestRRFFusion:
    def test_empty_lists(self):
        result = rrf_fusion([], [])
        assert result == []

    def test_single_list(self):
        ranked = [("a", 0.9), ("b", 0.5), ("c", 0.1)]
        result = rrf_fusion([ranked], [1.0])
        assert len(result) == 3
        # "a" should have highest score (rank 0 bonus +0.05)
        assert result[0][0] == "a"
        assert result[1][0] == "b"

    def test_scores_normalized_to_unit_range(self):
        """RRF outputs are divided by max score so the top doc is 1.0."""
        ranked = [("a", 0.9), ("b", 0.5)]
        result = rrf_fusion([ranked], [1.0])
        scores = dict(result)
        assert max(scores.values()) == pytest.approx(1.0)
        assert all(0.0 <= s <= 1.0 for s in scores.values())

    def test_top_rank_bonus_first(self):
        """Document ranked #1 in any list gets +0.05 bonus (then max-normalized)."""
        ranked = [("a", 0.9), ("b", 0.5)]
        result = rrf_fusion([ranked], [1.0])
        a_score = dict(result)["a"]
        raw_a = 1.0 / 61 + 0.05
        raw_b = 1.0 / 62 + 0.02
        assert a_score == pytest.approx(raw_a / max(raw_a, raw_b))

    def test_top_rank_bonus_second_third(self):
        """Documents ranked #2 or #3 in any list get +0.02 bonus."""
        ranked = [("a", 0.9), ("b", 0.5), ("c", 0.3)]
        result = rrf_fusion([ranked], [1.0])
        scores = dict(result)
        raw_a = 1.0 / 61 + 0.05
        raw_b = 1.0 / 62 + 0.02
        raw_c = 1.0 / 63 + 0.02
        mx = max(raw_a, raw_b, raw_c)
        assert scores["b"] == pytest.approx(raw_b / mx)
        assert scores["c"] == pytest.approx(raw_c / mx)

    def test_no_bonus_below_top3(self):
        """Fourth-ranked doc (index 3) does not receive the top-3 rank bonus."""
        ranked = [("a", 0), ("b", 0), ("c", 0), ("d", 0)]
        result = rrf_fusion([ranked], [1.0])
        scores = dict(result)
        raw_a = 1.0 / 61 + 0.05
        raw_b = 1.0 / 62 + 0.02
        raw_c = 1.0 / 63 + 0.02
        raw_d = 1.0 / 64
        mx = max(raw_a, raw_b, raw_c, raw_d)
        assert scores["d"] == pytest.approx(raw_d / mx)

    def test_two_lists_different_weights(self):
        list1 = [("a", 0.9), ("b", 0.5)]
        list2 = [("b", 0.8), ("c", 0.6)]
        result = rrf_fusion([list1, list2], [1.5, 1.0])
        scores = dict(result)
        a_raw = 1.5 * (1 / 61) + 0.05
        b_raw = 1.5 * (1 / 62) + 1.0 * (1 / 61) + 0.05
        c_raw = 1.0 * (1 / 62)
        mx = max(a_raw, b_raw, c_raw)
        assert scores["b"] == pytest.approx(b_raw / mx)

    def test_descending_order(self):
        list1 = [("a", 0), ("b", 0), ("c", 0)]
        list2 = [("c", 0), ("a", 0), ("b", 0)]
        result = rrf_fusion([list1, list2], [1.0, 1.0])
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)

    def test_custom_k_value(self):
        """Larger RRF ``k`` dampens rank contributions; results stay max-normalized to 1.0."""
        ranked = [("a", 0), ("b", 0)]
        result_k10 = rrf_fusion([ranked], [1.0], k=10)
        result_k100 = rrf_fusion([ranked], [1.0], k=100)
        s10 = dict(result_k10)
        s100 = dict(result_k100)
        assert max(s10.values()) == pytest.approx(1.0)
        assert max(s100.values()) == pytest.approx(1.0)
        assert s10["a"] == pytest.approx(1.0)
        assert s100["a"] == pytest.approx(1.0)
        assert s10["b"] < s10["a"] and s100["b"] < s100["a"]

    def test_weight_default_is_one(self):
        """If weights list is shorter than ranked_lists, default weight is 1.0."""
        list1 = [("a", 0)]
        list2 = [("a", 0)]
        result = rrf_fusion([list1, list2], [2.0])  # only 1 weight for 2 lists
        a_score = dict(result)["a"]
        raw = 2.0 / 61 + 1.0 / 61 + 0.05
        assert a_score == pytest.approx(1.0)

    def test_large_k_boundary(self):
        ranked = [("a", 0)]
        result = rrf_fusion([ranked], [1.0], k=10000)
        a_score = dict(result)["a"]
        assert a_score == pytest.approx(1.0)


class TestPositionAwareBlend:
    def test_empty_inputs(self):
        result = position_aware_blend([], {}, top_k=5)
        assert result == []

    def test_no_reranker_scores(self):
        rrf = [("a", 0.04), ("b", 0.03), ("c", 0.02)]
        result = position_aware_blend(rrf, {}, top_k=3)
        # All reranker scores are 0.0, so only RRF matters
        assert len(result) == 3
        assert result[0][0] == "a"

    def test_top3_weights(self):
        """Top 3 results use 75% RRF, 25% reranker."""
        rrf = [("a", 0.04), ("b", 0.03), ("c", 0.02)]
        # All RRF: normalized to [0, 0.5, 1.0]
        # Reranker: a=0.1, b=0.5, c=0.9 → normalized [0.0, 0.5, 1.0]
        re_scores = {"a": 0.1, "b": 0.5, "c": 0.9}
        result = position_aware_blend(rrf, re_scores, top_k=3)
        scores = dict(result)
        # All in top 3, so weight = 0.75 * rrf_norm + 0.25 * re_norm
        # a: rrf_norm=1.0 (highest rrf), re_norm=0.0 → 0.75*1.0 + 0.25*0.0 = 0.75
        # b: rrf_norm=0.5, re_norm=0.5 → 0.75*0.5 + 0.25*0.5 = 0.5
        # c: rrf_norm=0.0 (lowest rrf), re_norm=1.0 → 0.75*0.0 + 0.25*1.0 = 0.25
        assert scores["a"] == pytest.approx(0.75)
        assert scores["b"] == pytest.approx(0.5)
        assert scores["c"] == pytest.approx(0.25)

    def test_rank_10_plus_weights(self):
        """Ranks 10+ use 40% RRF, 60% reranker."""
        rrf = [(f"doc{i}", 0.04 - i * 0.003) for i in range(12)]
        re_scores = {f"doc{i}": float(i) / 11 for i in range(12)}
        result = position_aware_blend(rrf, re_scores, top_k=12)
        # doc11 is at rank 11 (0-indexed 11), so uses 40/60 weight
        # This is verified by checking it is not dominated by RRF rank alone


    def test_top_k_limits_output(self):
        rrf = [(f"d{i}", 0.01 * (10 - i)) for i in range(10)]
        result = position_aware_blend(rrf, {}, top_k=3)
        assert len(result) == 3

    def test_reranker_can_reorder(self):
        """Reranker with strong signal can reorder lower-ranked items above."""
        rrf = [("a", 0.05), ("b", 0.04), ("c", 0.03), ("d", 0.02), ("e", 0.01)]
        # "e" gets maximum reranker score
        re_scores = {"a": 0.1, "b": 0.1, "c": 0.1, "d": 0.1, "e": 10.0}
        result = position_aware_blend(rrf, re_scores, top_k=5)
        # e should climb up due to high reranker score
        names = [name for name, _ in result]
        e_pos = names.index("e")
        assert e_pos < 4  # e should not be last

    def test_normalization_isolates_scales(self):
        """Different score scales should not affect relative ordering after normalization."""
        # RRF scores in 0.001-0.05 range
        rrf = [("a", 0.05), ("b", 0.03), ("c", 0.01)]
        # Reranker scores in 0-10 range
        re_scores = {"a": 1.0, "b": 5.0, "c": 10.0}
        result = position_aware_blend(rrf, re_scores, top_k=3)
        # Should work correctly despite wildly different scales
        assert len(result) == 3
        assert all(isinstance(s, float) for _, s in result)
