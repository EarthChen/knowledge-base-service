"""Batch contradiction detection: same-entity pages, embedding gate + LLM judge."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from wiki.llm_port import LLMPort


@dataclass(frozen=True)
class ContradictionRecord:
    page_uid_a: str
    page_uid_b: str
    description: str
    severity: Literal["high", "medium", "low"]


# Backwards-compatible alias referenced in the phase-2 plan
ContradictionCandidate = ContradictionRecord


def wiki_page_uid(repository: str, path: str) -> str:
    return f"WikiPage:{repository}:{path}"


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for x, y in zip(a, b, strict=True):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0.0 or nb <= 0.0:
        return 0.0
    return dot / (na**0.5 * nb**0.5)


def group_pages_by_entity_name(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group wiki page rows by entity key (title, else first referenced entity uid)."""
    out: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        title = str(row.get("title", "") or "").strip()
        ref_uids = row.get("referenced_entity_uids") or []
        if isinstance(ref_uids, (list, tuple)) and ref_uids:
            key = str(ref_uids[0] or title or "unknown")
        else:
            key = title or "unknown"
        if not key or key == "unknown":
            continue
        out.setdefault(key, []).append(row)
    return out


class LlmVerdict(BaseModel):
    is_contradiction: bool
    description: str = ""
    severity: Literal["high", "medium", "low"] = "medium"


def _parse_verdict_json(raw: str) -> LlmVerdict | None:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return LlmVerdict.model_validate(data)
    except Exception:
        return None


class ContradictionDetector:
    """Finds conflicting statements across wiki pages for the same entity."""

    def __init__(
        self,
        graph: Any,
        embedding_fn: Any,
        llm: LLMPort | None,
        *,
        similarity_threshold: float = 0.75,
    ) -> None:
        self._graph = graph
        self._embedding_fn = embedding_fn
        self._llm = llm
        self._similarity_threshold = similarity_threshold

    async def detect(
        self,
        pages: list[dict[str, Any]],
        repository: str,
    ) -> list[ContradictionRecord]:
        found: list[ContradictionRecord] = []
        groups = group_pages_by_entity_name(pages)
        for _key, group in groups.items():
            n = len(group)
            if n < 2:
                continue
            for i in range(n):
                for j in range(i + 1, n):
                    a = group[i]
                    b = group[j]
                    path_a = str(a.get("path", "") or "")
                    path_b = str(b.get("path", "") or "")
                    if not path_a or not path_b:
                        continue
                    va = await self._embedding_fn(
                        str(a.get("title", "") or ""),
                        str(a.get("content", "") or ""),
                    )
                    vb = await self._embedding_fn(
                        str(b.get("title", "") or ""),
                        str(b.get("content", "") or ""),
                    )
                    sim = cosine_similarity(va, vb)
                    rec = await self._maybe_flag_pair(
                        page_a=a,
                        page_b=b,
                        similarity=sim,
                        repository=repository,
                    )
                    if rec is not None:
                        found.append(rec)
        return found

    async def _maybe_flag_pair(
        self,
        page_a: dict[str, Any],
        page_b: dict[str, Any],
        similarity: float,
        repository: str,
    ) -> ContradictionRecord | None:
        if similarity >= self._similarity_threshold:
            return None
        if self._llm is None:
            return None

        text_a = str(page_a.get("content", "") or "")[:8000]
        text_b = str(page_b.get("content", "") or "")[:8000]
        path_a = str(page_a.get("path", "") or "")
        path_b = str(page_b.get("path", "") or "")

        prompt = (
            "You compare two wiki snippets about the same code entity. "
            "Decide if they make CONTRADICTORY factual claims (e.g. different behavior, type, or contract).\n\n"
            f"--- Page A ({path_a}) ---\n{text_a}\n\n"
            f"--- Page B ({path_b}) ---\n{text_b}\n\n"
            "Reply with JSON only: "
            '{"is_contradiction": <bool>, "description": <string>, "severity": "high"|"medium"|"low"}\n'
        )
        raw = (await self._llm.generate(prompt, system="JSON only, no markdown.")).strip()
        verdict = _parse_verdict_json(raw)
        if verdict is None or not verdict.is_contradiction:
            return None
        if verdict.severity not in ("high", "medium", "low"):
            verdict = verdict.model_copy(update={"severity": "medium"})
        return ContradictionRecord(
            page_uid_a=wiki_page_uid(repository, path_a),
            page_uid_b=wiki_page_uid(repository, path_b),
            description=verdict.description[:4000] if verdict.description else "Contradictory statements",
            severity=verdict.severity,
        )
