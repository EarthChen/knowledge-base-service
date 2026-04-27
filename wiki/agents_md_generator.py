"""Auto-generate AGENTS.md from wiki metadata for AI coding agents."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class AgentsMdGenerator:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    async def generate(self, repository: str, business_id: str = "default") -> str:
        """Generate AGENTS.md content from wiki page metadata."""
        _ = business_id
        pages_q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "RETURN wp.title AS title, wp.path AS page_path, wp.page_type AS type "
            "ORDER BY wp.path"
        )
        result = await self._graph.execute_query(pages_q, {"repo": repository})
        rows = getattr(result, "data", []) or []
        pages = [r for r in rows if isinstance(r, dict)]

        stats_q = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE coalesce(wp.deprecated, false) = false "
            "RETURN count(wp) AS n, avg(coalesce(wp.confidence, 0)) AS avg_conf"
        )
        stats_result = await self._graph.execute_query(stats_q, {"repo": repository})
        stats_rows = getattr(stats_result, "data", []) or []
        stat0: dict[str, Any] = (
            stats_rows[0] if stats_rows and isinstance(stats_rows[0], dict) else {}
        )
        n_pages = int(stat0.get("n", 0) or 0)
        raw_avg = stat0.get("avg_conf")
        avg_conf = float(raw_avg) if raw_avg is not None else 0.0

        lines: list[str] = [
            "# Knowledge Base — Agent Guide",
            "",
            f"> Auto-generated from wiki for repository `{repository}`.",
            "",
            "## Available Knowledge Pages",
            "",
        ]

        if not pages:
            lines.append("_No wiki pages generated yet. Run wiki generation first._")
            lines.append("")
            lines.extend(self._knowledge_at_glance_lines(n_pages, avg_conf))
            return "\n".join(lines)

        sections: dict[str, list[dict[str, Any]]] = {}
        for p in pages:
            ppath = p.get("page_path", "")
            section = ppath.split("/")[0] if "/" in ppath else "root"
            sections.setdefault(section, []).append(p)

        for section_name, section_pages in sorted(sections.items()):
            lines.append(f"### {section_name}")
            lines.append("")
            for p in section_pages:
                title = p.get("title", "Untitled")
                ppath = p.get("page_path", "")
                ptype = p.get("type", "")
                type_badge = f" ({ptype})" if ptype else ""
                lines.append(f"- **{title}**{type_badge}: `{ppath}`")
            lines.append("")

        lines.extend(self._knowledge_at_glance_lines(n_pages, avg_conf))
        lines.extend([
            "## How to Use",
            "",
            "Use `wiki_search` to find relevant knowledge, `wiki_explain` to get details about specific entities,",
            "and `wiki_qa` to ask questions about the codebase.",
            "",
        ])

        return "\n".join(lines)

    def _knowledge_at_glance_lines(self, n_pages: int, avg_conf: float) -> list[str]:
        return [
            "## Knowledge at a glance",
            "",
            f"- **Pages:** {n_pages}",
            f"- **Average confidence:** {avg_conf:.2f}",
            "",
            "For a full map of pages and cross-refs, call MCP tool `wiki_get_snapshot` with this repository, or read",
            "`wiki_snapshot.md` in exports.",
            "",
        ]
