"""Tests for smart early stop detection."""

import pytest

from wiki.early_stop import EarlyStopDetector


class TestEarlyStopDetector:
    def test_no_stop_on_meaningful_results(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop(["some code found", "class Foo {}"])

    def test_no_stop_on_first_empty_round(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop(["[EMPTY_RESULT] No data returned for read_code"])

    def test_stop_after_consecutive_empty_rounds(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        assert detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_reset_on_meaningful_result(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        detector.should_stop(["meaningful data here"])
        assert not detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_mixed_results_not_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        assert not detector.should_stop([
            "[EMPTY_RESULT] No data",
            "but this one has data",
        ])

    def test_empty_list_counts_as_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop([])
        assert detector.should_stop([])

    def test_reset_method(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(["[EMPTY_RESULT] No data"])
        detector.reset()
        assert not detector.should_stop(["[EMPTY_RESULT] No data"])

    def test_custom_max_empty_rounds(self):
        detector = EarlyStopDetector(max_empty_rounds=3)
        assert not detector.should_stop(["[EMPTY_RESULT] x"])
        assert not detector.should_stop(["[EMPTY_RESULT] x"])
        assert detector.should_stop(["[EMPTY_RESULT] x"])

        detector2 = EarlyStopDetector(max_empty_rounds=3)
        detector2.should_stop(["[EMPTY_RESULT] x"])
        detector2.should_stop(["[EMPTY_RESULT] x"])
        detector2.should_stop(["[EMPTY_RESULT] x"])
        assert detector2.should_stop(["[EMPTY_RESULT] x"])

    def test_error_results_count_as_empty(self):
        detector = EarlyStopDetector(max_empty_rounds=2)
        detector.should_stop(['{"error": "something failed"}'])
        assert detector.should_stop(['{"error": "another failure"}'])
