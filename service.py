"""Knowledge base service — orchestrates all KB components.

Provides a single entry point for initializing and managing
the knowledge base (store, indexer, query services, MCP handler).
"""

from __future__ import annotations

from config import Settings
from log import get_logger

from api.mcp_server import KnowledgeBaseMCPHandler
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator
from indexer.incremental_indexer import IncrementalIndexer
from indexer.tree_sitter_parser import TreeSitterParser
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from query.semantic_query import SemanticQueryService
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


class KnowledgeBaseService:
    """Top-level facade for the knowledge base subsystem."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

        falkordb_config = settings.falkordb
        if settings.falkordb_password and not falkordb_config.password:
            falkordb_config = falkordb_config.model_copy(update={"password": settings.falkordb_password})

        self._store = FalkorDBStore(
            config=falkordb_config,
            embedding_dim=settings.embedding.dimension,
        )
        self._embedding = EmbeddingGenerator(config=settings.embedding)
        self._parser = TreeSitterParser(supported_languages=settings.supported_languages)
        self._graph_builder = CodeGraphBuilder(
            parser=self._parser,
            file_extensions=settings.file_extensions,
        )
        self._doc_indexer = DocumentIndexer()
        self._incremental_indexer = IncrementalIndexer(
            store=self._store,
            graph_builder=self._graph_builder,
            embedding_gen=self._embedding,
        )

        self._graph_query = GraphQueryService(store=self._store)
        self._semantic_query = SemanticQueryService(
            store=self._store,
            embedding_gen=self._embedding,
        )
        self._hybrid_query = HybridQueryService(
            store=self._store,
            semantic_svc=self._semantic_query,
            graph_svc=self._graph_query,
        )

        self._mcp_handler = KnowledgeBaseMCPHandler(
            hybrid_svc=self._hybrid_query,
            graph_svc=self._graph_query,
            indexer=self._incremental_indexer,
            doc_indexer=self._doc_indexer,
            store=self._store,
            embedding_gen=self._embedding,
        )

    async def start(self) -> None:
        log.info("knowledge_base_starting")
        await self._store.connect()
        log.info("knowledge_base_started")

    async def stop(self) -> None:
        log.info("knowledge_base_stopping")
        await self._store.close()
        log.info("knowledge_base_stopped")

    @property
    def store(self) -> FalkorDBStore:
        return self._store

    @property
    def indexer(self) -> IncrementalIndexer:
        return self._incremental_indexer

    @property
    def doc_indexer(self) -> DocumentIndexer:
        return self._doc_indexer

    @property
    def graph_query(self) -> GraphQueryService:
        return self._graph_query

    @property
    def semantic_query(self) -> SemanticQueryService:
        return self._semantic_query

    @property
    def hybrid_query(self) -> HybridQueryService:
        return self._hybrid_query

    @property
    def mcp_handler(self) -> KnowledgeBaseMCPHandler:
        return self._mcp_handler

    async def index_directory(self, directory: str) -> dict[str, int]:
        """Full index of code + docs in a directory."""
        code_stats = await self._incremental_indexer.index_full(directory)

        doc_nodes, doc_edges = self._doc_indexer.index_directory(directory)
        await self._store.batch_upsert(doc_nodes, doc_edges)

        embeddable = [n for n in doc_nodes if n.properties.get("content")]
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

        return {
            "code_nodes": code_stats.get("nodes", 0),
            "code_edges": code_stats.get("edges", 0),
            "code_embeddings": code_stats.get("embeddings", 0),
            "doc_nodes": len(doc_nodes),
            "doc_edges": len(doc_edges),
            "doc_embeddings": len(embeddable),
        }
