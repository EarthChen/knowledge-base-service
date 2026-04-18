"""MCP tool definitions and handlers for Wiki generation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from wiki.models import WikiPage, parse_scope


@runtime_checkable
class WikiPipeline(Protocol):
    """Minimal async interface for wiki generation used by MCP (mockable in tests)."""

    async def generate_wiki(self, repository: str, scope: str, mode: str) -> list[WikiPage]:
        ...

    async def get_wiki_page(self, repository: str, scope: str) -> WikiPage | None:
        ...

    async def list_wiki_pages(self, repository: str, scope: str | None) -> dict[str, Any]:
        ...


WIKI_MCP_TOOLS_MANIFEST: list[dict[str, Any]] = [
    {
        "name": "generate_wiki",
        "description": (
            "Generate structured wiki documentation for indexed code in a repository. "
            "Returns WikiPage entries with titles, content, diagrams, and source_locations."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name or identifier in the knowledge base.",
                },
                "scope": {
                    "type": "string",
                    "description": "Generation scope: 'repo', 'module:<path>', or 'class:<fqn>'.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "structure"],
                    "description": "full = rich content; structure = layout and skeleton.",
                    "default": "structure",
                },
            },
            "required": ["repository", "scope"],
        },
    },
    {
        "name": "get_wiki_page",
        "description": (
            "Fetch a single generated wiki page by scope (module:<path> or class:<fqn>)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name or identifier.",
                },
                "scope": {
                    "type": "string",
                    "description": "Page scope: 'module:<path>' or 'class:<fqn>'.",
                },
            },
            "required": ["repository", "scope"],
        },
    },
    {
        "name": "list_wiki_pages",
        "description": (
            "List generated wiki pages as a directory tree with metadata, optionally filtered by scope."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name or identifier.",
                },
                "scope": {
                    "type": "string",
                    "description": "Optional subtree filter: 'repo', 'module:<path>', or 'class:<fqn>'.",
                },
            },
            "required": ["repository"],
        },
    },
]


class WikiMCPHandler:
    """Holds wiki pipeline components and serves MCP tool calls."""

    def __init__(self, pipeline: WikiPipeline | None = None) -> None:
        self._pipeline = pipeline

    def _not_configured(self) -> dict[str, Any]:
        return {"error": "Wiki pipeline not configured"}

    async def handle_generate_wiki(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return {"error": "repository parameter is required"}
        scope_raw = arguments.get("scope", "")
        if scope_raw is None or not str(scope_raw).strip():
            return {"error": "scope parameter is required"}
        scope_str = str(scope_raw).strip()
        try:
            parse_scope(scope_str)
        except ValueError as exc:
            return {"error": str(exc)}
        mode = arguments.get("mode", "structure")
        mode_str = str(mode) if mode is not None else "structure"
        if mode_str not in ("full", "structure"):
            return {"error": f"Invalid mode '{mode_str}': must be 'full' or 'structure'"}

        pages = await self._pipeline.generate_wiki(repository, scope_str, mode_str)
        return {
            "status": "success",
            "repository": repository,
            "pages": [p.to_dict() for p in pages],
        }

    async def handle_get_wiki_page(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return {"error": "repository parameter is required"}
        scope_raw = arguments.get("scope", "")
        if scope_raw is None or not str(scope_raw).strip():
            return {"error": "scope parameter is required"}
        scope_str = str(scope_raw).strip()
        try:
            parse_scope(scope_str)
        except ValueError as exc:
            return {"error": str(exc)}

        page = await self._pipeline.get_wiki_page(repository, scope_str)
        if page is None:
            return {"error": f"Wiki page not found for scope '{scope_str}'"}
        pd = page.to_dict()
        return {
            "repository": repository,
            "scope": scope_str,
            "page": pd,
            "content": page.content,
            "diagrams": pd.get("diagrams", []),
            "source_locations": pd.get("source_locations", []),
        }

    async def handle_list_wiki_pages(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return {"error": "repository parameter is required"}
        raw_scope = arguments.get("scope")
        scope_filter: str | None
        if raw_scope is None:
            scope_filter = None
        else:
            s = str(raw_scope).strip()
            if not s:
                scope_filter = None
            else:
                try:
                    parse_scope(s)
                except ValueError as exc:
                    return {"error": str(exc)}
                scope_filter = s

        return await self._pipeline.list_wiki_pages(repository, scope_filter)
