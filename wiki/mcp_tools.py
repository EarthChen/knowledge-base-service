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

    async def search_wiki(
        self,
        repository: str,
        query: str,
        mode: str = "hybrid",
        limit: int = 10,
        min_score: float = 0.0,
        scope: str | None = None,
    ) -> dict[str, Any]:
        ...

    async def ask_about_code(
        self,
        repository: str,
        question: str,
        scope: str | None = None,
        conversation_id: str | None = None,
    ) -> dict[str, Any]:
        ...


@runtime_checkable
class GraphQueryPort(Protocol):
    """Graph traversal for MCP wiki tools (no LLM); implemented by GraphQueryService in production."""

    async def traverse_call_chain(
        self,
        repository: str,
        node_name: str,
        direction: str = "callees",
        max_depth: int = 3,
    ) -> dict[str, Any]:
        ...

    async def find_impact_scope(
        self,
        repository: str,
        node_name: str,
        max_hops: int = 2,
    ) -> dict[str, Any]:
        ...

    async def analyze_pr_impact(
        self,
        repository: str,
        changed_files: list[dict[str, Any]],
    ) -> dict[str, Any]:
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
    {
        "name": "search_wiki",
        "description": (
            "Search generated Wiki pages using hybrid search (graph + vector + full-text). "
            "Returns ranked results with scores, snippets, source locations, and hierarchical context."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository name"},
                "query": {"type": "string", "description": "Search query string"},
                "mode": {
                    "type": "string",
                    "description": (
                        "Search mode: 'hybrid' (default) | 'graph' | 'semantic' | 'keyword'"
                    ),
                    "default": "hybrid",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10)",
                    "default": 10,
                },
                "min_score": {
                    "type": "number",
                    "description": "Minimum relevance score threshold (0.0-1.0)",
                    "default": 0.0,
                },
                "scope": {
                    "type": "string",
                    "description": "Optional wiki page path prefix to filter results (exact path or subtree).",
                },
            },
            "required": ["repository", "query"],
        },
    },
    {
        "name": "ask_about_code",
        "description": (
            "Interactive Q&A about code using Wiki context + hybrid search. "
            "Returns answer with source code references."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository name"},
                "question": {"type": "string", "description": "Natural language question about the code"},
                "scope": {"type": "string", "description": "Optional scope to focus the search"},
                "conversation_id": {"type": "string", "description": "Optional ID for multi-turn conversation"},
            },
            "required": ["repository", "question"],
        },
    },
    {
        "name": "traverse_call_chain",
        "description": (
            "Walk CALLS edges from a Function node to list callees or callers with optional wiki page paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository identifier in the knowledge base."},
                "node_name": {"type": "string", "description": "Function name or FQN to start from."},
                "direction": {
                    "type": "string",
                    "enum": ["callees", "callers"],
                    "description": "callees: root calls others; callers: others call root.",
                    "default": "callees",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum CALLS hops (1–5).",
                    "default": 3,
                },
            },
            "required": ["repository", "node_name"],
        },
    },
    {
        "name": "find_impact_scope",
        "description": (
            "Compute reverse impact along CALLS, IMPORTS, and INHERITS toward a target entity, grouped by hop."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository identifier."},
                "node_name": {"type": "string", "description": "Target function, class, or module name / FQN."},
                "max_hops": {
                    "type": "integer",
                    "description": "Maximum reverse hops (1–3).",
                    "default": 2,
                },
            },
            "required": ["repository", "node_name"],
        },
    },
    {
        "name": "analyze_pr_impact",
        "description": (
            "Map changed files to code entities, expand one hop upstream in the graph, "
            "and summarize affected WikiPage paths with impact levels."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository identifier."},
                "changed_files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "status": {"type": "string"},
                        },
                        "required": ["path", "status"],
                    },
                    "description": "List of changed file paths and git status codes.",
                },
            },
            "required": ["repository", "changed_files"],
        },
    },
]


