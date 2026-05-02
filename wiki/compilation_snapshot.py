"""Build a compiled markdown snapshot of wiki knowledge (graph -> markdown)."""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from core.log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


def _summary_excerpt(text: str, max_len: int = 200) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "\u2026"


def _section_key(path: str) -> str:
    p = (path or "").strip("/")
    if "/" in p:
        return p.split("/", 1)[0]
    return "root"


@dataclass
class _PageRow:
    path: str
    title: str
    summary: str
    page_type: str
    importance_tier: str
    confidence: float | None
    wikilinks: list[str]


class WikiCompilationSnapshot:
    """Full rebuild of a repo's wiki snapshot from graph queries (no diff merge)."""

    def __init__(self, graph: _GraphPort, wiki_config: Any) -> None:
        self._graph = graph
        self._cfg = wiki_config

    @staticmethod
    def _parse_rows(result: Any) -> list[dict[str, Any]]:
        rows = getattr(result, "data", None) or []
        out: list[dict[str, Any]] = []
        for r in rows:
            if isinstance(r, dict):
                out.append(r)
        return out

    async def _fetch_pages(self, repository: str) -> list[_PageRow]:
        q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE coalesce(wp.deprecated, false) = false "
            "RETURN wp.path AS path, wp.title AS title, "
            "left(coalesce(wp.content, ''), 2000) AS content_excerpt, "
            "coalesce(wp.page_type, '') AS page_type, "
            "coalesce(wp.importance_tier, '') AS importance_tier, "
            "coalesce(wp.confidence, null) AS confidence, "
            "coalesce(wp.wikilinks, []) AS wikilinks "
            "ORDER BY wp.path"
        )
        result = await self._graph.execute_query(q, {"repo": repository})
        parsed: list[_PageRow] = []
        for d in self._parse_rows(result):
            raw_links = d.get("wikilinks") or []
            if isinstance(raw_links, str):
                wikilinks = [raw_links]
            else:
                wikilinks = [str(x) for x in raw_links]
            conf = d.get("confidence")
            try:
                conf_f = float(conf) if conf is not None else None
            except (TypeError, ValueError):
                conf_f = None
            parsed.append(
                _PageRow(
                    path=str(d.get("path") or ""),
                    title=str(d.get("title") or ""),
                    summary=_summary_excerpt(str(d.get("content_excerpt") or "")),
                    page_type=str(d.get("page_type") or ""),
                    importance_tier=str(d.get("importance_tier") or "standard"),
                    confidence=conf_f,
                    wikilinks=wikilinks,
                )
            )
        return parsed

    def _render_page_line(self, p: _PageRow) -> str:
        slug = p.path.replace(".md", "").replace("/", "-")
        conf = f"{p.confidence:.2f}" if p.confidence is not None else "n/a"
        refs = ", ".join(p.wikilinks[:8]) if p.wikilinks else "\u2014"
        head = f"{p.title} — {p.summary}" if p.title else p.summary
        return (
            f"- [[{slug}]]: {head} "
            f"({p.importance_tier or 'standard'}, confidence: {conf}) "
            f"\u2192 references: {refs}"
        )

    def _render_cross_ref(self, pages: list[_PageRow]) -> str:
        lines: list[str] = ["", "## Cross-Reference Map", ""]
        for p in pages:
            if not p.wikilinks:
                continue
            slug = p.path.replace(".md", "").replace("/", "-")
            targets = ", ".join(p.wikilinks)
            lines.append(f"- {slug} \u2192 {targets}")
        if len(lines) <= 3:
            lines.append("_No wikilinks recorded._")
        return "\n".join(lines)

    async def generate(self, _business_id: str, repository: str) -> str:
        pages = await self._fetch_pages(repository)
        if not pages:
            return self._empty_doc(repository)
        return self._render_bundle(repository, pages, module_sections=None)

    async def generate_layered(self, business_id: str, repository: str) -> dict[str, str]:
        pages = await self._fetch_pages(repository)
        if not pages:
            return {"index": self._empty_doc(repository)}
        by_mod: dict[str, list[_PageRow]] = defaultdict(list)
        for p in pages:
            by_mod[_section_key(p.path)].append(p)
        index_body = self._render_index_only(repository, pages, by_mod)
        out: dict[str, str] = {"index": index_body}
        for mod, pgs in sorted(by_mod.items()):
            out[mod] = self._render_bundle(repository, pgs, module_sections={mod: pgs}, title_suffix=mod)
        return out

    def _empty_doc(self, repository: str) -> str:
        now = datetime.now(timezone.utc).isoformat()
        return "\n".join(
            [
                f"# Knowledge Base Snapshot \u2014 {repository}",
                f"Generated: {now} | Pages: 0",
                "",
                "_No wiki pages in graph._",
            ]
        )

    def _render_index_only(
        self,
        repository: str,
        pages: list[_PageRow],
        by_mod: dict[str, list[_PageRow]],
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        lines: list[str] = [
            f"# Knowledge Base Snapshot \u2014 {repository} (index)",
            f"Generated: {now} | Pages: {len(pages)} | Modules: {len(by_mod)}",
            "",
            "## Module overview",
            "",
        ]
        for mod, pgs in sorted(by_mod.items()):
            lines.append(f"- **{mod}**: {len(pgs)} page(s)")
        lines.append(self._render_cross_ref(pages))
        return "\n".join(lines)

    def _render_bundle(
        self,
        repository: str,
        pages: list[_PageRow],
        module_sections: dict[str, list[_PageRow]] | None,
        title_suffix: str | None = None,
    ) -> str:
        now = datetime.now(timezone.utc).isoformat()
        title = f"# Knowledge Base Snapshot \u2014 {repository}"
        if title_suffix:
            title += f" / {title_suffix}"
        lines: list[str] = [
            title,
            f"Generated: {now} | Pages: {len(pages)}",
            "",
        ]
        if module_sections is None:
            by_mod: dict[str, list[_PageRow]] = defaultdict(list)
            for p in pages:
                by_mod[_section_key(p.path)].append(p)
        else:
            by_mod = module_sections
        for mod, pgs in sorted(by_mod.items()):
            lines.append(f"## Module: {mod}")
            lines.append("")
            for p in pgs:
                lines.append(self._render_page_line(p))
            lines.append("")
        lines.append(self._render_cross_ref(pages))
        return "\n".join(lines).strip() + "\n"

    async def generate_and_persist(
        self,
        business_id: str,
        repository: str,
        persist_fn: Any | None = None,
    ) -> str:
        pages = await self._fetch_pages(repository)
        threshold = int(getattr(self._cfg, "snapshot_layer_page_threshold", 100))
        if len(pages) >= threshold:
            layered = await self.generate_layered(business_id, repository)
            if callable(persist_fn):
                await persist_fn(layered, repository, layered=True)
            return layered.get("index", "")
        one = await self.generate(business_id, repository)
        if callable(persist_fn):
            await persist_fn({"(single)": one}, repository, layered=False)
        return one
