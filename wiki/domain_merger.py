"""Post-processing to merge small domains into larger siblings."""
from __future__ import annotations

from typing import Protocol

from core.log import get_logger

log = get_logger(__name__)


class DomainLike(Protocol):
    name: str
    modules: list


def _name_similarity(a: DomainLike, b: DomainLike) -> float:
    """Simple Jaccard similarity on module name character trigrams."""

    def trigrams(text: str) -> set[str]:
        t = text.lower()
        return {t[i : i + 3] for i in range(max(0, len(t) - 2))}

    a_tri = set()
    for m in a.modules:
        a_tri |= trigrams(str(m))
    b_tri = set()
    for m in b.modules:
        b_tri |= trigrams(str(m))

    if not a_tri or not b_tri:
        return 0.0
    return len(a_tri & b_tri) / len(a_tri | b_tri)


def merge_small_domains(domains: list, min_size: int = 3) -> list:
    """Merge domains with fewer than min_size modules into the most similar large domain."""
    large = [d for d in domains if len(d.modules) >= min_size]
    small = [d for d in domains if len(d.modules) < min_size]

    if not large and small:
        large = [small.pop(0)]

    for sd in small:
        if not large:
            break
        best = max(large, key=lambda ld: _name_similarity(sd, ld))
        best.modules.extend(sd.modules)
        log.info("domain_merged", small=sd.name, into=best.name, added=len(sd.modules))

    return large
