"""MCP Server interface for the RAG knowledge base.

Exposes the knowledge base as MCP tools that can be injected into
Cursor Agent sessions, enabling the agent to query the code knowledge graph.

Tools exposed:
  - rag_query: Natural language search over code and docs (semantic + graph expansion)
  - rag_graph: Execute structured graph queries (call chains, inheritance, etc.)
  - rag_index: Trigger indexing for a repository/directory
  - analyze_impact: Blast-radius analysis for changed functions
  - list_endpoints: HTTP, RPC, and Kafka endpoints from the graph
  - check_consistency: Compare graph file paths to on-disk repository files
  - search_architecture: List classes (with methods) filtered by architecture layer
  - code_quality: Heuristic 0–100 quality score for a Function or Class node
  - dashboard_stats: P2 enrichment aggregates (architecture layers, Kafka events, RPC, cross-repo)
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator
from indexer.incremental_indexer import IncrementalIndexer
from log import get_logger
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


def _looks_like_git_url(value: str) -> bool:
    """Heuristic: detect if a string is a git URL rather than a local path.

    NOTE: duplicated in main.py — keep in sync or move to a shared util module.
    """
    if value.startswith(("http://", "https://", "git@", "ssh://")):
        return True
    if value.endswith(".git"):
        return True
    return False


MCP_TOOLS_MANIFEST = [
    {
        "name": "rag_query",
        "description": (
            "Search the code knowledge base using natural language. "
            "Finds semantically similar functions, classes, and documentation, "
            "then expands results through call graphs and inheritance trees."
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
                    ],
                    "description": "Type of graph query to execute.",
                },
                "name": {
                    "type": "string",
                    "description": "Entity name for the query (function, class, or module name).",
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
            },
            "required": ["query_type"],
        },
    },
    {
        "name": "rag_index",
        "description": (
            "Trigger indexing of a repository or directory. "
            "Supports full reindex or incremental updates based on git diff."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "directory": {
                    "type": "string",
                    "description": "Directory path to index.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["full", "incremental"],
                    "description": "Indexing mode: full reindex or incremental (git diff).",
                    "default": "full",
                },
                "base_ref": {
                    "type": "string",
                    "description": "Base git ref for incremental mode.",
                    "default": "HEAD~1",
                },
                "head_ref": {
                    "type": "string",
                    "description": "Head git ref for incremental mode.",
                    "default": "HEAD",
                },
            },
            "required": ["directory"],
        },
    },
    {
        "name": "rag_business_search",
        "description": (
            "搜索业务流程和业务概念，支持自然语言查询。可以搜索业务流程（如'用户下单'）、"
            "业务概念（如'私信'），并返回关联的代码位置。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "业务语义查询（自然语言）",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["flow", "concept", "all"],
                    "default": "all",
                    "description": "搜索类型：flow=业务流程, concept=业务概念, all=全部",
                },
                "k": {
                    "type": "integer",
                    "default": 5,
                    "description": "返回结果数量",
                },
                "include_code": {
                    "type": "boolean",
                    "default": True,
                    "description": "是否包含关联的代码位置",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "analyze_impact",
        "description": (
            "Analyze the blast radius of code changes. Given function names that were modified, "
            "returns all directly and transitively affected callers, affected architectural layers, "
            "and entry points in the blast radius."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "changed_functions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Names of changed functions",
                },
                "max_depth": {
                    "type": "integer",
                    "default": 5,
                    "description": "Maximum call chain depth to trace",
                },
            },
            "required": ["changed_functions"],
        },
    },
    {
        "name": "list_endpoints",
        "description": (
            "List all discovered API endpoints (HTTP, RPC, Kafka) in the indexed codebase."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "check_consistency",
        "description": (
            "Verify index consistency by comparing the graph against actual repository files. "
            "Detects ghost nodes and missing files."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repository": {
                    "type": "string",
                    "description": "Repository name or path",
                },
            },
            "required": ["repository"],
        },
    },
    {
        "name": "search_architecture",
        "description": (
            "Search indexed classes by architecture layer (presentation, business, data_access, "
            "rpc, messaging, infrastructure, model, unknown). Returns each class with its methods."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
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
                    "description": "Architecture layer to filter Class nodes",
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository name to scope results",
                },
                "limit": {
                    "type": "integer",
                    "default": 50,
                    "description": "Max classes to return (capped at 500)",
                },
                "offset": {
                    "type": "integer",
                    "default": 0,
                    "description": "Number of classes to skip (pagination)",
                },
                "search": {
                    "type": "string",
                    "description": "Optional substring match on class name (case-insensitive)",
                },
            },
            "required": ["layer"],
        },
    },
    {
        "name": "code_quality",
        "description": (
            "Compute a 0–100 heuristic quality score for a code entity (Function or Class) "
            "using docstrings, typing, length, tests, naming, semantic roles, and complexity."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_uid": {
                    "type": "string",
                    "description": "Graph node uid of the Function or Class",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["function", "class"],
                    "description": "Optional: restrict match to Function or Class",
                },
            },
            "required": ["entity_uid"],
        },
    },
    {
        "name": "review_pr",
        "description": (
            "Analyze a PR diff and build comprehensive review context. Returns changed entities, "
            "impact analysis, affected API endpoints, cross-repository impacts, and review suggestions. "
            "Use this when starting a code review to understand the blast radius of changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "diff_text": {
                    "type": "string",
                    "description": (
                        "Unified diff text from git diff. Optional if branch and repo_path are set."
                    ),
                },
                "branch": {
                    "type": "string",
                    "description": (
                        "Branch to compare against base_branch (requires repo_path on the KB host)."
                    ),
                },
                "base_branch": {
                    "type": "string",
                    "description": 'Base branch for git diff (default "master").',
                    "default": "master",
                },
                "repo_path": {
                    "type": "string",
                    "description": (
                        "Local path to a git repository on the KB server; used with branch to run git diff."
                    ),
                },
                "repo_url": {
                    "type": "string",
                    "description": (
                        "Remote git URL (reserved for future server-side fetch; validated for format when set)."
                    ),
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository name to scope the analysis",
                },
                "max_depth": {
                    "type": "integer",
                    "default": 3,
                    "description": "Maximum call chain depth for impact analysis",
                },
            },
        },
    },
    {
        "name": "build_context",
        "description": (
            "Build an optimal context package for a code entity (function or class). "
            "Returns the entity's code, callers, callees, parent class, sibling methods, "
            "cross-repository dependencies, entity tables, DI dependencies, and interfaces. "
            "Use this to deeply understand a function or class before modifying it."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "entity_name": {
                    "type": "string",
                    "description": "Name of the function or class to get context for",
                },
                "entity_type": {
                    "type": "string",
                    "enum": ["function", "class"],
                    "default": "function",
                    "description": "Type of entity",
                },
                "repository": {
                    "type": "string",
                    "description": "Optional repository name to scope the search",
                },
            },
            "required": ["entity_name"],
        },
    },
    {
        "name": "dashboard_stats",
        "description": (
            "Return P2 enrichment statistics for the knowledge graph dashboard: "
            "architecture layer counts, Kafka topic and event edge counts, RPC contract totals, "
            "and cross-repository / DI / entity-table edge counts. "
            "quality_overview is omitted (null) because bulk scoring is expensive."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


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
    ) -> None:
        self._hybrid = hybrid_svc
        self._graph = graph_svc
        self._indexer = indexer
        self._doc_indexer = doc_indexer
        self._store = store
        self._embedding = embedding_gen

    def get_tools_manifest(self) -> list[dict[str, Any]]:
        return MCP_TOOLS_MANIFEST

    async def handle_tool_call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Dispatch MCP tool calls to the appropriate handler."""
        handlers = {
            "rag_query": self.handle_rag_query,
            "rag_graph": self.handle_rag_graph,
            "rag_index": self.handle_rag_index,
            "rag_business_search": self.handle_rag_business_search,
            "analyze_impact": self.handle_analyze_impact,
            "list_endpoints": self.handle_list_endpoints,
            "check_consistency": self.handle_check_consistency,
            "search_architecture": self.handle_search_architecture,
            "code_quality": self.handle_code_quality,
            "review_pr": self.handle_review_pr,
            "build_context": self.handle_build_context,
            "dashboard_stats": self.handle_dashboard_stats,
        }

        handler = handlers.get(tool_name)
        if not handler:
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            return await handler(arguments)
        except Exception as exc:
            log.error("mcp_tool_error", tool=tool_name, error=str(exc))
            return {"error": str(exc)}

    async def handle_rag_query(self, args: dict[str, Any]) -> dict[str, Any]:
        query_text = args.get("query", "")
        k = args.get("k", 5)
        expand_depth = args.get("expand_depth", 2)

        result = await self._hybrid.search_with_context(query_text, k=k, expand_depth=expand_depth)
        return {
            "query": result.query_text,
            "semantic_matches": result.semantic_matches,
            "graph_context": result.graph_context,
            "total_results": result.total,
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
                return {"error": "cypher parameter is required for raw_cypher queries"}
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

        return {"error": f"Unknown query_type: {query_type}"}

    async def handle_rag_business_search(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = arguments.get("query", "")
        if not query:
            return {"error": "query parameter is required"}
        search_type = arguments.get("search_type", "all")
        k = arguments.get("k", 5)
        include_code = arguments.get("include_code", True)

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

        return {"status": "success", "results": results}

    async def handle_analyze_impact(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.analysis_service import AnalysisService

        changed = arguments.get("changed_functions", [])
        if not isinstance(changed, list):
            return {"error": "changed_functions must be a list of strings"}
        max_depth = arguments.get("max_depth", 5)
        if not self._store:
            return {"error": "Graph store not available"}
        analysis = AnalysisService(self._store)
        report = await analysis.analyze_impact(
            [str(x) for x in changed],
            max_depth=max_depth,
        )
        return report.to_dict()

    async def handle_list_endpoints(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if not self._store:
            return {"error": "Graph store not available"}
        from query.endpoint_queries import query_all_endpoints

        repository = arguments.get("repository", "")
        return await query_all_endpoints(self._store, repository)

    async def handle_check_consistency(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from pathlib import Path

        from config import get_settings
        from git_manager import GitManager
        from query.analysis_service import AnalysisService

        repository = arguments.get("repository", "")
        if not repository:
            return {"error": "repository parameter is required"}
        if not self._store:
            return {"error": "Graph store not available"}

        settings = get_settings()
        git_mgr = GitManager(settings.git)
        repo_path = git_mgr._repo_local_path(repository)
        base_path = Path(settings.git.clone_base_path).resolve()
        resolved = repo_path.resolve()
        if not resolved.is_relative_to(base_path):
            return {"error": f"Repository path escapes clone base: {repository}"}

        analysis = AnalysisService(self._store)
        report = await analysis.verify_consistency(str(resolved), repository=repository)
        return {"repository": repository, **report.to_dict()}

    async def handle_search_architecture(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from store.graph_queries import GraphQueryRepository, validate_architecture_class_search

        layer = (arguments.get("layer") or "").strip()
        if not layer:
            return {"error": "layer is required"}
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
            return {"error": f"Invalid layer; expected one of: {', '.join(sorted(_allowed))}"}
        repository = arguments.get("repository")
        if repository is not None:
            repository = str(repository).strip() or None
        raw_limit = arguments.get("limit", 50)
        raw_offset = arguments.get("offset", 0)
        try:
            limit = int(raw_limit) if raw_limit is not None else 50
            offset = int(raw_offset) if raw_offset is not None else 0
        except (TypeError, ValueError):
            return {"error": "limit and offset must be integers"}
        limit = max(1, min(limit, 500))
        if offset < 0:
            return {"error": "offset must be >= 0"}
        raw_search = arguments.get("search")
        if raw_search is not None and not isinstance(raw_search, str):
            raw_search = str(raw_search)
        try:
            search_param = validate_architecture_class_search(raw_search)
        except ValueError as exc:
            return {"error": str(exc)}
        if not self._store:
            return {"error": "Graph store not available"}
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
            return {"error": str(exc)}

    async def handle_code_quality(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.agent_workflow import AgentWorkflowService

        uid = arguments.get("entity_uid", "")
        if not uid:
            return {"error": "entity_uid is required"}
        if not self._store:
            return {"error": "Graph store not available"}
        et_raw = arguments.get("entity_type")
        if et_raw is None or et_raw == "":
            et = ""
        else:
            et = str(et_raw).strip().lower()
        if et and et not in ("function", "class"):
            return {"error": "entity_type must be 'function' or 'class' when provided"}
        try:
            workflow = AgentWorkflowService(self._store)
            return await workflow.compute_quality_score(str(uid), et)
        except Exception as exc:
            log.error("mcp_code_quality_failed", error=str(exc))
            return {"error": str(exc)}

    async def handle_review_pr(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.agent_workflow import AgentWorkflowService

        diff_text = arguments.get("diff_text") or ""
        branch = (arguments.get("branch") or "").strip()
        repo_path = (arguments.get("repo_path") or "").strip()
        base_branch = arguments.get("base_branch")
        repo_url = (arguments.get("repo_url") or "").strip()
        if repo_url and not _looks_like_git_url(repo_url):
            return {"error": "repo_url does not look like a valid git remote URL"}

        has_diff = bool(str(diff_text).strip())
        has_branch_path = bool(branch) and bool(repo_path)
        if not has_diff and not has_branch_path:
            return {
                "error": (
                    "Provide either diff_text, or both branch and repo_path "
                    "(local git repo path on the KB server)",
                ),
            }
        if not self._store:
            return {"error": "Graph store not available"}

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
            return {"error": str(exc)}
        return ctx.to_dict()

    async def handle_build_context(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from query.agent_workflow import AgentWorkflowService

        entity_name = arguments.get("entity_name", "")
        if not entity_name:
            return {"error": "entity_name parameter is required"}
        if not self._store:
            return {"error": "Graph store not available"}

        workflow = AgentWorkflowService(self._store)
        ctx = await workflow.build_smart_context(
            entity_name=entity_name,
            entity_type=arguments.get("entity_type", "function"),
            repository=arguments.get("repository"),
        )
        return ctx.to_dict()

    async def handle_dashboard_stats(self, _arguments: dict[str, Any]) -> dict[str, Any]:
        stats = await self._graph.get_p2_stats()
        return {"status": "success", "stats": stats}

    async def handle_rag_index(
        self, args: dict[str, Any], progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        directory = args.get("directory", "")
        mode = args.get("mode", "full")

        if not directory:
            return {"error": "directory parameter is required"}

        if mode == "incremental":
            base_ref = args.get("base_ref", "HEAD~1")
            head_ref = args.get("head_ref", "HEAD")
            stats = await self._indexer.index_incremental(
                directory, base_ref, head_ref, progress_callback=progress_callback,
            )
            doc_stats = {}
        else:
            stats = await self._indexer.index_full(directory, progress_callback=progress_callback)
            doc_stats = await self._index_docs_full(directory, progress_callback=progress_callback)

        stats.update(doc_stats)
        return {"mode": mode, "directory": directory, "stats": stats}

    async def _index_docs_full(
        self, directory: str, progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Index all documents (.md, .rst, .txt) — one file at a time."""
        if not self._doc_indexer or not self._store:
            return {}

        from pathlib import Path

        base = Path(directory)
        total_nodes = 0
        total_edges = 0
        total_embeds = 0

        exclude_dirs = set(self._doc_indexer._exclude_dirs)
        doc_paths: list[Path] = []
        for ext in self._doc_indexer.SUPPORTED_EXTENSIONS:
            for fpath in base.rglob(f"*{ext}"):
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
                await self._store.batch_upsert(nodes, edges)
                total_nodes += len(nodes)
                total_edges += len(edges)

                if self._embedding:
                    embeddable = [n for n in nodes if n.properties.get("content")]
                    if embeddable:
                        items = [
                            {
                                "name": n.properties.get("title", ""),
                                "signature": "",
                                "docstring": "",
                                "code_snippet": n.properties.get("content", ""),
                            }
                            for n in embeddable
                        ]
                        embeddings = await self._embedding.generate_for_code(items)
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
                    if Path(fpath).suffix.lower() in doc_exts:
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
                                items = [
                                    {
                                        "name": n.properties.get("title", ""),
                                        "signature": "",
                                        "docstring": "",
                                        "code_snippet": n.properties.get("content", ""),
                                    }
                                    for n in embeddable
                                ]
                                embeddings = await self._embedding.generate_for_code(items)
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
