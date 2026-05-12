"""Stabilize wiki domain names across incremental runs using lexical similarity."""

from __future__ import annotations

import re
from typing import Any

# WikiSection nodes for business domains use this section_type (see wiki/models.py).
_EXISTING_DOMAINS_CY = (
    "MATCH (ws:WikiSection) "
    "WHERE ws.section_type = 'business_domain' "
    "RETURN DISTINCT ws.title AS domain"
)

# Longer / multi-char suffixes first where relevant.
_DOMAIN_SUFFIXES: tuple[str, ...] = (
    "management",
    "module",
    "service",
    "system",
    "管理",
    "模块",
    "服务",
    "系统",
)


class DomainStabilizer:
    """Stabilize domain names across incremental runs using lexical similarity.

    When the LLM proposes domain names for a new run, this class compares them
    against existing domain names in the graph store and maps near-duplicates
    to the existing canonical name.  The comparison uses normalization, substring
    containment, and Jaccard token similarity (not embedding-based).
    """

    def __init__(self, graph_store: Any | None = None, *, similarity_threshold: float = 0.85):
        self._graph = graph_store
        self._threshold = similarity_threshold

    async def fetch_existing_domains(self) -> list[str]:
        """Query the graph store for all existing domain names."""
        if self._graph is None or not hasattr(self._graph, "execute_query"):
            return []
        result = await self._graph.execute_query(_EXISTING_DOMAINS_CY, None)
        rows = getattr(result, "data", None) or []
        out: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = row.get("domain")
            if title is None:
                continue
            text = str(title).strip()
            if text:
                out.append(text)
        return out

    def normalize_domain_name(self, name: str) -> str:
        """Normalize a domain name for comparison (lowercase, strip, etc.)."""
        s = name.strip().lower()
        return self._strip_suffixes(s)

    def _strip_suffixes(self, s: str) -> str:
        while True:
            stripped = False
            for suf in _DOMAIN_SUFFIXES:
                if not s.endswith(suf):
                    continue
                rest = s[: -len(suf)].rstrip(" \t-/_.")
                if not rest:
                    continue
                s = rest
                stripped = True
                break
            if not stripped:
                break
        return s

    def compute_similarity(self, name_a: str, name_b: str) -> float:
        """Compute text similarity between two domain names.

        Uses a combination of:
        1. Exact match after normalization
        2. Substring containment
        3. Jaccard similarity on word tokens
        """
        na = self.normalize_domain_name(name_a)
        nb = self.normalize_domain_name(name_b)
        if na == nb:
            return 1.0
        if not na or not nb:
            return 0.0
        if na in nb or nb in na:
            return 0.9
        ta = self._tokenize_for_jaccard(na)
        tb = self._tokenize_for_jaccard(nb)
        if not ta or not tb:
            return 0.0
        inter = len(ta & tb)
        union = len(ta | tb)
        j = inter / union if union else 0.0
        pa = na.split()
        pb = nb.split()
        if len(pa) >= 2 and len(pb) >= 2 and pa[0] == pb[0]:
            return max(j, 0.85)
        return j

    _CJK_RE = re.compile(r"[\u4e00-\u9fff]")

    def _tokenize_for_jaccard(self, normalized: str) -> set[str]:
        tokens: set[str] = set()
        for part in re.split(r"[\s/\-_]+", normalized):
            if not part:
                continue
            if self._CJK_RE.search(part):
                for ch in part:
                    if "\u4e00" <= ch <= "\u9fff":
                        tokens.add(ch)
            else:
                tokens.add(part)
        return tokens

    async def stabilize(self, proposed_domains: list[str]) -> dict[str, str]:
        """Map proposed domain names to stable (existing) names.

        Returns: dict mapping proposed_name -> stable_name
        If a proposed name has a close match in existing domains, map to existing.
        If no match found, keep the proposed name as-is.
        """
        existing = await self.fetch_existing_domains()
        return self.stabilize_sync(proposed_domains, existing)

    def stabilize_sync(
        self,
        proposed_domains: list[str],
        existing_domains: list[str],
    ) -> dict[str, str]:
        """Synchronous stabilization with Phase 1 (vs existing) + Phase 2 (vs batch).

        Pre-indexes existing domains by their first normalized token to reduce
        comparisons from O(proposed * existing) to roughly O(proposed * bucket).
        Phase 2 compares against already-confirmed batch canonicals when no
        existing domain matched.
        """
        if not proposed_domains:
            return {}

        if not existing_domains:
            result: dict[str, str] = {}
            batch_canonical: list[str] = []
            for proposed in proposed_domains:
                best_batch: tuple[float, str] = (-1.0, proposed)
                for canonical in batch_canonical:
                    sim = self.compute_similarity(proposed, canonical)
                    if sim > best_batch[0]:
                        best_batch = (sim, canonical)
                if best_batch[0] >= self._threshold:
                    result[proposed] = best_batch[1]
                else:
                    result[proposed] = proposed
                    batch_canonical.append(proposed)
            return result

        index: dict[str, list[str]] = {}
        for ed in existing_domains:
            norm = self.normalize_domain_name(ed)
            tokens = self._tokenize_for_jaccard(norm)
            bucket_keys = tokens if tokens else {""}
            for tk in bucket_keys:
                index.setdefault(tk, []).append(ed)

        result: dict[str, str] = {}
        batch_canonical: list[str] = []

        for proposed in proposed_domains:
            pnorm = self.normalize_domain_name(proposed)
            ptokens = self._tokenize_for_jaccard(pnorm)
            candidates: set[str] = set()
            bucket_keys = ptokens if ptokens else {""}
            for tk in bucket_keys:
                candidates.update(index.get(tk, []))
            if not candidates:
                candidates = set(existing_domains)

            best: tuple[float, str] = (-1.0, proposed)
            for existing in candidates:
                sim = self.compute_similarity(proposed, existing)
                if sim > best[0]:
                    best = (sim, existing)

            if best[0] >= self._threshold:
                result[proposed] = best[1]
                continue

            best_batch: tuple[float, str] = (-1.0, proposed)
            for canonical in batch_canonical:
                sim = self.compute_similarity(proposed, canonical)
                if sim > best_batch[0]:
                    best_batch = (sim, canonical)

            if best_batch[0] >= self._threshold:
                result[proposed] = best_batch[1]
            else:
                result[proposed] = proposed
                batch_canonical.append(proposed)

        return result

    def stabilize_dual_sync(
        self,
        proposed: list[dict[str, str]],
        existing: list[dict[str, str]],
    ) -> dict[str, dict[str, str]]:
        """Match proposed (slug, display_name) pairs against existing anchors.

        Priority: exact slug > display_name similarity > slug similarity > new domain.
        Returns: {final_slug: {"slug": str, "display_name": str}}
        """
        result: dict[str, dict[str, str]] = {}
        used_existing: set[str] = set()

        for prop in proposed:
            p_slug = prop.get("slug", "")
            p_display = prop.get("display_name", p_slug)

            # 1. Exact slug match
            exact = next(
                (e for e in existing if e["slug"] == p_slug and e["slug"] not in used_existing),
                None,
            )
            if exact:
                used_existing.add(exact["slug"])
                result[exact["slug"]] = {"slug": exact["slug"], "display_name": exact["display_name"]}
                continue

            # 2. Display name similarity
            best_score = 0.0
            best_match = None
            for e in existing:
                if e["slug"] in used_existing:
                    continue
                score = self.compute_similarity(
                    self.normalize_domain_name(p_display),
                    self.normalize_domain_name(e.get("display_name", "")),
                )
                if score > best_score:
                    best_score = score
                    best_match = e

            if best_match and best_score >= self._threshold:
                used_existing.add(best_match["slug"])
                result[best_match["slug"]] = {
                    "slug": best_match["slug"],
                    "display_name": best_match["display_name"],
                }
                continue

            # 3. Slug similarity
            best_score = 0.0
            best_match = None
            for e in existing:
                if e["slug"] in used_existing:
                    continue
                score = self.compute_similarity(p_slug, e["slug"])
                if score > best_score:
                    best_score = score
                    best_match = e

            if best_match and best_score >= self._threshold:
                used_existing.add(best_match["slug"])
                result[best_match["slug"]] = {
                    "slug": best_match["slug"],
                    "display_name": best_match["display_name"],
                }
                continue

            # 4. New domain
            result[p_slug] = {"slug": p_slug, "display_name": p_display}

        return result
