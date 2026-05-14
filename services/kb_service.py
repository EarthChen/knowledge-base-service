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
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.service import WikiService
from core.config import Settings
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from indexer.incremental_indexer import (
    IncrementalIndexer,
    _stamp_repository_metadata,
    _try_git_head_sha,
)
from indexer.tree_sitter_parser import TreeSitterParser
from core.log import get_logger
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from query.reranker import Reranker
from query.semantic_query import SemanticQueryService
from store.analysis_store import AnalysisStore
from store.falkordb_store import FalkorDBStore
from store.search_store import SearchStore
from store.settings_store import SettingsStore
from store.traversal_store import TraversalStore

log = get_logger(__name__)


def _wrap_wiki_llm(raw_llm: object) -> object:
    """Expose a ``.generate``-compatible port for :class:`wiki.rag.engine.IterativeRAGEngine`."""
    if hasattr(raw_llm, "generate"):
        return raw_llm
    from llm.base_provider import GatewayLLMProviderAdapter, LLMPortBridge

    return LLMPortBridge(GatewayLLMProviderAdapter(raw_llm))  # type: ignore[arg-type]


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
        self._settings_store: SettingsStore | None = None
        self._init_components(settings)

    @classmethod
    def from_components(
        cls,
        store: FalkorDBStore,
        settings: Settings,
        *,
        index_task_status_lookup: Callable[[str], dict[str, Any] | None] | None = None,
        repo_registry: Any | None = None,
        settings_store: SettingsStore | None = None,
    ) -> KnowledgeBaseService:
        """Create a service with a pre-built store (used by ServiceRegistry for per-business instances)."""
        instance = cls.__new__(cls)
        instance._settings = settings
        instance._store = store
        instance._index_task_status_lookup = index_task_status_lookup
        instance._repo_registry = repo_registry
        instance._settings_store = settings_store
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

            from indexer.enrichment import CodeSummaryEnricher

            self._enricher = CodeSummaryEnricher(
                llm=self._llm_provider,
                gateway_client=gateway_client,
            )

        self._wiki_deferred_enrichment: DeferredEnrichmentService | None = None
        if self._enricher is not None:
            self._wiki_deferred_enrichment = DeferredEnrichmentService(
                store=self._store,
                enricher=self._enricher,
                embedding_gen=self._embedding,
            )

        self._wiki_flow_inferencer = None
        if self._llm_provider is not None and settings.llm.business_flow_enabled:
            from indexer.business_flow_inferencer import BusinessFlowInferencer

            self._wiki_flow_inferencer = BusinessFlowInferencer(
                llm=self._llm_provider,
                store=self._store,
                business_flow_enabled=True,
            )

        self._parser = TreeSitterParser(supported_languages=settings.supported_languages)
        hs = settings.hybrid_search
        self._graph_builder = CodeGraphBuilder(
            parser=self._parser,
            file_extensions=settings.file_extensions,
            child_chunk_enabled=hs.use_child_chunks,
            child_chunk_window_chars=hs.child_chunk_window_chars,
            child_chunk_stride_chars=hs.child_chunk_stride_chars,
            child_chunk_min_parent_chars=hs.child_chunk_min_parent_chars,
        )
        self._doc_indexer = DocumentIndexer(
            child_chunk_enabled=hs.use_child_chunks,
            child_chunk_window_chars=hs.child_chunk_window_chars,
            child_chunk_stride_chars=hs.child_chunk_stride_chars,
            child_chunk_min_parent_chars=hs.child_chunk_min_parent_chars,
        )
        self._incremental_indexer = IncrementalIndexer(
            store=self._store,
            graph_builder=self._graph_builder,
            embedding_gen=self._embedding,
            doc_indexer=self._doc_indexer,
            enricher=self._enricher,
            repo_task_manager=self._repo_task_mgr,
            wiki_auto_updater=self._auto_update_wiki,
            settings_store=getattr(self, "_settings_store", None),
        )

        self._traversal_store = TraversalStore(self._store)
        self._search_store = SearchStore(self._store)
        self._analysis_store = AnalysisStore(self._store)
        self._graph_query = GraphQueryService(store=self._store, traversal=self._traversal_store)
        self._semantic_query = SemanticQueryService(
            store=self._store,
            embedding_gen=self._embedding,
            include_raw_docs_in_results=settings.hybrid_search.include_raw_docs_in_results,
            search_store=self._search_store,
        )
        self._reranker = Reranker(settings.rerank) if settings.rerank.enabled else None

        self._hybrid_query = HybridQueryService(
            store=self._store,
            semantic_svc=self._semantic_query,
            graph_svc=self._graph_query,
            reranker=self._reranker,
            query_expansion_enabled=hs.query_expansion_enabled,
            use_child_chunks=hs.use_child_chunks,
            search_store=self._search_store,
            enable_bm25=hs.enable_bm25,
            bm25_weight=hs.bm25_weight,
        )

        self._wiki_cache = WikiCache()

        async def _repository_exists(repo: str) -> bool:
            queries = GraphQueryRepository(self._store)
            return await queries.get_repository_node_count(repo) > 0

        from store.wiki_store import WikiStore as _WikiStore

        community_service = None
        if settings.wiki.community_context_enabled:
            try:
                from query.community_detection import CommunityDetector
                from wiki.community_context import CachedCommunityService

                community_service = CachedCommunityService(
                    self._store,
                    CommunityDetector(self._store),
                )
            except Exception:  # noqa: BLE001 — optional wiring
                log.warning("community_context_service_unavailable", exc_info=True)

        self._wiki_service = WikiService(
            graph=self._store,
            llm=self._llm_provider,
            repository_exists=_repository_exists,
            store=self._store,
            deferred_enrichment=self._wiki_deferred_enrichment,
            flow_inferencer=self._wiki_flow_inferencer,
            wiki_store=_WikiStore(self._store),
            community_service=community_service,
            wiki_config=settings.wiki,
            embedding_config=settings.embedding,
        )
        self._wiki_search = WikiSearchService(
            graph=self._store,
            vector=self._semantic_query,
            fts=self._store,
            embedding_gen=self._embedding,
        )
        self._wiki_ask: WikiAskService | None = None
        hybrid_rag_retriever: Any = None
        nl_cypher: Any = None
        if self._llm_provider is not None:
            from query.nl_cypher import NLCypherService
            from wiki.rag.engine import IterativeRAGEngine
            from wiki.rag.hybrid_graph_retriever import HybridGraphRetriever

            nl_cypher = NLCypherService(store=self._store, llm=self._llm_provider)
            hybrid_rag_retriever = HybridGraphRetriever(
                hybrid_service=self._hybrid_query,
                graph_service=self._graph_query,
                nl_cypher=nl_cypher,
            )
            wrapped = _wrap_wiki_llm(self._llm_provider)
            rag_engine = IterativeRAGEngine(
                retriever=hybrid_rag_retriever,
                llm=wrapped,
            )
            self._wiki_ask = WikiAskService(
                search=self._wiki_search,
                llm=wrapped,
                rag_engine=rag_engine,
                graph=self._store,
            )
        self._wiki_pipeline = WikiPipelineAdapter(
            wiki_service=self._wiki_service,
            search=self._wiki_search,
            ask=self._wiki_ask,
            store=self._store,
        )

        self._deep_search = None
        rag_engine = None
        if settings.llm.enabled and self._llm_provider is not None:
            from query.deep_search import DeepSearchEngine
            from wiki.rag.engine import IterativeRAGEngine
            from wiki.rag.multi_repo_retriever import MultiRepoRetriever

            repo_registry = getattr(self, "_repo_registry", None)
            if repo_registry is not None and hasattr(repo_registry, "list_all"):
                deep_retriever = MultiRepoRetriever(
                    self._hybrid_query,
                    repo_registry=repo_registry,
                    nl_cypher=nl_cypher,
                )
            else:
                # MultiRepoRetriever needs RepoRegistry.list_all() for cross-repo retrieval;
                # without a registry, HybridGraphRetriever remains the deep-search retriever.
                deep_retriever = hybrid_rag_retriever

            rag_engine = IterativeRAGEngine(
                retriever=deep_retriever,
                llm=_wrap_wiki_llm(self._llm_provider),
            )
            self._deep_search = DeepSearchEngine(rag_engine=rag_engine)

        _wiki_rag_engine = rag_engine
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
                wiki_config=settings.wiki,
                rag_engine=_wiki_rag_engine,
            ),
            task_status_fn=self._index_task_status_lookup,
            repo_registry=getattr(self, "_repo_registry", None),
        )

    async def _auto_update_wiki(self, repository: str) -> Any:
        """Callback for IncrementalIndexer: triggers business-level wiki regeneration."""
        return await self._wiki_service.generate_business_wiki(
            business_id="default",
            incremental=True,
        )

    async def ensure_fulltext_indexes(self) -> None:
        await self._search_store.ensure_fulltext_indexes()

    async def start(self) -> None:
        log.info("knowledge_base_starting")
        await self._store.connect()
        await self.ensure_fulltext_indexes()
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
    def wiki_deferred_enrichment(self) -> DeferredEnrichmentService | None:
        """Optional wiki-stage batch enricher (requires LLM + :class:`CodeSummaryEnricher`)."""
        return self._wiki_deferred_enrichment

    @property
    def wiki_flow_inferencer(self):
        """Optional wiki-stage business-flow inferencer (requires LLM + ``business_flow_enabled``)."""
        return self._wiki_flow_inferencer

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
        commit_sha = _try_git_head_sha(str(directory.resolve()))
        for fpath in DocumentIndexer.iter_supported_paths(base):
            if any(part in exclude_dirs for part in fpath.parts):
                continue
            try:
                rel = str(fpath.relative_to(base))
                doc = self._doc_indexer.parse_document(str(fpath), store_path=rel)
                nodes, edges = self._doc_indexer.build_graph(doc)
                _stamp_repository_metadata(nodes, repository, commit_sha=commit_sha)
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
                from core.log import get_logger

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
