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

        lines.extend([
            "## How to Use",
            "",
            "Use `wiki_search` to find relevant knowledge, `wiki_explain` to get details about specific entities,",
            "and `wiki_qa` to ask questions about the codebase.",
            "",
        ])

        return "\n".join(lines)
