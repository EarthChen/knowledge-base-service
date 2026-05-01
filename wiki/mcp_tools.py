"""MCP tool definitions and handlers for Wiki generation."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from log import get_logger
from wiki.lint import WikiLintService

log = get_logger(__name__)
from wiki.models import WikiPage, parse_scope
from wiki.wiki_docs_exporter import WikiDocsExporter, export_result_to_dict


@runtime_checkable
class WikiPipeline(Protocol):
    """Minimal async interface for wiki data/query operations (MCP-exposed; mockable in tests)."""

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
        "name": "wiki_search",
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
                "page_context": {
                    "type": "string",
                    "description": "Optional page path to boost context from linked pages",
                },
            },
            "required": ["repository", "query"],
        },
    },
    {
        "name": "wiki_export",
        "description": (
            "Write wiki markdown files under target_dir for paths in selected_files "
            "(or all pending create/update when omitted). Skips human-written files lacking the AUTO-GENERATED marker."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {"type": "string", "description": "Repository name in the knowledge base."},
                "target_dir": {"type": "string", "description": "Directory under which markdown files are written."},
                "selected_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Wiki page paths to write; omit to write all pending updates.",
                },
            },
            "required": ["repository", "target_dir"],
        },
    },
    {
        "name": "wiki_get_tree",
        "description": "Get the wiki tree structure for a business, optionally filtered by view type (business_domain or code_structure).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "business_id": {"type": "string", "description": "Business ID", "default": "default"},
                "view": {"type": "string", "enum": ["business_domain", "code_structure"], "default": "business_domain"},
            },
        },
    },
    {
        "name": "wiki_get_related",
        "description": "Get related wiki pages (outgoing and incoming cross-references) for a given page.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page_uid": {"type": "string", "description": "WikiPage UID (e.g. WikiPage:repo:path)"},
            },
            "required": ["page_uid"],
        },
    },
    {
        "name": "wiki_get_domain_overview",
        "description": "Get the domain overview page for a business domain.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain_name": {"type": "string", "description": "Business domain name"},
                "business_id": {"type": "string", "description": "Business ID", "default": "default"},
            },
            "required": ["domain_name"],
        },
    },
    {
        "name": "wiki_get_snapshot",
        "description": (
            "Get a compiled knowledge snapshot of all wiki pages for a repository. "
            "Returns a structured markdown document with page summaries, confidence scores, cross-references, and module organization."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name to get snapshot for",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "wiki_find_implementing_modules",
        "description": (
            "Find code modules that implement a given business domain/capability. "
            "Returns modules with their wiki page paths for reverse lookup from business to code."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "domain_name": {
                    "type": "string",
                    "description": "Business domain name to search for",
                },
                "business_id": {
                    "type": "string",
                    "description": "Business ID (default: 'default')",
                    "default": "default",
                },
            },
            "required": ["domain_name"],
        },
    },
]


class WikiMCPHandler:
    """Holds wiki pipeline components and serves MCP tool calls."""

    def __init__(
        self,
        pipeline: Any | None = None,
        graph: GraphQueryPort | None = None,
        store: Any | None = None,
        wiki_cache: Any | None = None,
        repo_registry: Any | None = None,
        wiki_config: Any | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._graph = graph
        self._store = store
        self._wiki_cache = wiki_cache
        self._repo_registry = repo_registry
        self._wiki_config = wiki_config

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

        try:
            pages = await self._pipeline.generate_wiki(repository, scope_str, mode_str)
        except Exception:
            log.exception("mcp_generate_wiki_failed", repository=repository, scope=scope_str)
            return self._mcp_error("internal_error", "Wiki generation failed unexpectedly")
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

        try:
            page = await self._pipeline.get_wiki_page(repository, scope_str)
        except Exception:
            log.exception("mcp_get_wiki_page_failed", repository=repository, scope=scope_str)
            return self._mcp_error("internal_error", "Failed to retrieve wiki page")
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
            "synthesized": True,
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

        try:
            return await self._pipeline.list_wiki_pages(repository, scope_filter)
        except Exception:
            log.exception("mcp_list_wiki_pages_failed", repository=repository)
            return self._mcp_error("internal_error", "Failed to list wiki pages")

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
        raw_page_context = arguments.get("page_context")
        page_context: str | None = None
        if raw_page_context is not None:
            pc = str(raw_page_context).strip()
            if pc:
                page_context = pc
                log.info("wiki_search_page_context", repository=repository, page_context=pc)
                if scope_filter is None:
                    scope_filter = pc
        try:
            payload = await self._pipeline.search_wiki(
                repository,
                query,
                mode,
                limit,
                min_score,
                scope_filter,
            )
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))
        if isinstance(payload, dict):
            out = {**payload, "synthesized": True}
            if page_context is not None:
                out["page_context"] = page_context
            return out
        return payload

    handle_wiki_search = handle_search_wiki  # alias after the method definition

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

    async def handle_wiki_lint(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Graph store not configured for wiki_lint")
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        scope = str(arguments.get("scope", "all") or "all")
        try:
            from wiki.models import parse_scope
            parse_scope(scope) if scope != "all" else None
        except ValueError:
            return self._mcp_error("invalid_params", f"Invalid scope: must be 'all', 'repo', 'module:<path>', or 'class:<fqn>'")
        try:
            svc = WikiLintService(
                self._store,
                wiki_cache=self._wiki_cache,
                repo_registry=self._repo_registry,
                wiki_config=self._wiki_config,
            )
            payload = await svc.run_lint(repository, scope=scope)
        except Exception:
            import structlog
            structlog.get_logger().exception("wiki_lint failed", repository=repository)
            return self._mcp_error("internal_error", "Wiki lint failed unexpectedly")
        return {"status": "success", **payload}

    async def handle_wiki_export_preview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._wiki_cache is None:
            return self._mcp_error("service_unavailable", "Wiki cache not configured for wiki_export_preview")
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        target_dir = str(arguments.get("target_dir", "")).strip()
        if not target_dir:
            return self._mcp_error("invalid_params", "target_dir parameter is required")
        include_marker = bool(arguments.get("include_auto_generated_marker", True))
        exporter = WikiDocsExporter(wiki_cache=self._wiki_cache)
        try:
            result = await exporter.preview_export(
                repository,
                target_dir,
                include_auto_generated_marker=include_marker,
            )
        except ValueError as exc:
            return self._mcp_error("invalid_params", str(exc))
        return {"status": "success", **export_result_to_dict(result)}

    async def handle_wiki_export(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._wiki_cache is None:
            return self._mcp_error("service_unavailable", "Wiki cache not configured for wiki_export")
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        target_dir = str(arguments.get("target_dir", "")).strip()
        if not target_dir:
            return self._mcp_error("invalid_params", "target_dir parameter is required")
        raw_sel = arguments.get("selected_files")
        selected: list[str] | None
        if raw_sel is None:
            selected = None
        elif isinstance(raw_sel, list):
            selected = [str(x) for x in raw_sel]
        else:
            return self._mcp_error("invalid_params", "selected_files must be an array of strings or omitted")
        exporter = WikiDocsExporter(wiki_cache=self._wiki_cache)
        try:
            result = await exporter.execute_export(repository, target_dir, selected_files=selected)
        except ValueError as exc:
            return self._mcp_error("invalid_params", str(exc))
        return {"status": "success", **export_result_to_dict(result)}

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

    async def handle_wiki_get_tree(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Store not configured")
        business_id = str(arguments.get("business_id", "default")).strip()
        view = str(arguments.get("view", "business_domain")).strip()
        from store.wiki_store import WikiStore

        ws = WikiStore(self._store)
        result = await ws.get_wiki_tree(business_id, view)
        nodes = []
        if result and result.result_set:
            for row in result.result_set:
                nodes.append(
                    {
                        "uid": row[0],
                        "title": row[1],
                        "label": row[2],
                        "depth": row[3],
                        "sort_order": row[4],
                        "path": row[5],
                        "page_type": row[6],
                    },
                )
        return {"business_id": business_id, "view": view, "nodes": nodes}

    async def handle_wiki_get_related(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Store not configured")
        page_uid = str(arguments.get("page_uid", "")).strip()
        if not page_uid:
            return self._mcp_error("invalid_params", "page_uid parameter is required")
        from store.wiki_store import WikiStore

        ws = WikiStore(self._store)
        outgoing = await ws.get_wiki_page_references(page_uid)
        incoming = await ws.get_wiki_page_back_references(page_uid)
        return {
            "page_uid": page_uid,
            "outgoing": outgoing.data if outgoing else [],
            "incoming": incoming.data if incoming else [],
        }

    async def handle_wiki_get_domain_overview(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Store not configured")
        domain_name = str(arguments.get("domain_name", "")).strip()
        if not domain_name:
            return self._mcp_error("invalid_params", "domain_name parameter is required")
        business_id = str(arguments.get("business_id", "default")).strip()
        path = f"/{domain_name}/_overview"
        from store.wiki_store import WikiStore

        ws = WikiStore(self._store)
        result = await ws.get_wiki_page_detail(business_id, path)
        if not result.data:
            return self._mcp_error("not_found", f"No domain overview page for '{domain_name}'")
        row = result.data[0]
        wp = row.get("wp")
        props = dict(wp.properties) if hasattr(wp, "properties") else (wp if isinstance(wp, dict) else {})
        return {
            "domain_name": domain_name,
            "business_id": business_id,
            "content": props.get("content", ""),
            "title": props.get("title", ""),
        }

    async def handle_wiki_get_snapshot(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Store not configured")
        repository = str(arguments.get("repository", "")).strip()
        if not repository:
            return self._mcp_error("invalid_params", "repository parameter is required")
        from wiki.compilation_snapshot import WikiCompilationSnapshot

        snap = WikiCompilationSnapshot(self._store, self._wiki_config)
        try:
            md = await snap.generate("default", repository)
        except Exception as exc:
            return self._mcp_error("internal_error", str(exc))
        return {"repository": repository, "format": "markdown", "content": md}

    async def handle_wiki_find_implementing_modules(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if self._store is None:
            return self._mcp_error("service_unavailable", "Store not configured")
        domain_name = str(arguments.get("domain_name", "")).strip()
        if not domain_name:
            return self._mcp_error("invalid_params", "domain_name parameter is required")
        business_id = str(arguments.get("business_id", "default")).strip()

        from store.wiki_store import WikiStore

        ws = WikiStore(self._store)
        try:
            result = await ws.find_modules_by_domain(domain_name, business_id)
        except Exception:
            log.exception("mcp_find_implementing_modules_failed", domain=domain_name)
            return self._mcp_error("internal_error", "Failed to query implementing modules")
        modules = []
        if result and result.result_set:
            for row in result.result_set:
                modules.append({
                    "uid": row[0],
                    "name": row[1],
                    "path": row[2],
                    "repository": row[3],
                    "wiki_page_path": row[4],
                })
        return {
            "domain_name": domain_name,
            "business_id": business_id,
            "modules": modules,
            "count": len(modules),
        }
