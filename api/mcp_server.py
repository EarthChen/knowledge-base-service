"""MCP Server interface for the RAG knowledge base (query-only).

Exposes the knowledge base as MCP tools that can be injected into
Cursor Agent sessions, enabling the agent to query the code knowledge graph.
Indexing is handled through HTTP API endpoints, not through MCP tools.

Tools exposed (18 total):
  - rag_query, rag_graph: Hybrid search and graph queries
  - documents: List indexed docs or fetch one by uid
  - get_file_content, get_code_snippet, get_complete_context: On-disk file source and entity context
  - analyze_code: Quality score or index vs disk consistency (mode)
  - analyze_changes: PR review, blast-radius impact, wiki impact scope, wiki file-level PR impact (mode)
  - search_architecture: Classes by layer or discovered HTTP/RPC/Kafka endpoints (mode)
  - get_insights: Dashboard P2 stats and/or per-repo graph anomaly scan (type)
  - index_freshness: Repository index stamp and counts
  - get_wiki_page, list_wiki_pages, search_wiki, wiki_export: Wiki browse/search/export
  - wiki_get_tree, wiki_get_related, wiki_get_domain_overview: Business wiki tree, cross-refs, domain overview
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from auth import Role, TokenInfo
from indexer.config_indexer import _config_file_extension
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from indexer.incremental_indexer import IncrementalIndexer
from log import get_logger
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from store.traversal_store import TraversalStore
from utils.git_utils import looks_like_git_url
from wiki.mcp_tools import WIKI_MCP_TOOLS_MANIFEST, WikiMCPHandler

log = get_logger(__name__)

_MAX_FILE_READ_BYTES = 512 * 1024

_ENTITY_FILTER_LABELS: dict[str, frozenset[str]] = {
    "function": frozenset({str(NodeLabel.FUNCTION)}),
    "class": frozenset({str(NodeLabel.CLASS)}),
    "module": frozenset({str(NodeLabel.MODULE)}),
    "document": frozenset({str(NodeLabel.DOCUMENT)}),
}


def _normalize_entity_type_arg(raw: Any) -> str | None:
    if raw is None:
        return None
    s = str(raw).strip()
    return s.lower() if s else None


def _filter_semantic_matches_by_entity_type(
    matches: list[dict[str, Any]],
    entity_type: str | None,
) -> list[dict[str, Any]]:
    if not entity_type:
        return matches
    if entity_type in ("flow", "concept"):
        return matches
    allowed = _ENTITY_FILTER_LABELS.get(entity_type)
    if not allowed:
        return matches
    return [m for m in matches if m.get("type") in allowed]


def _filter_graph_context_by_entity_type(
    graph_context: list[dict[str, Any]],
    entity_type: str | None,
) -> list[dict[str, Any]]:
    if not entity_type:
        return graph_context
    if entity_type in ("flow", "concept"):
        return graph_context
    allowed = _ENTITY_FILTER_LABELS.get(entity_type)
    if not allowed:
        return graph_context
    fn_label = str(NodeLabel.FUNCTION)
    out: list[dict[str, Any]] = []
    for item in graph_context:
        t = item.get("type", "")
        if t in allowed:
            out.append(item)
        elif t == "business_flow" and fn_label in allowed:
            out.append(item)
    return out


def _mcp_error(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message}}


def _resolve_repo_base_path(repository: str, repo_registry: Any | None = None) -> Path | None:
    """Resolve repository name to its local clone directory.

    Security: rejects any repository value that resolves outside clone_base_path.
    When the graph uses a canonical name that differs from the clone folder (see
    ``RepoRegistry`` + ``GitManager``), ``repo_registry`` is used to find the git URL
    and the same on-disk path as indexing.
    """
    from config import get_settings
    from services.git_manager import resolve_repo_clone_root

    return resolve_repo_clone_root(repository, get_settings().git, repo_registry)


# Minimum role per MCP tool name. Omitted tools default to ``Role.VIEWER``.
MCP_TOOL_MIN_ROLE: dict[str, Role] = {
    "wiki_export": Role.EDITOR,
}
TOOL_ROLES: dict[str, Role] = MCP_TOOL_MIN_ROLE


_DOC_NUMBERED_HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)[\.\s]")


def _mcp_relative_document_path(file_path: str, repository: str | None) -> str:
    """Strip clone/base prefix from absolute paths (same logic as main list/get documents)."""
    if not file_path:
        return file_path
    normalized = file_path.replace("\\", "/")
    if repository:
        marker = f"/{repository}/"
        idx = normalized.find(marker)
        if idx != -1:
            return normalized[idx + len(marker) :]
    return normalized


def _mcp_infer_section_levels(sections: list[dict[str, Any]], file_path: str | None = None) -> None:
    heading_levels: dict[str, int] = {}

    if file_path:
        try:
            fpath = Path(file_path).resolve()
            if fpath.is_file() and ".." not in Path(file_path).parts:
                raw = fpath.read_text(encoding="utf-8")
                for line in raw.split("\n"):
                    stripped = line.lstrip()
                    if stripped.startswith("#"):
                        hashes = len(stripped) - len(stripped.lstrip("#"))
                        title = stripped[hashes:].strip()
                        heading_levels[title] = hashes
        except OSError:
            pass

    if heading_levels:
        for s in sections:
            title = s.get("title", "")
            clean_title = title.rsplit(" > ", 1)[-1] if " > " in title else title
            if clean_title in heading_levels:
                s["level"] = heading_levels[clean_title]
        return

    prev_level = 2
    for i, s in enumerate(sections):
        title = s.get("title", "")
        m = _DOC_NUMBERED_HEADING_RE.match(title)
        if m:
            dots = m.group(1).count(".")
            s["level"] = 2 + dots
        elif i == 0:
            s["level"] = 1
        else:
            s["level"] = prev_level
        prev_level = s["level"]


def _format_list_documents_mcp(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_uid: dict[str, dict[str, Any]] = {}
    for r in result_rows:
        uid = r.get("uid")
        if not uid:
            continue
        if uid not in by_uid:
            repo = r.get("repository")
            raw_file = r.get("file") or ""
            by_uid[uid] = {
                "file": _mcp_relative_document_path(raw_file, repo),
                "title": r.get("title") or r.get("name") or "",
                "repository": repo,
                "uid": uid,
                "content_hash": r.get("content_hash"),
                "sections": [],
            }
        sec_uid = r.get("sec_uid")
        if sec_uid:
            by_uid[uid]["sections"].append({
                "title": r.get("sec_name") or r.get("sec_title") or "",
                "uid": sec_uid,
                "start_line": r.get("sec_start_line"),
            })

    documents = sorted(
        by_uid.values(),
        key=lambda d: (d.get("repository") or "", d.get("file") or ""),
    )
    for d in documents:
        d["sections"].sort(key=lambda s: (s.get("start_line") is None, s.get("start_line") or 0))

    return {"documents": documents, "total": len(documents)}


def _format_get_document_mcp(result_rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = result_rows[0]
    repo = first.get("repository")
    raw_file = first.get("file") or ""

    sections: list[dict[str, Any]] = []
    for r in result_rows:
        suid = r.get("section_uid")
        if not suid:
            continue
        sections.append({
            "title": r.get("section_name") or r.get("section_title") or "",
            "content": r.get("content") or "",
            "start_line": r.get("start_line"),
            "uid": suid,
            "level": r.get("level"),
        })

    has_stored_levels = any(s.get("level") is not None for s in sections)
    if not has_stored_levels:
        _mcp_infer_section_levels(sections, file_path=first.get("file"))

    for s in sections:
        if s.get("level") is None:
            s["level"] = 2

    return {
        "title": first.get("title") or "",
        "file": _mcp_relative_document_path(raw_file, repo),
        "repository": repo,
        "sections": sections,
    }


MCP_TOOLS_MANIFEST = [
    {
        "name": "rag_query",
        "description": (
            "Search the code knowledge base using natural language. "
            "Finds semantically similar functions, classes, and documentation, "
            "then expands results through call graphs and inheritance trees. "
            "Uses intent-aware query routing to balance keyword vs semantic weights. "
            "Reranking (BAAI/bge-reranker-v2-m3) can be enabled via RERANK__ENABLED=true in .env for improved precision."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query about the codebase.",
                },
                "k": {
                    "type": "integer",
                    "description": "Number of top results to return.",
                    "default": 5,
                },
                "expand_depth": {
                    "type": "integer",
                    "description": "Depth of graph expansion from semantic matches.",
                    "default": 2,
                },
                "entity_type": {
                    "type": "string",
                    "description": (
                        "Filter by entity type: 'function', 'class', 'module', 'document', 'flow', 'concept'. "
                        "When 'flow' or 'concept', searches business entities."
                    ),
                },
                "repository": {
                    "type": "string",
                    "description": "Filter results to a specific repository (Cypher-level filtering).",
                },
                "repositories": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Search across multiple repositories simultaneously. "
                        "Results are fused by score. Max 10 repositories."
                    ),
                },
                "language": {
                    "type": "string",
                    "description": (
                        "Filter results by programming language: "
                        "'python', 'java', 'go', 'javascript', 'typescript'."
                    ),
                },
                "use_child_chunks": {
                    "type": "boolean",
                    "description": (
                        "When true, use chunk-level vector search with parent context "
                        "instead of whole-entity embeddings."
                    ),
                    "default": False,
                },
                "use_query_router": {
                    "type": "boolean",
                    "description": (
                        "When true (default), apply intent-aware routing for keyword vs semantic weights."
                    ),
                    "default": True,
                },
                "use_query_expansion": {
                    "type": "boolean",
                    "description": (
                        "When true (default), expand the query using graph neighbors before retrieval."
                    ),
                    "default": True,
                },
                "per_file_cap": {
                    "type": "integer",
                    "description": (
                        "Max semantic matches retained per source file after fusion (0 disables capping)."
                    ),
                    "default": 3,
                },
                "offset": {
                    "type": "integer",
                    "description": "Pagination offset into merged semantic results (after sort).",
                    "default": 0,
                },
                "enable_bm25": {
                    "type": "boolean",
                    "description": "Include BM25 full-text search in hybrid retrieval fusion.",
                    "default": True,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "rag_graph",
        "description": (
            "Execute structured graph queries on the code knowledge graph. "
            "Supports: call_chain, inheritance_tree, class_methods, "
            "module_dependencies, find_entity, file_entities, raw_cypher."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query_type": {
                    "type": "string",
                    "enum": [
                        "call_chain",
                        "inheritance_tree",
                        "class_methods",
                        "module_dependencies",
                        "reverse_dependencies",
                        "find_entity",
                        "file_entities",
                        "graph_stats",
                        "raw_cypher",
                        "business_flow",
                        "flows_for_function",
                        "related_concepts",
                        "explore_domain",
                        "flow_dependencies",
                        "blast_radius",
                    ],
                    "description": "Type of graph query to execute.",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Entity name for the query (function, class, or module name). "
                        "For blast_radius, comma-separated names are accepted when 'names' is omitted."
                    ),
                },
                "file": {
                    "type": "string",
                    "description": "File path for file_entities query.",
                },
                "depth": {
                    "type": "integer",
                    "description": "Traversal depth for call_chain/inheritance queries.",
                    "default": 3,
                },
                "direction": {
                    "type": "string",
                    "enum": ["upstream", "downstream", "children", "parents"],
                    "description": "Direction for call_chain or inheritance queries.",
                    "default": "downstream",
                },
                "cypher": {
                    "type": "string",
                    "description": "Raw Cypher query (for raw_cypher type only).",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["function", "class", "any"],
                    "description": "Entity type filter for find_entity.",
                    "default": "any",
                },
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "For blast_radius: entity names to analyze (Function/Class/Module). "
                        "Alternatively pass comma-separated names via 'name'."
                    ),
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository scope (blast_radius and other filtered traversals).",
                },
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "documents",
        "description": (
            "Browse indexed documentation: without uid, list document nodes with section metadata; "
            "with uid, return full document content (root + sections) for that document node."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {
                    "type": "string",
                    "description": (
                        "Document node uid from a prior list or graph results. "
                        "When set, returns a single document; when omitted, lists documents."
                    ),
                },
                "repository": {
                    "type": "string",
                    "description": "When listing (no uid), optionally filter by repository name.",
                },
            },
        },
    },
    {
        "name": "get_code_snippet",
        "description": (
            "Retrieve the source code snippet for a code entity (Function or Class) by its graph node uid. "
            "Use after rag_query or get_complete_context to fetch full source."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "node_uid": {
                    "type": "string",
                    "description": "Graph node uid from search results (semantic_matches or graph_context).",
                },
            },
            "required": ["node_uid"],
        },
    },
    {
        "name": "analyze_code",
        "description": (
            "Code analysis: mode 'quality' computes a 0–100 heuristic score for a Function or Class uid; "
            "mode 'consistency' verifies the index against on-disk files for a repository (ghost/missing nodes)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["quality", "consistency"],
                    "default": "quality",
                    "description": "quality: score one entity; consistency: verify repo vs graph",
                },
                "entity_uid": {
                    "type": "string",
                    "description": "Graph node uid (required for mode quality)",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["function", "class"],
                    "description": "Optional entity kind for quality scoring",
                },
                "repository": {
                    "type": "string",
                    "description": "Repository name or path (required for mode consistency)",
                },
            },
        },
    },
    {
        "name": "search_architecture",
        "description": (
            "Architecture discovery: mode 'layers' lists classes (with methods) filtered by architecture layer; "
            "mode 'endpoints' lists discovered HTTP, RPC, and Kafka endpoints (optional repository filter)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["layers", "endpoints"],
                    "default": "layers",
                    "description": "layers: class search by layer; endpoints: API surface from the graph",
                },
                "layer": {
                    "type": "string",
                    "enum": [
                        "presentation",
                        "business",
                        "data_access",
                        "rpc",
                        "messaging",
                        "infrastructure",
                        "model",
                        "unknown",
                    ],
                    "description": "Required when mode is layers",
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository scope (both modes)",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max classes (layers mode), capped at 500",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Pagination offset (layers mode)",
                },
                "search": {
                    "type": "string",
                    "description": "Substring on class name, case-insensitive (layers mode)",
                },
            },
        },
    },
    {
        "name": "analyze_changes",
        "description": (
            "Change and impact analysis (pick mode): "
            "'pr_review' — diff/branch-based PR review context; "
            "'impact' — blast radius from changed function names; "
            "'impact_scope' — wiki-scoped reverse impact along CALLS/IMPORTS/INHERITS; "
            "'wiki_pr_impact' — map changed files to entities and affected wiki paths."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["pr_review", "impact", "impact_scope", "wiki_pr_impact"],
                    "description": "Which analysis to run",
                },
                "diff_text": {"type": "string", "description": "pr_review: unified diff"},
                "branch": {"type": "string"},
                "base_branch": {"type": "string", "default": "master"},
                "repo_path": {"type": "string"},
                "repo_url": {"type": "string"},
                "repository": {"type": "string", "description": "Repository scope where applicable"},
                "max_depth": {"type": "integer", "default": 3, "description": "pr_review / impact depth"},
                "changed_functions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "impact: modified function names",
                },
                "node_name": {
                    "type": "string",
                    "description": "impact_scope: target function/class/module name or FQN",
                },
                "max_hops": {
                    "type": "integer",
                    "default": 2,
                    "description": "impact_scope: reverse hop count (1–3)",
                },
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
                    "description": "wiki_pr_impact: git changed file list",
                },
            },
            "required": ["mode"],
        },
    },
    {
        "name": "get_complete_context",
        "description": (
            "Assemble full context for an entity in one call: source snippet, docstring, "
            "one-hop call chain (callers and callees), class hierarchy (for classes), "
            "related business flows, and matching wiki page text. "
            "Respects max_tokens by trimming less critical sections first."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Function or class name (or substring matched by hybrid search)",
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository name to scope the entity and wiki lookup",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Approximate token budget for the assembled context payload",
                    "default": 8000,
                },
            },
            "required": ["entity_name"],
        },
    },
    {
        "name": "get_insights",
        "description": (
            "Knowledge graph insights: type 'dashboard' returns global P2 enrichment aggregates; "
            "type 'graph' runs per-repository architecture anomaly analysis; "
            "type 'all' returns both (repository required for the graph portion)."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["dashboard", "graph", "all"],
                    "default": "dashboard",
                    "description": "Which insight bundle to compute",
                },
                "repository": {
                    "type": "string",
                    "description": "Required when type is graph or all",
                },
            },
        },
    },
    {
        "name": "index_freshness",
        "description": (
            "Report index freshness for a stamped repository: latest node indexed_at, "
            "total node count, and commit_sha from the last indexing run when git metadata was captured."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name as stored on indexed nodes.",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "get_file_content",
        "description": (
            "Read the raw source content of a file from an indexed repository. "
            "Returns the full file content or a specific line range. "
            "Use this when code snippets from search results are truncated and you need the complete source."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name as indexed.",
                },
                "file_path": {
                    "type": "string",
                    "description": (
                        "Relative file path within the repository (e.g. "
                        "'src/main/java/com/example/Service.java')."
                    ),
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number (1-based, inclusive). Omit to read from beginning.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number (1-based, inclusive). Omit to read to end.",
                },
            },
            "required": ["repository", "file_path"],
        },
    },
] + WIKI_MCP_TOOLS_MANIFEST


class KnowledgeBaseMCPHandler:
    """Handles MCP tool calls for the knowledge base."""

    def __init__(
        self,
        hybrid_svc: HybridQueryService,
        graph_svc: GraphQueryService,
        indexer: IncrementalIndexer,
        doc_indexer: DocumentIndexer | None = None,
        store: FalkorDBStore | None = None,
        embedding_gen: EmbeddingGenerator | None = None,
        wiki_handler: WikiMCPHandler | None = None,
        deep_search_engine: Any | None = None,
        task_status_fn: Callable[[str], dict[str, Any] | None] | None = None,
        repo_registry: Any | None = None,
    ) -> None:
        self._hybrid = hybrid_svc
        self._graph = graph_svc
        self._indexer = indexer
        self._doc_indexer = doc_indexer
        self._store = store
        self._traversal = TraversalStore(store) if store is not None else None
        self._embedding = embedding_gen
        self._wiki = wiki_handler if wiki_handler is not None else WikiMCPHandler(None)
        self._deep_search_engine = deep_search_engine
        self._task_status_fn = task_status_fn
        self._repo_registry = repo_registry

    def get_tools_manifest(self) -> list[dict[str, Any]]:
        return MCP_TOOLS_MANIFEST

    async def handle_tool_call(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        token_info: TokenInfo | None = None,
    ) -> dict[str, Any]:
        """Dispatch MCP tool calls to the appropriate handler."""
        if token_info is not None:
            minimum = MCP_TOOL_MIN_ROLE.get(tool_name, Role.VIEWER)
            if token_info.role < minimum:
                return _mcp_error(
                    "forbidden",
                    f"This tool requires at least the {minimum.name.lower()} role.",
                )

        handlers = {
            "rag_query": self.handle_rag_query,
            "rag_graph": self.handle_rag_graph,
            "documents": self.handle_documents,
            "get_file_content": self.handle_get_file_content,
            "get_code_snippet": self.handle_get_code_snippet,
            "analyze_code": self.handle_analyze_code,
            "search_architecture": self.handle_search_architecture,
            "analyze_changes": self.handle_analyze_changes,
            "get_complete_context": self.handle_get_complete_context,
            "get_insights": self.handle_get_insights,
            "index_freshness": self.handle_index_freshness,
            "get_wiki_page": self._wiki.handle_get_wiki_page,
            "list_wiki_pages": self._wiki.handle_list_wiki_pages,
            "search_wiki": self._wiki.handle_search_wiki,
            "wiki_export": self._wiki.handle_wiki_export,
            "wiki_get_tree": self._wiki.handle_wiki_get_tree,
            "wiki_get_related": self._wiki.handle_wiki_get_related,
            "wiki_get_domain_overview": self._wiki.handle_wiki_get_domain_overview,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return _mcp_error("unknown_tool", f"Unknown tool: {tool_name}")

        try:
            return await handler(arguments)
        except Exception as exc:
            log.error("mcp_tool_error", tool=tool_name, error=str(exc))
            return _mcp_error("internal_error", "Tool execution failed unexpectedly")

    async def handle_rag_query(self, args: dict[str, Any]) -> dict[str, Any]:
        query_text = args.get("query", "")
        try:
            k = max(1, min(50, int(args.get("k", 5))))
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "k must be an integer between 1 and 50")
        try:
            expand_depth = max(0, min(5, int(args.get("expand_depth", 2))))
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "expand_depth must be an integer between 0 and 5")
        entity_type = _normalize_entity_type_arg(args.get("entity_type"))
        repository = (args.get("repository") or "").strip() or None
        repositories_arg = args.get("repositories")
        use_multi_repo = False
        repository_list: list[str] | None = None
        if repositories_arg is not None:
            if not isinstance(repositories_arg, list):
                return _mcp_error("invalid_params", "repositories must be an array of strings")
            normalized_repos: list[str] = []
            for item in repositories_arg:
                if not isinstance(item, str):
                    return _mcp_error("invalid_params", "repositories must contain only strings")
                s = item.strip()
                if s:
                    normalized_repos.append(s)
            if len(normalized_repos) > 10:
                return _mcp_error("invalid_params", "repositories supports at most 10 entries")
            if len(normalized_repos) == 0:
                repository = None
            elif len(normalized_repos) == 1:
                repository = normalized_repos[0]
            else:
                use_multi_repo = True
                repository_list = normalized_repos
        language = (args.get("language") or "").strip() or None
        try:
            offset = max(0, int(args.get("offset", 0)))
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "offset must be a non-negative integer")

        hybrid_kwargs: dict[str, Any] = {}
        if "use_child_chunks" in args:
            hybrid_kwargs["use_child_chunks"] = bool(args["use_child_chunks"])
        if "use_query_router" in args:
            hybrid_kwargs["use_query_router"] = bool(args["use_query_router"])
        if "use_query_expansion" in args:
            hybrid_kwargs["use_query_expansion"] = bool(args["use_query_expansion"])
        if "enable_bm25" in args:
            hybrid_kwargs["enable_bm25"] = bool(args["enable_bm25"])
        if "per_file_cap" in args:
            try:
                pfc = int(args["per_file_cap"])
                hybrid_kwargs["per_file_cap"] = max(1, min(20, pfc))
            except (TypeError, ValueError):
                return _mcp_error("invalid_params", "per_file_cap must be an integer between 1 and 20")

        if entity_type in ("flow", "concept"):
            if not str(query_text).strip():
                return _mcp_error("invalid_params", "query parameter is required")
            search_type = "flow" if entity_type == "flow" else "concept"
            business = await self._collect_business_search_results(
                str(query_text),
                search_type,
                int(k) if k is not None else 5,
                True,
            )
            semantic_matches: list[dict[str, Any]] = []
            if entity_type == "flow":
                semantic_matches = business.get("flows", [])
            else:
                semantic_matches = business.get("concepts", [])
            return {
                "query": str(query_text),
                "semantic_matches": semantic_matches,
                "graph_context": [],
                "total_results": len(semantic_matches),
                "total": len(semantic_matches),
            }

        if use_multi_repo:
            result = await self._hybrid.search_multi_repo(
                query_text,
                repository_list or [],
                k=k,
                expand_depth=expand_depth,
                language=language,
                offset=offset,
                entity_type=entity_type,
                **hybrid_kwargs,
            )
        else:
            result = await self._hybrid.search_with_context(
                query_text,
                k=k,
                expand_depth=expand_depth,
                repository=repository,
                language=language,
                offset=offset,
                entity_type=entity_type,
                **hybrid_kwargs,
            )
        matches = _filter_semantic_matches_by_entity_type(result["results"], entity_type)
        graph_ctx = _filter_graph_context_by_entity_type(result["graph_context"], entity_type)
        return {
            "query": result["query_text"],
            "semantic_matches": matches,
            "graph_context": graph_ctx,
            "total": result["total"],
            "total_results": result["total"] + len(graph_ctx),
            "offset": result["offset"],
            "limit": result["limit"],
            "confidence": result["confidence"],
        }

    async def handle_rag_graph(self, args: dict[str, Any]) -> dict[str, Any]:
        query_type = args.get("query_type", "")
        name = args.get("name", "")
        depth = args.get("depth", 3)
        direction = args.get("direction", "downstream")

        if query_type == "call_chain":
            result = await self._graph.find_call_chain(name, depth=depth, direction=direction)
            edges = result.params.get("_edges", [])
            return {
                "type": "call_chain", "function": name, "direction": direction,
                "results": result.data, "edges": edges,
            }

        elif query_type == "inheritance_tree":
            result = await self._graph.find_inheritance_tree(name, direction=direction)
            return {"type": "inheritance_tree", "class": name, "direction": direction, "results": result.data}

        elif query_type == "class_methods":
            result = await self._graph.find_class_methods(name)
            return {"type": "class_methods", "class": name, "results": result.data}

        elif query_type == "module_dependencies":
            result = await self._graph.find_module_dependencies(name)
            return {"type": "module_dependencies", "module": name, "results": result.data}

        elif query_type == "reverse_dependencies":
            result = await self._graph.find_reverse_dependencies(name)
            return {"type": "reverse_dependencies", "module": name, "results": result.data}

        elif query_type == "find_entity":
            entity_type = args.get("entity_type", "any")
            result = await self._graph.find_entity(name, entity_type=entity_type)
            return {"type": "find_entity", "name": name, "results": result.data}

        elif query_type == "file_entities":
            file_path = args.get("file", "")
            result = await self._graph.find_file_entities(file_path)
            return {"type": "file_entities", "file": file_path, "results": result.data}

        elif query_type == "graph_stats":
            stats = await self._graph.get_graph_stats()
            return {"type": "graph_stats", "stats": stats}

        elif query_type == "raw_cypher":
            cypher = args.get("cypher", "")
            if not cypher:
                return _mcp_error("invalid_params", "cypher parameter is required for raw_cypher queries")
            result = await self._graph.execute_raw(cypher)
            return {"type": "raw_cypher", "results": result.data}

        elif query_type == "business_flow":
            result = await self._graph.find_business_flow(name, k=depth or 10)
            return {"type": "business_flow", "name": name, "results": result.data}

        elif query_type == "flows_for_function":
            result = await self._graph.find_flows_for_function(name)
            return {"type": "flows_for_function", "function": name, "results": result.data}

        elif query_type == "related_concepts":
            result = await self._graph.find_related_concepts(name)
            return {"type": "related_concepts", "entity": name, "results": result.data}

        elif query_type == "explore_domain":
            result = await self._graph.explore_business_domain(name)
            return {"type": "explore_domain", "category": name, "results": result.data}

        elif query_type == "flow_dependencies":
            result = await self._graph.find_flow_dependencies(name)
            return {"type": "flow_dependencies", "flow": name, "results": result.data}

        elif query_type == "blast_radius":
            from query.blast_radius import BlastRadiusAnalyzer

            raw_names = args.get("names")
            name_field = str(args.get("name", "") or "").strip()
            names_list: list[str] = []
            if isinstance(raw_names, list):
                names_list = [str(x).strip() for x in raw_names if str(x).strip()]
            elif raw_names not in (None, ""):
                names_list = [str(raw_names).strip()]
            if not names_list and name_field:
                sep = "," if "," in name_field else None
                if sep:
                    names_list = [p.strip() for p in name_field.split(",") if p.strip()]
                else:
                    names_list = [p.strip() for p in name_field.replace(",", " ").split() if p.strip()]
            if not names_list:
                return _mcp_error(
                    "invalid_params",
                    "names or comma-separated name is required for blast_radius",
                )
            repo = args.get("repository")
            repository = str(repo).strip() if repo not in (None, "") else None
            try:
                depth_val = int(args.get("depth", 3))
            except (TypeError, ValueError):
                depth_val = 3
            depth_val = max(1, min(depth_val, 5))
            if self._store is None:
                return _mcp_error("internal_error", "Graph store unavailable")
            analyzer = BlastRadiusAnalyzer(self._store)
            result = await analyzer.analyze(names_list, max_depth=depth_val, repository=repository)
            return {"type": "blast_radius", **result}

        return _mcp_error("invalid_params", f"Unknown query_type: {query_type}")

    async def _collect_business_search_results(
        self,
        query: str,
        search_type: str,
        k: int,
        include_code: bool,
    ) -> dict[str, Any]:
        results: dict[str, Any] = {}
        if search_type in ("flow", "all"):
            flow_result = await self._hybrid.semantic.search_business_flows(query, k)
            results["flows"] = flow_result.matches
        if search_type in ("concept", "all"):
            concept_result = await self._hybrid.semantic.search_business_concepts(query, k)
            results["concepts"] = concept_result.matches

        if include_code:
            for flow in results.get("flows", []):
                flow_name = flow.get("name", "")
                if flow_name:
                    code_result = await self._graph.find_business_flow(flow_name, k=5)
                    flow["code_locations"] = code_result.data

        return results

    # handle_rag_business_search removed in P3 (Track C).

    async def handle_analyze_impact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.analysis_service import AnalysisService

        changed = arguments.get("changed_functions", [])
        if not isinstance(changed, list):
            return _mcp_error("invalid_params", "changed_functions must be a list of strings")
        max_depth = arguments.get("max_depth", 5)
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        analysis = AnalysisService(self._store)
        report = await analysis.analyze_impact(
            [str(x) for x in changed],
            max_depth=max_depth,
        )
        return report.to_dict()

    async def handle_list_endpoints(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        from query.endpoint_queries import query_all_endpoints

        repository = arguments.get("repository", "")
        return await query_all_endpoints(self._store, repository)

    async def handle_check_consistency(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        from config import get_settings
        from services.git_manager import resolve_repo_clone_root
        from query.analysis_service import AnalysisService

        repository = arguments.get("repository", "")
        if not repository:
            return _mcp_error("invalid_params", "repository parameter is required")
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")

        settings = get_settings()

        resolved = resolve_repo_clone_root(repository, settings.git, self._repo_registry)
        if resolved is None:
            return _mcp_error("not_found", f"Repository '{repository}' not found on disk")
        base_path = Path(settings.git.clone_base_path).resolve()
        if not resolved.is_relative_to(base_path):
            return _mcp_error("invalid_params", f"Repository path escapes clone base: {repository}")

        analysis = AnalysisService(self._store)
        report = await analysis.verify_consistency(str(resolved), repository=repository)
        return {"repository": repository, **report.to_dict()}

    async def handle_search_architecture(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from store.graph_queries import GraphQueryRepository, validate_architecture_class_search

        mode_raw = arguments.get("mode", "layers")
        arch_mode = str(mode_raw).strip().lower() if mode_raw is not None else "layers"
        if arch_mode == "endpoints":
            repo_ep = arguments.get("repository", "")
            if repo_ep is not None and not isinstance(repo_ep, str):
                repo_ep = str(repo_ep)
            return await self.handle_list_endpoints({"repository": repo_ep or ""})
        if arch_mode != "layers":
            return _mcp_error("invalid_params", "mode must be 'layers' or 'endpoints'")

        layer = (arguments.get("layer") or "").strip()
        if not layer:
            return _mcp_error("invalid_params", "layer is required when mode is layers")
        _allowed = {
            "presentation",
            "business",
            "data_access",
            "rpc",
            "messaging",
            "infrastructure",
            "model",
            "unknown",
        }
        if layer not in _allowed:
            return _mcp_error(
                "invalid_params",
                f"Invalid layer; expected one of: {', '.join(sorted(_allowed))}",
            )
        repository = arguments.get("repository")
        if repository is not None:
            repository = str(repository).strip() or None
        raw_limit = arguments.get("limit", 50)
        raw_offset = arguments.get("offset", 0)
        try:
            limit = int(raw_limit) if raw_limit is not None else 50
            offset = int(raw_offset) if raw_offset is not None else 0
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "limit and offset must be integers")
        limit = max(1, min(limit, 500))
        if offset < 0:
            return _mcp_error("invalid_params", "offset must be >= 0")
        raw_search = arguments.get("search")
        if raw_search is not None and not isinstance(raw_search, str):
            raw_search = str(raw_search)
        try:
            search_param = validate_architecture_class_search(raw_search)
        except ValueError as exc:
            return _mcp_error("invalid_params", str(exc))
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        try:
            queries = GraphQueryRepository(self._store)
            total_count = await queries.count_classes_by_architecture_layer(
                layer, repository, search=search_param
            )
            classes = await queries.search_classes_by_architecture_layer(
                layer, repository, limit, search=search_param, offset=offset
            )
            return {
                "layer": layer,
                "repository": repository,
                "limit": limit,
                "offset": offset,
                "search": search_param,
                "classes": classes,
                "total_count": total_count,
            }
        except Exception as exc:
            log.error("mcp_search_architecture_failed", error=str(exc))
            return _mcp_error("query_failed", str(exc))

    async def handle_code_quality(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.agent_workflow import AgentWorkflowService

        uid = arguments.get("entity_uid", "")
        if not uid:
            return _mcp_error("invalid_params", "entity_uid is required")
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        et_raw = arguments.get("entity_type")
        if et_raw is None or et_raw == "":
            et = ""
        else:
            et = str(et_raw).strip().lower()
        if et and et not in ("function", "class"):
            return _mcp_error("invalid_params", "entity_type must be 'function' or 'class' when provided")
        try:
            workflow = AgentWorkflowService(self._store)
            return await workflow.compute_quality_score(str(uid), et)
        except Exception as exc:
            log.error("mcp_code_quality_failed", error=str(exc))
            return _mcp_error("query_failed", str(exc))

    async def handle_review_pr(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.agent_workflow import AgentWorkflowService

        diff_text = arguments.get("diff_text") or ""
        branch = (arguments.get("branch") or "").strip()
        repo_path = (arguments.get("repo_path") or "").strip()
        base_branch = arguments.get("base_branch")
        repo_url = (arguments.get("repo_url") or "").strip()
        if repo_url and not looks_like_git_url(repo_url):
            return _mcp_error("invalid_params", "repo_url does not look like a valid git remote URL")

        has_diff = bool(str(diff_text).strip())
        has_branch_path = bool(branch) and bool(repo_path)
        if not has_diff and not has_branch_path:
            return _mcp_error(
                "invalid_params",
                "Provide either diff_text, or both branch and repo_path "
                "(local git repo path on the KB server)",
            )
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")

        workflow = AgentWorkflowService(self._store)
        try:
            ctx = await workflow.build_review_context(
                diff_text=diff_text if has_diff else None,
                repository=arguments.get("repository"),
                max_depth=arguments.get("max_depth", 3),
                repo_path=repo_path or None,
                branch=branch or None,
                base_branch=base_branch,
            )
        except (ValueError, RuntimeError) as exc:
            return _mcp_error("invalid_params", str(exc))
        return ctx.to_dict()

    async def handle_documents(self, args: dict[str, Any]) -> dict[str, Any]:
        uid_raw = args.get("uid")
        uid = str(uid_raw).strip() if uid_raw not in (None, "") else ""
        if uid:
            return await self.handle_get_document({"doc_uid": uid})
        return await self.handle_list_documents({"repository": args.get("repository")})

    async def handle_analyze_code(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode_raw = arguments.get("mode", "quality")
        mode = str(mode_raw).strip().lower() if mode_raw is not None else "quality"
        if mode == "consistency":
            return await self.handle_check_consistency(arguments)
        if mode == "quality":
            return await self.handle_code_quality(arguments)
        return _mcp_error("invalid_params", "mode must be 'quality' or 'consistency'")

    async def handle_analyze_changes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        mode_raw = arguments.get("mode")
        if mode_raw is None or str(mode_raw).strip() == "":
            return _mcp_error("invalid_params", "mode is required")
        mode = str(mode_raw).strip().lower()
        if mode == "pr_review":
            return await self.handle_review_pr(arguments)
        if mode == "impact":
            return await self.handle_analyze_impact(arguments)
        if mode == "impact_scope":
            return await self._wiki.handle_find_impact_scope(arguments)
        if mode == "wiki_pr_impact":
            return await self._wiki.handle_analyze_pr_impact(arguments)
        return _mcp_error(
            "invalid_params",
            "mode must be one of: pr_review, impact, impact_scope, wiki_pr_impact",
        )

    async def handle_get_insights(self, arguments: dict[str, Any]) -> dict[str, Any]:
        raw = arguments.get("type", "dashboard")
        t = str(raw).strip().lower() if raw is not None else "dashboard"
        if t not in ("dashboard", "graph", "all"):
            return _mcp_error("invalid_params", "type must be 'dashboard', 'graph', or 'all'")
        if t == "dashboard":
            return await self.handle_dashboard_stats({})
        if t == "graph":
            return await self.handle_graph_insights(arguments)
        repo = str(arguments.get("repository") or "").strip()
        if not repo:
            return _mcp_error("invalid_params", "repository is required when type is 'all'")
        dash = await self.handle_dashboard_stats({})
        graph = await self.handle_graph_insights(arguments)
        return {"type": "all", "dashboard": dash, "graph": graph}

    async def handle_get_complete_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.context_assembler import ContextAssembler

        entity_name = str(arguments.get("entity_name") or "").strip()
        if not entity_name:
            return _mcp_error("invalid_params", "entity_name parameter is required")
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        repo = arguments.get("repository")
        repository = str(repo).strip() if repo not in (None, "") else None
        raw_max = arguments.get("max_tokens", 8000)
        try:
            max_tokens = int(raw_max) if raw_max is not None else 8000
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "max_tokens must be an integer")
        max_tokens = max(256, min(max_tokens, 100_000))

        assembler = ContextAssembler(self._store, self._hybrid, self._graph)
        return await assembler.assemble(entity_name, repository=repository, max_tokens=max_tokens)

    async def handle_dashboard_stats(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        stats = await self._graph.get_p2_stats()
        return {"status": "success", "stats": stats}

    async def handle_graph_insights(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._store or self._store.graph is None:
            return _mcp_error("service_unavailable", "Graph store not available")
        repository = str(arguments.get("repository", "") or "").strip()
        if not repository:
            return _mcp_error("invalid_params", "repository parameter is required")
        from query.graph_insights import GraphInsightsService

        svc = GraphInsightsService(self._store)
        report = await svc.analyze(repository)
        return {"status": "success", **report.to_dict()}

    async def handle_index_freshness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        repository = str(arguments.get("repository") or "").strip()
        if not repository:
            return _mcp_error("invalid_params", "repository parameter is required")
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        return await self._store.get_repository_index_freshness(repository)

    async def handle_task_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = str(arguments.get("task_id") or "").strip()
        if not task_id:
            return _mcp_error("invalid_params", "task_id is required")
        if self._task_status_fn is None:
            return _mcp_error(
                "service_unavailable",
                "Index task status is not available in this deployment.",
            )
        payload = self._task_status_fn(task_id)
        if payload is None:
            return _mcp_error("not_found", "Task not found")
        return payload

    async def handle_deep_search(self, args: dict[str, Any]) -> dict[str, Any]:
        if self._deep_search_engine is None:
            return _mcp_error(
                "service_unavailable",
                "Deep search requires LLM to be enabled and initialized.",
            )
        query = str(args.get("query") or "").strip()
        if not query:
            return _mcp_error("invalid_params", "query parameter is required")
        raw_max = args.get("max_iterations", 3)
        try:
            max_iterations = int(raw_max) if raw_max is not None else 3
        except (TypeError, ValueError):
            return _mcp_error("invalid_params", "max_iterations must be an integer")
        max_iterations = max(1, min(max_iterations, 5))
        include_code = args.get("include_code", True)
        if not isinstance(include_code, bool):
            include_code = bool(include_code)
        try:
            result = await self._deep_search_engine.search(
                query,
                max_iterations=max_iterations,
                include_code=include_code,
            )
        except Exception as exc:
            log.error("mcp_deep_search_failed", error=str(exc))
            return _mcp_error("deep_search_failed", str(exc))
        conclusion = result.get("analysis", "")
        sources: list[dict[str, Any]] = []
        for loc in result.get("code_locations", []) or []:
            if isinstance(loc, dict):
                sources.append(loc)
        return {
            "conclusion": conclusion,
            "analysis": result.get("analysis", ""),
            "sources": sources,
            "business_flows": result.get("business_flows", []),
            "code_locations": result.get("code_locations", []),
            "search_trace": result.get("search_trace", []),
        }

    async def handle_list_documents(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        from store.graph_queries import GraphQueryRepository

        repository = args.get("repository")
        if repository is not None:
            repository = str(repository).strip() or None
        queries = GraphQueryRepository(self._store)
        try:
            result = await queries.list_documents(repository)
        except Exception as exc:
            log.error("mcp_list_documents_failed", error=str(exc))
            return _mcp_error("query_failed", str(exc))
        return _format_list_documents_mcp(result.data)

    async def handle_get_document(self, args: dict[str, Any]) -> dict[str, Any]:
        if not self._store:
            return _mcp_error("service_unavailable", "Graph store not available")
        from store.graph_queries import GraphQueryRepository

        doc_uid = str(args.get("doc_uid") or "").strip()
        if not doc_uid:
            return _mcp_error("invalid_params", "doc_uid parameter is required")
        queries = GraphQueryRepository(self._store)
        try:
            result = await queries.get_document(doc_uid)
        except Exception as exc:
            log.error("mcp_get_document_failed", error=str(exc))
            return _mcp_error("query_failed", str(exc))
        if not result.data:
            return _mcp_error("not_found", "Document not found")
        return _format_get_document_mcp(result.data)

    async def handle_get_file_content(self, args: dict[str, Any]) -> dict[str, Any]:
        repository = str(args.get("repository") or "").strip()
        file_path = str(args.get("file_path") or "").strip()
        if not repository or not file_path:
            return _mcp_error("invalid_params", "repository and file_path are required")

        if file_path.startswith("/") or ".." in Path(file_path).parts:
            return _mcp_error("invalid_params", "file_path must be relative and cannot contain '..'")

        repo_base = _resolve_repo_base_path(repository, self._repo_registry)
        if repo_base is None:
            return _mcp_error("not_found", f"Repository '{repository}' not found on disk")

        full_path = (repo_base / file_path).resolve()
        if not full_path.is_relative_to(repo_base.resolve()):
            return _mcp_error("invalid_params", "file_path resolves outside repository")

        if not full_path.is_file():
            return _mcp_error("not_found", f"File not found: {file_path}")

        file_size = full_path.stat().st_size
        start_line_raw = args.get("start_line")
        end_line_raw = args.get("end_line")
        has_range = start_line_raw is not None or end_line_raw is not None

        if has_range:
            try:
                sl = int(start_line_raw) if start_line_raw is not None else 1
                el = int(end_line_raw) if end_line_raw is not None else None
            except (TypeError, ValueError):
                return _mcp_error("invalid_params", "start_line and end_line must be positive integers")
            if sl < 1:
                return _mcp_error("invalid_params", "start_line must be >= 1")
            if el is not None and el < 1:
                return _mcp_error("invalid_params", "end_line must be >= 1")
            if el is not None and sl > el:
                return _mcp_error("invalid_params", "start_line cannot be greater than end_line")

            selected: list[str] = []
            total_lines = 0
            try:
                with open(full_path, encoding="utf-8", errors="replace") as fh:
                    for i, line in enumerate(fh, 1):
                        total_lines = i
                        if el is not None and i > el:
                            for _ in fh:
                                total_lines += 1
                            break
                        if i >= sl:
                            selected.append(line.rstrip("\n"))
            except OSError as exc:
                return _mcp_error("read_error", str(exc))

            actual_el = el if el is not None else total_lines
            actual_el = min(actual_el, total_lines)
            content = "\n".join(selected) + ("\n" if selected else "")
            return {
                "repository": repository,
                "file_path": file_path,
                "content": content,
                "start_line": sl,
                "end_line": actual_el,
                "total_lines": total_lines,
                "truncated": False,
            }

        truncated = False
        try:
            raw = full_path.read_bytes()
        except OSError as exc:
            return _mcp_error("read_error", str(exc))

        if len(raw) > _MAX_FILE_READ_BYTES:
            raw = raw[:_MAX_FILE_READ_BYTES]
            truncated = True

        probe = raw[:8192]
        if b"\x00" in probe:
            return _mcp_error("read_error", "File appears to be binary")

        text = raw.decode("utf-8", errors="replace")

        all_lines = text.split("\n")
        if text.endswith("\n") and all_lines and all_lines[-1] == "":
            all_lines = all_lines[:-1]
        total_lines = len(all_lines) if all_lines != [""] else 0

        return {
            "repository": repository,
            "file_path": file_path,
            "content": text,
            "total_lines": total_lines,
            "truncated": truncated,
        }

    async def handle_get_code_snippet(self, args: dict[str, Any]) -> dict[str, Any]:
        node_uid = str(args.get("node_uid") or "").strip()
        if not node_uid:
            return _mcp_error("invalid_params", "node_uid is required")
        if not self._traversal:
            return _mcp_error("service_unavailable", "Graph store not available")

        result = await self._traversal.get_code_entity_for_snippet(node_uid)
        if not result.data:
            return _mcp_error("not_found", f"No code entity with uid '{node_uid}'")
        row = result.data[0]
        return {
            "uid": row.get("uid", ""),
            "name": row.get("name", ""),
            "file": row.get("file", ""),
            "repository": row.get("repository", ""),
            "start_line": row.get("start_line"),
            "end_line": row.get("end_line"),
            "type": row.get("type", ""),
            "code_snippet": row.get("code_snippet", ""),
            "signature": row.get("signature", ""),
            "docstring": row.get("docstring", ""),
            "language": row.get("language", ""),
            "fqn": row.get("fqn", ""),
        }

    async def handle_rag_index(
        self, args: dict[str, Any], progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        git_url = str(args.get("git_url") or "").strip()
        directory = str(args.get("directory") or "").strip()
        mode_raw = args.get("mode", "full")
        mode = str(mode_raw) if mode_raw is not None else "full"
        repository = args.get("repository")

        if git_url:
            if not looks_like_git_url(git_url):
                return _mcp_error("invalid_params", "git_url must be an https, ssh, git@, or .git remote URL")

            from pathlib import Path as _Path

            from config import get_settings
            from services.git_manager import GitManager

            branch_arg = args.get("branch")
            branch = str(branch_arg).strip() if branch_arg not in (None, "") else None

            settings = get_settings()
            mgr = GitManager(settings.git)
            clone_result = await mgr.ensure_repo(git_url, branch=branch)
            if clone_result["status"] in ("clone_failed", "pull_failed"):
                detail = clone_result.get("detail", "") or "git operation failed"
                return _mcp_error("git_operation_failed", detail)

            directory = str(clone_result.get("directory") or "").strip()
            if not directory:
                return _mcp_error("git_operation_failed", "No directory resolved after clone/pull")

            base_path = _Path(settings.git.clone_base_path).resolve()
            resolved_dir = _Path(directory).resolve()
            if not resolved_dir.is_relative_to(base_path):
                return _mcp_error("invalid_params", "Clone directory escapes allowed base path")

            if repository is None or (isinstance(repository, str) and not repository.strip()):
                repository = clone_result.get("repository")

            if clone_result["status"] == "cloned" and mode == "incremental":
                mode = "full"

        elif not directory:
            return _mcp_error(
                "invalid_params",
                "Provide directory (local path) or git_url for remote indexing.",
            )

        effective_mode = mode
        if effective_mode == "incremental" and repository and self._store:
            from store.graph_queries import GraphQueryRepository

            queries = GraphQueryRepository(self._store)
            repo_key = str(repository).strip()
            sample = await queries.get_repository_sample_file(repo_key)
            if sample is None:
                effective_mode = "full"

        if effective_mode == "incremental":
            base_ref = args.get("base_ref", "HEAD~1")
            head_ref = args.get("head_ref", "HEAD")
            stats = await self._indexer.index_incremental(
                directory,
                base_ref,
                head_ref,
                progress_callback=progress_callback,
                repository=repository,
            )
            doc_stats = {}
        else:
            stats = await self._indexer.index_full(
                directory, progress_callback=progress_callback, repository=repository,
            )
            doc_stats = await self._index_docs_full(
                directory, progress_callback=progress_callback, repository=repository,
            )

        stats.update(doc_stats)
        return {"mode": effective_mode, "directory": directory, "stats": stats}

    async def _index_docs_full(
        self,
        directory: str,
        progress_callback: Callable[..., None] | None = None,
        *,
        repository: str | None = None,
    ) -> dict[str, int]:
        """Index all documents (.md, .rst, .txt) — one file at a time."""
        if not self._doc_indexer or not self._store:
            return {}

        from pathlib import Path

        from indexer.incremental_indexer import _stamp_repository_metadata, _try_git_head_sha

        base = Path(directory)
        commit_sha = _try_git_head_sha(directory)
        total_nodes = 0
        total_edges = 0
        total_embeds = 0

        exclude_dirs = set(self._doc_indexer._exclude_dirs)
        doc_paths: list[Path] = []
        for fpath in DocumentIndexer.iter_supported_paths(base):
            if any(part in exclude_dirs for part in fpath.parts):
                continue
            doc_paths.append(fpath)

        if progress_callback:
            progress_callback(phase="indexing_docs", total_files=len(doc_paths))

        processed = 0
        for fpath in doc_paths:
            try:
                rel = str(fpath.relative_to(base))
                doc = self._doc_indexer.parse_document(str(fpath), store_path=rel)
                nodes, edges = self._doc_indexer.build_graph(doc)
                _stamp_repository_metadata(nodes, repository, commit_sha=commit_sha)
                await self._store.batch_upsert(nodes, edges)
                total_nodes += len(nodes)
                total_edges += len(edges)

                if self._embedding:
                    embeddable = [n for n in nodes if n.properties.get("content")]
                    if embeddable:
                        items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                        embeddings = await self._embedding.generate_for_docs(items)
                        for node, emb in zip(embeddable, embeddings):
                            await self._store.set_node_embedding(node.uid, node.label, emb)
                        total_embeds += len(embeddings)
                processed += 1
                if progress_callback:
                    progress_callback(
                        current_file=str(fpath),
                        processed_files=processed,
                        doc_nodes=total_nodes,
                        doc_edges=total_edges,
                        doc_embeddings=total_embeds,
                    )
            except Exception as exc:
                log.warning("doc_index_error", file=str(fpath), error=str(exc))

        return {
            "doc_nodes": total_nodes,
            "doc_edges": total_edges,
            "doc_embeddings": total_embeds,
        }

    async def _index_docs_incremental(
        self,
        directory: str,
        base_ref: str,
        head_ref: str,
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Incrementally index changed document files based on git diff."""
        if not self._doc_indexer or not self._store:
            return {}

        import subprocess
        from pathlib import Path

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "diff", "--name-status", base_ref, head_ref],
                    capture_output=True, text=True, cwd=directory, timeout=30,
                ),
            )
            if result.returncode != 0:
                return {}

            doc_exts = DocumentIndexer.SUPPORTED_EXTENSIONS
            changed: list[tuple[str, str]] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, fpath = parts
                    if _config_file_extension(Path(fpath)) in doc_exts:
                        changed.append((fpath, status[0]))

            if not changed:
                return {"doc_nodes": 0, "doc_edges": 0, "doc_embeddings": 0}

            if progress_callback:
                progress_callback(phase="indexing_docs", total_files=len(changed))

            total_nodes = 0
            total_edges = 0
            total_embeds = 0

            processed = 0
            for fpath, status in changed:
                await self._store.delete_by_file(fpath)
                if status != "D":
                    full_path = str(Path(directory) / fpath)
                    if Path(full_path).exists():
                        doc = self._doc_indexer.parse_document(full_path, store_path=fpath)
                        nodes, edges = self._doc_indexer.build_graph(doc)
                        await self._store.batch_upsert(nodes, edges)
                        total_nodes += len(nodes)
                        total_edges += len(edges)

                        if self._embedding:
                            embeddable = [n for n in nodes if n.properties.get("content")]
                            if embeddable:
                                items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                                embeddings = await self._embedding.generate_for_docs(items)
                                for node, emb in zip(embeddable, embeddings):
                                    await self._store.set_node_embedding(node.uid, node.label, emb)
                                total_embeds += len(embeddings)

                processed += 1
                if progress_callback:
                    progress_callback(
                        current_file=fpath,
                        processed_files=processed,
                        doc_nodes=total_nodes,
                        doc_edges=total_edges,
                        doc_embeddings=total_embeds,
                    )

            return {
                "doc_nodes": total_nodes,
                "doc_edges": total_edges,
                "doc_embeddings": total_embeds,
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}
