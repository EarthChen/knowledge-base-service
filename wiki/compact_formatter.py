"""Compact knowledge format optimized for LLM context windows."""
from __future__ import annotations

import json
from typing import Any


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 0)


class CompactFormatter:
    """Formats wiki knowledge into compact JSON for LLM consumption."""

    def __init__(self, max_tokens: int = 4000) -> None:
        self._max_tokens = max_tokens

    def format_entity(self, entity_data: dict[str, Any]) -> dict[str, Any]:
        """Format a single entity explanation into compact form."""
        if not entity_data.get("found"):
            return {"status": "not_found"}

        e = entity_data.get("entity", {})
        compact = {
            "name": e.get("name", ""),
            "type": e.get("type", ""),
            "file": e.get("file", ""),
        }
        if e.get("signature"):
            compact["sig"] = e["signature"]
        if e.get("docstring"):
            doc = e["docstring"]
            if _estimate_tokens(doc) > self._max_tokens // 4:
                doc = doc[: self._max_tokens] + "..."
            compact["doc"] = doc

        rels = entity_data.get("relationships", [])
        if rels:
            compact["rels"] = [
                {"type": r.get("rel_type", ""), "target": r.get("other_name", "")} for r in rels[:10]
            ]

        wiki = entity_data.get("wiki_page", {})
        if wiki.get("content"):
            content = wiki["content"]
            if _estimate_tokens(content) > self._max_tokens // 2:
                content = content[: self._max_tokens * 2] + "..."
            compact["wiki"] = content

        return compact

    def format_search_results(self, results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Format search results into compact form."""
        compact: list[dict[str, Any]] = []
        budget = self._max_tokens
        for r in results:
            entry = {
                "title": r.get("title", ""),
                "path": r.get("page_path", ""),
                "score": round(r.get("score", 0.0), 3),
            }
            if r.get("snippet"):
                entry["snip"] = r["snippet"][:200]
            cost = _estimate_tokens(json.dumps(entry))
            if cost > budget:
                break
            compact.append(entry)
            budget -= cost
        return compact

    def format_impact(self, affected_data: dict[str, Any]) -> dict[str, Any]:
        """Format impact analysis into compact form."""
        return {
            "pages_affected": len(affected_data.get("page_uids", [])),
            "entities_affected": len(affected_data.get("affected_entities", [])),
            "trigger": affected_data.get("trigger", "unknown"),
            "pages": affected_data.get("page_uids", [])[:20],
        }
