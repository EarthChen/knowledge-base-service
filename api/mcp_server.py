"""MCP Server interface for the RAG knowledge base.

Exposes the knowledge base as MCP tools that can be injected into
Cursor Agent sessions, enabling the agent to query the code knowledge graph.

Tools exposed:
  - rag_query: Natural language search over code and docs (semantic + graph expansion)
  - rag_graph: Execute structured graph queries (call chains, inheritance, etc.)
  - rag_index: Trigger indexing for a repository/directory
"""

from __future__ import annotations

import json
from typing import Any

from log import get_logger

from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator
from indexer.incremental_indexer import IncrementalIndexer
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


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
            return {"type": "call_chain", "function": name, "direction": direction, "results": result.data}

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

        return {"error": f"Unknown query_type: {query_type}"}

    async def handle_rag_index(self, args: dict[str, Any]) -> dict[str, Any]:
        directory = args.get("directory", "")
        mode = args.get("mode", "full")

        if not directory:
            return {"error": "directory parameter is required"}

        if mode == "incremental":
            base_ref = args.get("base_ref", "HEAD~1")
            head_ref = args.get("head_ref", "HEAD")
            stats = await self._indexer.index_incremental(directory, base_ref, head_ref)
            doc_stats = await self._index_docs_incremental(directory, base_ref, head_ref)
        else:
            stats = await self._indexer.index_full(directory)
            doc_stats = await self._index_docs_full(directory)

        stats.update(doc_stats)
        return {"mode": mode, "directory": directory, "stats": stats}

    async def _index_docs_full(self, directory: str) -> dict[str, int]:
        """Index all documents (.md, .rst, .txt) — one file at a time."""
        if not self._doc_indexer or not self._store:
            return {}

        from pathlib import Path

        base = Path(directory)
        total_nodes = 0
        total_edges = 0
        total_embeds = 0

        for ext in self._doc_indexer.SUPPORTED_EXTENSIONS:
            for fpath in base.rglob(f"*{ext}"):
                if any(
                    part in {"node_modules", ".git", ".venv", "venv", "__pycache__"}
                    for part in fpath.parts
                ):
                    continue
                try:
                    doc = self._doc_indexer.parse_document(str(fpath))
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
                except Exception as exc:
                    log.warning("doc_index_error", file=str(fpath), error=str(exc))

        return {
            "doc_nodes": total_nodes,
            "doc_edges": total_edges,
            "doc_embeddings": total_embeds,
        }

    async def _index_docs_incremental(
        self, directory: str, base_ref: str, head_ref: str,
    ) -> dict[str, int]:
        """Incrementally index changed document files based on git diff."""
        if not self._doc_indexer or not self._store:
            return {}

        import asyncio
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

            total_nodes = 0
            total_edges = 0
            total_embeds = 0

            for fpath, status in changed:
                await self._store.delete_by_file(fpath)
                if status == "D":
                    continue

                full_path = str(Path(directory) / fpath)
                if not Path(full_path).exists():
                    continue

                doc = self._doc_indexer.parse_document(full_path)
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

            return {
                "doc_nodes": total_nodes,
                "doc_edges": total_edges,
                "doc_embeddings": total_embeds,
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}
