"""Compare extracted claims across wiki regenerations and compute supersession."""

from __future__ import annotations

from dataclasses import dataclass

from wiki.claim_extractor import ExtractedClaim


@dataclass(frozen=True)
class SupersedePair:
    subject_entity: str
    old_claim_text: str
    new_claim_text: str


class ClaimTracker:
    """Finds when a new claim replaces an older one for the same subject."""

    @staticmethod
    def find_supersedions(
        old_claims: list[ExtractedClaim],
        new_claims: list[ExtractedClaim],
    ) -> list[SupersedePair]:
        pairs: list[SupersedePair] = []
        for n in new_claims:
            subj = (n.subject_entity or "").strip()
            ntxt = (n.claim_text or "").strip()
            if not subj or not ntxt:
                continue
            for o in old_claims:
                if (o.subject_entity or "").strip() != subj:
                    continue
                otxt = (o.claim_text or "").strip()
                if otxt and otxt != ntxt:
                    pairs.append(
                        SupersedePair(
                            subject_entity=subj,
                            old_claim_text=otxt,
                            new_claim_text=ntxt,
                        ),
                    )
                    break
        return pairs