class WikiMCPHandler:
    """Holds wiki pipeline components and serves MCP tool calls."""

    def __init__(self, pipeline: WikiPipeline | None = None, graph: GraphQueryPort | None = None) -> None:
        self._pipeline = pipeline
        self._graph = graph

    @staticmethod
    def _mcp_error(code: str, message: str) -> dict[str, Any]:
        return {"error": {"code": code, "message": message}}

    def _not_configured(self) -> dict[str, Any]:
        return self._mcp_error("service_unavailable", "Wiki pipeline not configured")

    def _graph_not_configured(self) -> dict[str, Any]:
        return self._mcp_error("service_unavailable", "Graph traversal not configured")

    async def handle_generate_wiki(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        scope_raw = arguments.get("scope", "")
        if scope_raw is None or not str(scope_raw).strip():
            return self._mcp_error("invalid_params", "scope parameter is required")
        scope_str = str(scope_raw).strip()
        try:
            parse_scope(scope_str)
        except ValueError as exc:
            return self._mcp_error("invalid_scope", str(exc))
        mode = arguments.get("mode", "structure")
        mode_str = str(mode) if mode is not None else "structure"
        if mode_str not in ("full", "structure"):
            return self._mcp_error("invalid_params", f"Invalid mode '{mode_str}': must be 'full' or 'structure'")

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
            return self._mcp_error("invalid_params", "repository parameter is required")
        scope_raw = arguments.get("scope", "")
        if scope_raw is None or not str(scope_raw).strip():
            return self._mcp_error("invalid_params", "scope parameter is required")
        scope_str = str(scope_raw).strip()
        try:
            parse_scope(scope_str)
        except ValueError as exc:
            return self._mcp_error("invalid_scope", str(exc))

        page = await self._pipeline.get_wiki_page(repository, scope_str)
        if page is None:
            return self._mcp_error("not_found", f"Wiki page not found for scope '{scope_str}'")
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
            return self._mcp_error("invalid_params", "repository parameter is required")
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
                    return self._mcp_error("invalid_scope", str(exc))
                scope_filter = s

        return await self._pipeline.list_wiki_pages(repository, scope_filter)

    async def handle_search_wiki(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        query = str(arguments.get("query", "")).strip()
        if not query:
            return self._mcp_error("invalid_params", "query parameter is required")
        mode = arguments.get("mode", "hybrid")
        try:
            limit = int(arguments.get("limit", 10))
        except (ValueError, TypeError):
            return self._mcp_error("invalid_params", "limit must be an integer")
        try:
            min_score = float(arguments.get("min_score", 0.0))
        except (ValueError, TypeError):
            return self._mcp_error("invalid_params", "min_score must be a number")
        raw_scope = arguments.get("scope")
        scope_filter: str | None = None
        if raw_scope is not None:
            s = str(raw_scope).strip()
            if s:
                scope_filter = s
        try:
            return await self._pipeline.search_wiki(
                repository,
                query,
                mode,
                limit,
                min_score,
                scope_filter,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))

    async def handle_ask_about_code(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._pipeline is None:
            return self._not_configured()
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        question = str(arguments.get("question", "")).strip()
        if not question:
            return self._mcp_error("invalid_params", "question parameter is required")
        scope = arguments.get("scope")
        conversation_id = arguments.get("conversation_id")
        try:
            return await self._pipeline.ask_about_code(repository, question, scope, conversation_id)
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))

    def _require_graph(self) -> dict[str, Any] | None:
        if self._graph is None:
            return self._graph_not_configured()
        return None

    @staticmethod
    def _parse_direction(raw: object, default: str = "callees") -> str:
        s = str(raw) if raw is not None else default
        s = s.strip() or default
        return s if s in ("callees", "callers") else default

    @staticmethod
    def _clamp_int(value: object, default: int, min_v: int, max_v: int) -> int:
        try:
            n = int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            n = default
        return max(min_v, min(n, max_v))

    async def handle_traverse_call_chain(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if (err := self._require_graph()) is not None:
            return err
        assert self._graph is not None
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        node_name = str(arguments.get("node_name", "")).strip()
        if not node_name:
            return self._mcp_error("invalid_params", "node_name parameter is required")
        direction = self._parse_direction(arguments.get("direction", "callees"), "callees")
        max_depth = self._clamp_int(arguments.get("max_depth", 3), 3, 1, 5)
        try:
            return await self._graph.traverse_call_chain(
                repository=repository,
                node_name=node_name,
                direction=direction,
                max_depth=max_depth,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))

    async def handle_find_impact_scope(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if (err := self._require_graph()) is not None:
            return err
        assert self._graph is not None
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        node_name = str(arguments.get("node_name", "")).strip()
        if not node_name:
            return self._mcp_error("invalid_params", "node_name parameter is required")
        max_hops = self._clamp_int(arguments.get("max_hops", 2), 2, 1, 3)
        try:
            return await self._graph.find_impact_scope(
                repository=repository,
                node_name=node_name,
                max_hops=max_hops,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))

    async def handle_analyze_pr_impact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if (err := self._require_graph()) is not None:
            return err
        assert self._graph is not None
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        raw_cf = arguments.get("changed_files")
        if raw_cf is None:
            return self._mcp_error("invalid_params", "changed_files parameter is required")
        if not isinstance(raw_cf, list):
            return self._mcp_error("invalid_params", "changed_files must be a list")
        changed_files: list[dict[str, Any]] = []
        for item in raw_cf:
            if isinstance(item, dict):
                changed_files.append(
                    {
                        "path": str(item.get("path", "")),
                        "status": str(item.get("status", "")),
                    },
                )
            else:
                changed_files.append({"path": "", "status": ""})
        if not changed_files:
            return {
                "affected_pages": [],
                "summary": {"high_impact": 0, "medium_impact": 0, "total_affected_pages": 0},
            }
        try:
            return await self._graph.analyze_pr_impact(
                repository=repository,
                changed_files=changed_files,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))
