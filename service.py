"""Knowledge base service — orchestrates all KB components.

Provides a single entry point for initializing and managing
the knowledge base (store, indexer, query services, MCP handler).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from api.mcp_server import KnowledgeBaseMCPHandler
from store.graph_queries import GraphQueryRepository
from wiki.ask import WikiAskService
from wiki.cache import WikiCache
from wiki.kb_wiki_pipeline import WikiPipelineAdapter
from wiki.mcp_tools import WikiMCPHandler
from wiki.search import WikiSearchService
from wiki.service import WikiService
from config import Settings
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from indexer.incremental_indexer import IncrementalIndexer, _stamp_repository_on_nodes
from indexer.tree_sitter_parser import TreeSitterParser
from log import get_logger
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from query.reranker import Reranker
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
        self._init_components(settings)

    @classmethod
    def from_components(
        cls,
        store: FalkorDBStore,
        settings: Settings,
        *,
        index_task_status_lookup: Callable[[str], dict[str, Any] | None] | None = None,
    ) -> KnowledgeBaseService:
        """Create a service with a pre-built store (used by ServiceRegistry for per-business instances)."""
        instance = cls.__new__(cls)
        instance._settings = settings
        instance._store = store
        instance._index_task_status_lookup = index_task_status_lookup
        instance._init_components(settings)
        return instance

    def _init_components(self, settings: Settings) -> None:
        """Wire up all sub-components against the current store."""
        if not hasattr(self, "_index_task_status_lookup"):
            self._index_task_status_lookup: Callable[[str], dict[str, Any] | None] | None = None
        self._embedding = EmbeddingGenerator.shared(config=settings.embedding)

        self._llm_provider = None
        self._enricher = None
        self._gateway_client = None
        self._repo_task_mgr = None
        if settings.llm.enabled:
            from llm.provider import LLMProvider

            self._llm_provider = LLMProvider(settings.llm)

            gateway_client = None
            if settings.llm.gateway.enabled:
                from llm.gateway_client import GatewayTaskClient, RepoTaskManager

                ws_url, http_url = settings.llm.resolve_gateway_urls()

                gateway_client = GatewayTaskClient(
                    gateway_ws_url=ws_url,
                    gateway_http_url=http_url,
                    api_key=settings.llm.api_key,
                    model=settings.llm.model,
                    timeout=settings.llm.timeout,
                )
                self._gateway_client = gateway_client

                self._repo_task_mgr = RepoTaskManager(
                    gateway_ws_url=ws_url,
                    gateway_http_url=http_url,
                    api_key=settings.llm.api_key,
                    model=settings.llm.model,
                    idle_timeout=settings.llm.gateway.idle_timeout,
                    response_timeout=settings.llm.timeout,
                )
                log.info("repo_task_manager_enabled", ws_url=ws_url, http_url=http_url)

            indexing_enrichment_on = (
                not settings.llm.gateway.enabled or settings.llm.gateway.enrichment_enabled
            )
            if indexing_enrichment_on:
                from indexer.enrichment import CodeSummaryEnricher

                self._enricher = CodeSummaryEnricher(
                    llm=self._llm_provider,
                    gateway_client=gateway_client,
                )
            else:
                self._enricher = None
                log.info("indexing_enrichment_disabled", gateway_enrichment_flag=False)

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
            doc_indexer=self._doc_indexer,
            enricher=self._enricher,
            repo_task_manager=self._repo_task_mgr,
        )

        self._graph_query = GraphQueryService(store=self._store)
        self._semantic_query = SemanticQueryService(
            store=self._store,
            embedding_gen=self._embedding,
            include_raw_docs_in_results=settings.hybrid_search.include_raw_docs_in_results,
        )
        self._reranker = Reranker(settings.rerank) if settings.rerank.enabled else None

        self._hybrid_query = HybridQueryService(
            store=self._store,
            semantic_svc=self._semantic_query,
            graph_svc=self._graph_query,
            reranker=self._reranker,
            query_expansion_enabled=settings.hybrid_search.query_expansion_enabled,
        )

        self._wiki_cache = WikiCache()

        async def _repository_exists(repo: str) -> bool:
            queries = GraphQueryRepository(self._store)
            sample = await queries.get_repository_sample_file(repo)
            return sample is not None

        self._wiki_service = WikiService(
            graph=self._store,
            llm=self._llm_provider,
            repository_exists=_repository_exists,
        )
        self._wiki_search = WikiSearchService(
            graph=self._store,
            vector=self._semantic_query,
            fts=self._store,
        )
        self._wiki_ask: WikiAskService | None = None
        if self._llm_provider is not None:
            self._wiki_ask = WikiAskService(
                search=self._wiki_search,
                llm=self._llm_provider,
                graph=self._store,
            )
        self._wiki_pipeline = WikiPipelineAdapter(
            wiki_service=self._wiki_service,
            search=self._wiki_search,
            ask=self._wiki_ask,
        )

        self._deep_search = None
        if settings.llm.enabled and self._llm_provider is not None:
            from query.deep_search import DeepSearchEngine

            self._deep_search = DeepSearchEngine(
                llm=self._llm_provider,
                hybrid_svc=self._hybrid_query,
                graph_svc=self._graph_query,
                task_manager=self._repo_task_mgr,
            )

        self._mcp_handler = KnowledgeBaseMCPHandler(
            hybrid_svc=self._hybrid_query,
            graph_svc=self._graph_query,
            indexer=self._incremental_indexer,
            doc_indexer=self._doc_indexer,
            store=self._store,
            embedding_gen=self._embedding,
            wiki_handler=WikiMCPHandler(
                pipeline=self._wiki_pipeline,
                graph=self._graph_query,
                store=self._store,
                wiki_cache=self._wiki_cache,
            ),
            deep_search_engine=self._deep_search,
            task_status_fn=self._index_task_status_lookup,
        )

    async def start(self) -> None:
        log.info("knowledge_base_starting")
        await self._store.connect()
        if self._repo_task_mgr is not None:
            await self._repo_task_mgr.start()
        log.info("knowledge_base_started")

    async def stop(self) -> None:
        log.info("knowledge_base_stopping")
        if self._repo_task_mgr is not None:
            await self._repo_task_mgr.close_all()
        if self._gateway_client is not None:
            await self._gateway_client.close()
        await self._store.close()
        log.info("knowledge_base_stopped")

    @property
    def store(self) -> FalkorDBStore:
        return self._store

    @property
    def indexer(self) -> IncrementalIndexer:
        return self._incremental_indexer

    @property
    def incremental_indexer(self) -> IncrementalIndexer:
        """Alias for :attr:`indexer` — incremental/full indexing orchestrator."""
        return self._incremental_indexer

    @property
    def doc_indexer(self) -> DocumentIndexer:
        return self._doc_indexer

    @property
    def llm_provider(self):
        return self._llm_provider

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

    @property
    def deep_search(self):
        return self._deep_search

    async def index_directory(self, directory: str, repository: str | None = None) -> dict[str, int]:
        """Full index of code + docs in a directory (streaming per-file)."""
        code_stats = await self._incremental_indexer.index_full(directory, repository=repository)

        doc_nodes_total = 0
        doc_edges_total = 0
        doc_embeds_total = 0

        from pathlib import Path

        base = Path(directory)
        exclude_dirs = set(self._doc_indexer._exclude_dirs)
        for ext in self._doc_indexer.SUPPORTED_EXTENSIONS:
            for fpath in base.rglob(f"*{ext}"):
                if any(part in exclude_dirs for part in fpath.parts):
                    continue
                try:
                    rel = str(fpath.relative_to(base))
                    doc = self._doc_indexer.parse_document(str(fpath), store_path=rel)
                    nodes, edges = self._doc_indexer.build_graph(doc)
                    _stamp_repository_on_nodes(nodes, repository)
                    await self._store.batch_upsert(nodes, edges)
                    doc_nodes_total += len(nodes)
                    doc_edges_total += len(edges)

                    embeddable = [n for n in nodes if n.properties.get("content")]
                    if embeddable:
                        items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                        embeddings = await self._embedding.generate_for_docs(items)
                        for node, emb in zip(embeddable, embeddings):
                            await self._store.set_node_embedding(node.uid, node.label, emb)
                        doc_embeds_total += len(embeddings)
                except Exception as exc:
                    from log import get_logger
                    get_logger(__name__).warning(
                        "doc_index_error", file=str(fpath), error=str(exc),
                    )

        return {
            "code_nodes": code_stats.get("nodes", 0),
            "code_edges": code_stats.get("edges", 0),
            "code_embeddings": code_stats.get("embeddings", 0),
            "doc_nodes": doc_nodes_total,
            "doc_edges": doc_edges_total,
            "doc_embeddings": doc_embeds_total,
        }
