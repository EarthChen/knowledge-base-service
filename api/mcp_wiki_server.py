"""MCP-compatible wiki knowledge server exposing 5 tools."""
from __future__ import annotations

from typing import Any

from log import get_logger

log = get_logger(__name__)


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "wiki_search",
        "description": "Search the code knowledge base for entities, concepts, and documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "repository": {"type": "string", "description": "Repository name (optional)"},
                "limit": {"type": "integer", "description": "Max results", "default": 5},
            },
            "required": ["query"],
        },
    },
    {
        "name": "wiki_explain",
        "description": "Get a detailed explanation of a code entity (class, function, module).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity": {"type": "string", "description": "Entity name or path"},
                "repository": {"type": "string", "description": "Repository name"},
            },
            "required": ["entity", "repository"],
        },
    },
    {
        "name": "wiki_navigate",
        "description": "Browse the wiki page tree structure.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Wiki path to browse", "default": "/"},
                "repository": {"type": "string", "description": "Repository name"},
            },
            "required": ["repository"],
        },
    },
    {
        "name": "wiki_qa",
        "description": "Ask a question about the codebase using wiki knowledge.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Question to ask"},
                "repository": {"type": "string", "description": "Repository name"},
            },
            "required": ["question", "repository"],
        },
    },
    {
        "name": "wiki_impact",
        "description": "Analyze the impact of changing specific files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "files": {"type": "array", "items": {"type": "string"}, "description": "Changed file paths"},
                "repository": {"type": "string", "description": "Repository name"},
            },
            "required": ["files", "repository"],
        },
    },
]


class MCPWikiServer:
    """Lightweight MCP-compatible wiki server."""

    def __init__(
        self,
        search_service: Any = None,
        wiki_store: Any = None,
        ask_service: Any = None,
        change_detector: Any = None,
    ) -> None:
        self._search = search_service
        self._wiki_store = wiki_store
        self._ask = ask_service
        self._change_detector = change_detector

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Route tool call to the appropriate handler."""
        handler = getattr(self, f"_handle_{tool_name}", None)
        if handler is None:
            return {"error": f"Unknown tool: {tool_name}"}
        try:
            return await handler(arguments)
        except Exception as exc:
            log.warning("mcp_tool_call_failed", tool=tool_name, error=str(exc))
            return {"error": str(exc)}

    async def _handle_wiki_search(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._search is None:
            return {"error": "Search service not configured"}
        query = args.get("query", "")
        repo = args.get("repository", "")
        limit = args.get("limit", 5)
        result = await self._search.search(repo, query, mode="hybrid", limit=limit, min_score=0.0)
        results = getattr(result, "results", [])
        return {
            "results": [
                {"title": r.title, "page_path": r.page_path, "score": r.score, "snippet": r.snippet}
                for r in results[:limit]
            ]
        }

    async def _handle_wiki_explain(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._wiki_store is None:
            return {"error": "Wiki store not configured"}
        from wiki.entity_explainer import EntityExplainer

        explainer = EntityExplainer(self._wiki_store)
        return await explainer.explain(args.get("repository", ""), args.get("entity", ""))

    async def _handle_wiki_navigate(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._wiki_store is None:
            return {"error": "Wiki store not configured"}
        repo = args.get("repository", "")
        path = args.get("path", "/")
        cypher = (
            "MATCH (wp:WikiPage {repository: $repo}) "
            "WHERE wp.path STARTS WITH $prefix "
            "RETURN wp.path AS path, wp.title AS title, wp.page_type AS type "
            "ORDER BY wp.path LIMIT 50"
        )
        result = await self._wiki_store.execute_query(cypher, {"repo": repo, "prefix": path})
        rows = getattr(result, "data", []) or []
        pages = [r for r in rows if isinstance(r, dict)]
        return {"path": path, "pages": pages}

    async def _handle_wiki_qa(self, args: dict[str, Any]) -> dict[str, Any]:
        return {"status": "not_implemented", "question": args.get("question", "")}

    async def _handle_wiki_impact(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._change_detector is None:
            return {"error": "Change detector not configured"}
        files = args.get("files", [])
        repo = args.get("repository", "")

        affected = await self._change_detector.detect_from_file_list(repo, files, trigger="mcp")

        from wiki.compact_formatter import CompactFormatter

        formatter = CompactFormatter()
        return formatter.format_impact({
            "page_uids": affected.page_uids,
            "affected_entities": affected.affected_entities,
            "trigger": affected.trigger,
        })
