"""RED tests for Task 12: edit distance fallback + threshold default change."""

import pytest

from wiki.domain_stabilizer import DomainStabilizer


class TestThresholdDefault:
    """Verify default similarity_threshold is 0.72."""

    def test_default_threshold_is_072(self):
        ds = DomainStabilizer()
        assert ds._threshold == pytest.approx(0.72)

    def test_threshold_override_still_works(self):
        ds = DomainStabilizer(similarity_threshold=0.9)
        assert ds._threshold == pytest.approx(0.9)


class TestLevenshteinMethod:
    """Unit tests for the pure-Python _levenshtein_distance method."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.ds = DomainStabilizer()

    def test_identical_strings(self):
        assert self.ds._levenshtein_distance("abc", "abc") == 0

    def test_empty_vs_nonempty(self):
        assert self.ds._levenshtein_distance("", "abc") == 3
        assert self.ds._levenshtein_distance("abc", "") == 3

    def test_both_empty(self):
        assert self.ds._levenshtein_distance("", "") == 0

    def test_single_substitution(self):
        assert self.ds._levenshtein_distance("cat", "car") == 1

    def test_single_insertion(self):
        assert self.ds._levenshtein_distance("cat", "cats") == 1

    def test_single_deletion(self):
        assert self.ds._levenshtein_distance("cats", "cat") == 1

    def test_completely_different(self):
        assert self.ds._levenshtein_distance("abc", "xyz") == 3


class TestEditDistanceSimilarity:
    """Unit tests for _edit_distance_similarity (normalised 0-1)."""

    @pytest.fixture(autouse=True)
    def _setup(self):
        self.ds = DomainStabilizer()

    def test_identical_returns_1(self):
        assert self.ds._edit_distance_similarity("meeting", "meeting") == 1.0

    def test_one_char_diff(self):
        sim = self.ds._edit_distance_similarity("meeting", "meetin")
        assert 0.8 < sim < 1.0

    def test_completely_different_returns_low(self):
        sim = self.ds._edit_distance_similarity("abc", "xyz")
        assert sim == 0.0

    def test_empty_returns_0(self):
        assert self.ds._edit_distance_similarity("", "abc") == 0.0
        assert self.ds._edit_distance_similarity("abc", "") == 0.0


class TestEditDistanceInComputeSimilarity:
    """Verify compute_similarity uses edit distance as a fallback after Jaccard."""

    def test_edit_distance_rescues_typos(self):
        """'Meetng' vs 'Meeting' have no token overlap but high edit similarity."""
        ds = DomainStabilizer(similarity_threshold=0.65)
        sim = ds.compute_similarity("Meetng", "Meeting")
        # Edit similarity should rescue this above the threshold
        assert sim >= 0.65

    def test_edit_distance_better_than_jaccard(self):
        """For single-token names with typo, edit distance should be the returned value."""
        ds = DomainStabilizer()
        sim = ds.compute_similarity("Meetng", "Meeting")
        # Jaccard on single-char-different tokens gives 0, edit similarity ~0.86
        assert sim > 0.8

    def test_existing_stabilize_sync_still_works(self):
        """Regression: existing stabilization behaviour is preserved."""
        ds = DomainStabilizer(similarity_threshold=0.72)
        result = ds.stabilize_sync(
            proposed_domains=["Meeting Management", "Live Broadcasting"],
            existing_domains=["Meeting", "Live Streaming"],
        )
        assert result["Meeting Management"] == "Meeting"

    def test_low_threshold_matches_typos(self):
        """With 0.72 default, close typos (1 edit apart) should match."""
        ds = DomainStabilizer(similarity_threshold=0.72)
        result = ds.stabilize_sync(
            proposed_domains=["Meetng"],
            existing_domains=["Meeting"],
        )
        assert result["Meetng"] == "Meeting"
