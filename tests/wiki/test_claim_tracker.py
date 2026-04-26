"""Tests for ClaimTracker."""

from wiki.claim_extractor import ExtractedClaim
from wiki.claim_tracker import ClaimTracker, SupersedePair


def test_diff_marks_supersession() -> None:
    old = [ExtractedClaim(claim_text="A", subject_entity="E")]
    new = [ExtractedClaim(claim_text="B", subject_entity="E")]
    pairs = ClaimTracker.find_supersedions(old, new)
    assert len(pairs) == 1
    assert pairs[0] == SupersedePair(
        subject_entity="E",
        old_claim_text="A",
        new_claim_text="B",
    )


def test_no_pair_when_text_equal() -> None:
    c = [ExtractedClaim(claim_text="A", subject_entity="E")]
    assert ClaimTracker.find_supersedions(c, c) == []
