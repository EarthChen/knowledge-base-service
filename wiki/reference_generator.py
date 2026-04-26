"""Derive WIKI_REFERENCES edges from code graph relationships (CALLS, INHERITS, etc.)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from store.schema import EdgeType

_REL_TO_WIKI: dict[str, str] = {
    EdgeType.CALLS.value: "calls",
    EdgeType.CROSS_REPO_CALLS.value: "cross_repo",
    EdgeType.INHERITS.value: "inherits",
    EdgeType.IMPORTS.value: "imports",
}


class WikiReferenceGenerator:
    """Maps code-level edges between SOURCE_ENTITY-linked WikiPages to WIKI_REFERENCES."""

    def __init__(self, wiki_store: Any) -> None:
        self._wiki_store = wiki_store

    async def generate(self, repository: str | None = None) -> int:
        mappings = await self._wiki_store.find_source_entity_mappings(repository)
        if not mappings:
            return 0

        entity_to_wiki: dict[str, str] = {}
        for m in mappings:
            eu = str(m.get("entity_uid", "") or "")
            wu = str(m.get("wiki_uid", "") or "")
            if eu and wu:
                entity_to_wiki[eu] = wu

        if not entity_to_wiki:
            return 0

        entity_uids = list(entity_to_wiki.keys())
        rels = await self._wiki_store.find_code_entity_relationships(entity_uids)

        seen: set[tuple[str, str, str]] = set()
        count = 0
        for row in rels:
            su = str(row.get("source_uid", "") or "")
            tu = str(row.get("target_uid", "") or "")
            rt = str(row.get("rel_type", "") or "")
            wiki_rel = _REL_TO_WIKI.get(rt)
            if wiki_rel is None:
                continue
            sw = entity_to_wiki.get(su)
            tw = entity_to_wiki.get(tu)
            if not sw or not tw or sw == tw:
                continue
            key = (sw, tw, wiki_rel)
            if key in seen:
                continue
            seen.add(key)
            await self._wiki_store.add_wiki_reference_edge(
                sw,
                tw,
                wiki_rel,
                context="",
                auto_generated=True,
                confidence=1.0,
            )
            count += 1
        return count

    def inject_wikilinks(
        self, content: str, outgoing_refs: Sequence[str | Mapping[str, str]]
    ) -> str:
        """Append a ``## Related Pages`` section with ``[[path]]`` wikilinks."""
        ordered: list[str] = []
        seen_paths: set[str] = set()
        for ref in outgoing_refs:
            p = ref if isinstance(ref, str) else str(ref.get("path", "") or "")
            p = p.strip()
            if p and p not in seen_paths:
                seen_paths.add(p)
                ordered.append(p)
        if not ordered:
            return content
        block = "\n\n## Related Pages\n" + "\n".join(f"- [[{p}]]" for p in ordered)
        return content.rstrip() + block
