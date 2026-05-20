"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from core.config import AppWikiFlags as WikiAppConfig, EmbeddingConfig, get_settings
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from wiki.community_context import CachedCommunityService, format_communities_markdown
from wiki.llm_port import LLMPort
from wiki.protocols import WikiGraphStorePort
from store.schema import EdgeType, GraphNode, NodeLabel
from wiki.ask import set_default_resolver
from wiki.backlink_builder import BacklinkBuilder
from wiki.composer import WikiComposer
from wiki.confidence_inputs import gather_confidence_inputs, set_wiki_page_confidence_scores
from wiki.dependency_graph import DomainNode
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.context import WikiContextBuilder
from wiki.data_collector import DataCollectorPort, WikiDataCollector
from wiki.delegation import evaluate_delegation, group_children_by_graph
from wiki.export_service import WikiExportService
from wiki.flow_writer import BusinessFlowWriter
from wiki.incremental_diff import compute_domain_diff, compute_wiki_diff
from wiki.memory_loop import MemoryLoop
from wiki.page_composer_service import WikiPageComposerService
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    SkeletonStrategy,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
    WikiPageSummary,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)
from wiki.persistence import WikiPagePersistence
from wiki.structure_planner import WikiScopeError, WikiStructurePlanner
from wiki.tree_linker import WikiTreeLinker
from wiki.token_budget import TokenBudgetResolver
from wiki.tree_builder import WikiTreeBuilder
from wiki.wikilink_cache import WikiLinkCache

from core.log import get_logger
from store.wiki_store import WikiStore

if TYPE_CHECKING:
    from indexer.business_flow_inferencer import BusinessFlowInferencer
    from wiki.change_detector import AffectedPageSet
    from wiki.enrichment_coordinator import WikiEnrichmentCoordinator

log = get_logger(__name__)

_VALID_WIKI_REVIEW_STATUSES = frozenset({
    "approved",
    "needs_revision",
    "pending_review",
    "revised",
})


def _graph_query_positional_rows(result: Any) -> list[list[Any]]:
    rs = getattr(result, "result_set", None)
    if isinstance(rs, list):
        return rs
    raw = getattr(result, "raw", None)
    return raw if isinstance(raw, list) else []


def _compilation_snapshot_to_page_dicts(
    data: dict[str, str], repository: str, layered: bool
) -> list[dict[str, Any]]:
    """Map snapshot markdown blobs to the dict shape expected by ``persist_wiki_pages``."""
    ts = datetime.now(timezone.utc).isoformat()
    out: list[dict[str, Any]] = []
    for key, content in data.items():
        if not layered:
            path = "wiki_snapshot.md"
            title = f"Knowledge Snapshot — {repository}"
        elif key == "index":
            path = "wiki_snapshot.md"
            title = f"Knowledge Snapshot — {repository}"
        else:
            path = f"wiki_snapshot_modules/{key}.md"
            title = f"Snapshot — {key}"
        out.append(
            {
                "path": path,
                "title": title,
                "content": content,
                "page_type": PageType.INDEX.value,
                "generated_at": ts,
            }
        )
    return out


def _enrichment_level_for_api(level: object | None) -> str | None:
    if level is None:
        return None
    if isinstance(level, EnrichmentLevel):
        return level.value
    return str(level)


from wiki.errors import WikiRepoNotFoundError as WikiRepoNotFoundError  # noqa: F401 — re-export for backward compat


class WikiService:
    """Wiki generation pipeline with injectable graph and optional LLM."""

    def __init__(
        self,
        graph: DataCollectorPort,
        llm: LLMPort | None,
        repository_exists: Callable[[str], Awaitable[bool]],
        llm_factory: LLMProviderFactory | None = None,
        store: WikiGraphStorePort | None = None,
        deferred_enrichment: DeferredEnrichmentService | None = None,
        flow_inferencer: BusinessFlowInferencer | None = None,
        wiki_store: WikiStore | None = None,
        memory_loop: MemoryLoop | None = None,
        community_service: CachedCommunityService | None = None,
        *,
        wiki_config: WikiAppConfig,
        embedding_config: EmbeddingConfig,
        redis_conn: Any | None = None,  # TODO: narrow type — assigned only; unused within WikiService today
        task_supervisor: Any | None = None,
    ) -> None:
        self._graph = graph
        self._planner = WikiStructurePlanner(graph)
        self._wiki_store = wiki_store
        self._wiki_cfg = wiki_config
        _llm_budget = self._wiki_cfg.default_llm_budget or None
        _ctx_window = getattr(get_settings().llm, "max_context_tokens", 128_000)
        self._budget_resolver = TokenBudgetResolver(
            base=_llm_budget,
            ceiling=_ctx_window,
        )
        set_default_resolver(self._budget_resolver)
        self._embedding_cfg = embedding_config
        self._collector = WikiDataCollector(
            graph,
            wiki_config=wiki_config,
            embedding_config=embedding_config,
            wiki_store=wiki_store,
            rag_enabled=wiki_config.rag_enabled,
        )
        self._llm = llm
        self._llm_factory = llm_factory
        self._export_service = WikiExportService()
        self._repository_exists = repository_exists
        self._store = store
        self._deferred_enrichment = deferred_enrichment
        self._flow_inferencer = flow_inferencer
        self._memory_loop = memory_loop
        self._community_service = community_service
        self._redis = redis_conn
        self._task_supervisor = task_supervisor
        self._persistence = WikiPagePersistence(
            store=store,
            graph=graph,
            wiki_store=wiki_store,
            wiki_cfg=wiki_config,
            embedding_cfg=embedding_config,
            llm=llm,
        )
        self._tree_linker = WikiTreeLinker(
            store=store,
            wiki_store=wiki_store,
            wiki_cfg=wiki_config,
            persistence=self._persistence,
        )
        self._flow_writer = BusinessFlowWriter(
            store=store,
            wiki_cfg=wiki_config,
            flow_inferencer=flow_inferencer,
        )
        from wiki.enrichment_coordinator import WikiEnrichmentCoordinator

        self._enrichment = WikiEnrichmentCoordinator(
            store=store,
            graph=graph,
            wiki_cfg=wiki_config,
            persistence=self._persistence,
            llm_resolver=self._resolve_llm_port,
            repository_exists=repository_exists,
            deferred_enrichment=deferred_enrichment,
            supervisor=task_supervisor,
        )
        self._page_composer = WikiPageComposerService(
            graph=graph,
            collector=self._collector,
            wiki_store=wiki_store,
            wiki_cfg=wiki_config,
            store=store,
            budget_resolver=self._budget_resolver,
            llm=llm,
            persistence=self._persistence,
            enrichment=self._enrichment,
            composer_factory=self._composer_for,
            llm_resolver=self._resolve_llm_port,
            memory_loop=memory_loop,
            community_service=community_service,
        )

    def _get_enrichment(self) -> WikiEnrichmentCoordinator:
        enc = getattr(self, "_enrichment", None)
        if enc is not None:
            return enc
        from wiki.enrichment_coordinator import WikiEnrichmentCoordinator

        self._enrichment = WikiEnrichmentCoordinator(
            store=getattr(self, "_store", None),
            graph=getattr(self, "_graph", None),
            wiki_cfg=self._wiki_cfg,
            persistence=getattr(self, "_persistence", None),
            llm_resolver=self._resolve_llm_port,
            repository_exists=getattr(self, "_repository_exists", None),
            deferred_enrichment=getattr(self, "_deferred_enrichment", None),
            supervisor=getattr(self, "_task_supervisor", None),
        )
        return self._enrichment

    def _composer_for(self, llm_provider: str | None) -> WikiComposer:
        llm_port = self._resolve_llm_port(llm_provider)
        return WikiComposer(
            llm_port,
            WikiContextBuilder(llm_port),
            store=self._graph,
            wiki_store=self._wiki_store,
            memory_loop=self._memory_loop,
        )

    def _resolve_llm_port(self, llm_provider: str | None) -> LLMPort | None:
        if self._llm_factory is not None:
            provider = self._llm_factory.get_provider(llm_provider)
            return LLMPortBridge(provider)
        return self._llm

    def _confidence_scoring_enabled(self) -> bool:
        return self._persistence.confidence_scoring_enabled()

    async def _run_compilation_snapshot(self, business_id: str, repository: str) -> None:
        if not getattr(self._wiki_cfg, "snapshot_enabled", True):
            return
        if self._store is None or not hasattr(self._store, "execute_query"):
            return
        if not hasattr(self._store, "persist_wiki_pages"):
            return
        from wiki.compilation_snapshot import WikiCompilationSnapshot

        snap = WikiCompilationSnapshot(self._store, self._wiki_cfg)

        async def _persist_snapshot(data: dict[str, str], repo: str, layered: bool) -> None:
            page_dicts = _compilation_snapshot_to_page_dicts(data, repo, layered)
            if not page_dicts:
                return
            try:
                await self._store.persist_wiki_pages(repo, page_dicts)
            except Exception:
                log.warning(
                    "snapshot_persist_pages_failed", repository=repo, exc_info=True
                )

        try:
            _snap_timeout = 120
            log.info("compilation_snapshot_start", repository=repository)
            await asyncio.wait_for(
                snap.generate_and_persist(
                    business_id, repository, persist_fn=_persist_snapshot
                ),
                timeout=_snap_timeout,
            )
            log.info("compilation_snapshot_built", repository=repository)
        except TimeoutError:
            log.warning("compilation_snapshot_timeout", repository=repository, timeout_s=_snap_timeout)
        except Exception:
            log.warning("compilation_snapshot_failed", repository=repository, exc_info=True)

    async def _ensure_repo(self, repository: str) -> None:
        if not await self._repository_exists(repository):
            raise WikiRepoNotFoundError(repository)

    async def ensure_repository(self, repository: str) -> None:
        """Raise ``WikiRepoNotFoundError`` when the repository is not indexed."""
        await self._ensure_repo(repository)

    async def get_domain_tree(self, business_id: str) -> dict[str, Any]:
        """Hierarchical domain tree and review status from the latest pipeline run (when persisted)."""
        return await self._tree_linker.get_domain_tree(business_id)

    async def get_topic_tree(self, business_id: str) -> dict[str, Any]:
        """Topic and domain-overview pages as a nested tree for dashboard wiki navigation."""
        return await self._tree_linker.get_topic_tree(business_id)

    async def get_domain_edges(self, business_id: str) -> dict[str, Any]:
        """Compute cross-domain CALLS edges for knowledge graph."""
        return await self._tree_linker.get_domain_edges(business_id)

    def _config_for(
        self,
        mode: str,
        format: str,
        repository: str,
        language: str = "en",
    ) -> WikiConfig:
        return WikiConfig(repository=repository, mode=mode, format=format, language=language)

    async def _generate_business_flows(self, repository: str) -> int:
        return await self._flow_writer.generate_business_flows(repository)

    async def _build_call_chain(self, entry_point: dict[str, Any]) -> list[dict[str, str]]:
        return await self._flow_writer.build_call_chain(entry_point)

    async def _persist_flow(self, flow: dict[str, Any], repository: str) -> None:
        return await self._flow_writer.persist_flow(flow, repository)

    async def generate(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
        llm_provider: str | None = None,
        token_budget_multiplier: float = 1.0,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        _importance_tiers: dict[str, ImportanceTier] = {}
        app_cfg = self._wiki_cfg
        if app_cfg.code_budget_enabled and self._wiki_store is not None:
            from wiki.importance_scorer import ImportanceScorer

            scorer = ImportanceScorer(
                self._wiki_store,
                core_percentile=app_cfg.importance_core_percentile,
                standard_percentile=app_cfg.importance_standard_percentile,
            )
            _importance_tiers = await scorer.score_all(repository)
            log.info(
                "importance_scoring_complete",
                repository=repository,
                entities=len(_importance_tiers),
            )
        structure = await self._planner.plan(
            repository,
            scope,
            importance_tiers=_importance_tiers or None,
        )
        community_markdown = ""
        if self._community_service and getattr(
            self._wiki_cfg, "community_context_enabled", True,
        ):
            try:
                cr = await self._community_service.get_cached(repository)
                community_markdown = format_communities_markdown(cr)
            except Exception:  # noqa: BLE001 — optional context: never fail wiki generation
                log.warning("community_context_failed", repository=repository, exc_info=True)
        composer = self._composer_for(llm_provider)
        if self._deferred_enrichment:
            enriched = await self._deferred_enrichment.enrich_remaining(repository)
            log.info(
                "deferred_enrichment_complete",
                repository=repository,
                enriched_count=enriched,
            )
        if self._flow_inferencer:
            flows_created = await self._generate_business_flows(repository)
            log.info("business_flows_generated", repository=repository, count=flows_created)
        pages, degraded = await self._compose_all_pages(
            repository,
            structure,
            config,
            composer,
            _importance_tiers,
            llm_provider,
            community_markdown=community_markdown,
            token_budget_multiplier=token_budget_multiplier,
            progress_callback=progress_callback,
        )
        await self._persist_pages_to_graph(
            repository, pages, language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
        await self._sync_graph_references_into_page_content(
            repository,
            pages,
            language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
        await self._run_compilation_snapshot("default", repository)
        if self._deferred_enrichment:
            refreshed = await self._deferred_enrichment.refresh_stale_embeddings(repository)
            log.info(
                "embedding_refresh_complete",
                repository=repository,
                refreshed=refreshed,
            )

        # Establish baseline for incremental updates
        try:
            query_port = self._store if self._store is not None else self._graph
            wiki_meta = (
                self._wiki_store
                if self._wiki_store is not None
                else (WikiStore(query_port) if query_port else None)
            )
            if wiki_meta:
                await self._bulk_set_wiki_code_hashes(repository)
                current_ver = await wiki_meta.get_wiki_generation_version(repository)
                await wiki_meta.set_wiki_generation_version(
                    repository, (current_ver or 0) + 1,
                )
                log.info("wiki_baseline_established", repository=repository)
        except Exception:
            log.warning("wiki_baseline_failed", repository=repository, exc_info=True)

        return self._export_service.bundle_generation_result(
            pages,
            structure,
            export_format=format,
            degraded=degraded,
        )

    async def _bulk_set_wiki_code_hashes(self, repository: str) -> None:
        """After full generation, mark all entities as wiki-synced."""
        return await self._persistence.bulk_set_wiki_code_hashes(repository)

    async def inject_wikilinks(self, repository: str, pages: list[WikiPage]) -> None:
        """Append ``## Related Pages`` using outgoing ``WIKI_REFERENCES`` from the graph."""
        return await self._persistence.inject_wikilinks(repository, pages)

    async def _sync_graph_references_into_page_content(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str,
        skip_claim_tracking: bool,
    ) -> None:
        """Build ``WIKI_REFERENCES`` from the code graph, inject related links into page bodies, re-persist."""
        return await self._persistence.sync_graph_references_into_page_content(
            repository, pages, language=language, skip_claim_tracking=skip_claim_tracking
        )

    async def _update_wiki_code_hashes(self, repository: str, uids: list[str]) -> None:
        """After successful wiki page generation, set wiki_code_hash = code_hash."""
        return await self._persistence.update_wiki_code_hashes(repository, uids)

    @staticmethod
    def _sort_by_depth(
        uids: list[str],
        contains_edges: list[dict[str, str]],
    ) -> list[str]:
        """Sort uids by graph depth — leaves first, roots last."""
        return WikiPageComposerService.sort_by_depth(uids, contains_edges)

    def _resume_source_content_hash(self, graph_node: GraphNode, source_content: str) -> str:
        """Prefer graph ``code_hash`` (matches incremental ``wiki_code_hash``); fallback to hashed sources."""
        return self._page_composer.resume_source_content_hash(graph_node, source_content)

    async def _load_wikipage_for_resume_entity(
        self,
        repository: str,
        graph_node: GraphNode,
        *,
        structure_path: str,
        structure_title: str,
        structure_page_type: PageType,
        config: WikiConfig,
    ) -> WikiPage | None:
        """Load persisted markdown from DB when compose is skipped via resume-from-saved."""
        return await self._page_composer.load_wikipage_for_resume_entity(
            repository,
            graph_node,
            structure_path=structure_path,
            structure_title=structure_title,
            structure_page_type=structure_page_type,
            config=config,
        )

    async def generate_incremental(
        self,
        repository: str,
        config: WikiConfig | None = None,
        llm_provider: str | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        *,
        language: str = "en",
        token_budget_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        """Incremental wiki update: only regenerate pages for entities whose code hash changed."""
        query_port = self._store if self._store is not None else self._graph
        if query_port is None or not hasattr(query_port, "execute_query"):
            return {"status": "error", "message": "No graph store available"}

        wiki_meta = self._wiki_store if self._wiki_store is not None else WikiStore(query_port)

        last_version = await wiki_meta.get_wiki_generation_version(repository)
        if last_version is None:
            log.info("incremental_no_baseline", repository=repository)
            return {
                "status": "no_baseline",
                "message": "No previous generation found. Run full generation first.",
            }

        diff = await compute_wiki_diff(query_port, repository, since_version=last_version)
        if diff.is_empty:
            log.info("incremental_no_changes", repository=repository)
            return {"status": "no_changes", "changed": 0}

        if progress_callback:
            await progress_callback({"phase": "incremental_diff", "changed": diff.total_affected})

        all_affected_uids = diff.changed_uids | diff.affected_parents
        updated_uids: list[str] = []
        regenerated_pages: list[WikiPage] = []
        effective_config = config or self._config_for("full", "json", repository, language)

        _importance_tiers: dict[str, ImportanceTier] = {}
        app_cfg = self._wiki_cfg
        if app_cfg.code_budget_enabled and self._wiki_store is not None:
            from wiki.importance_scorer import ImportanceScorer

            scorer = ImportanceScorer(
                self._wiki_store,
                core_percentile=app_cfg.importance_core_percentile,
                standard_percentile=app_cfg.importance_standard_percentile,
            )
            _importance_tiers = await scorer.score_all(repository)

        _sk_light_raw = str(getattr(self._wiki_cfg, "skeleton_light_model", "") or "").strip()
        skeleton_light_model = _sk_light_raw if _sk_light_raw else None

        try:
            await self._ensure_repo(repository)
            composer = self._composer_for(llm_provider)

            graph_nodes_by_uid: dict[str, GraphNode] = {}
            batch_find = getattr(self._graph, "find_nodes_by_uids", None)
            if batch_find is not None:
                try:
                    graph_nodes_by_uid = await batch_find(
                        repository, list(all_affected_uids),
                    )
                except Exception:
                    log.debug("incremental_prefetch_nodes_batch_failed", exc_info=True)
            else:
                for u in all_affected_uids:
                    try:
                        n = await self._graph.find_node_by_uid(repository, u)
                        if n is not None:
                            graph_nodes_by_uid[u] = n
                    except Exception:
                        log.debug("incremental_prefetch_node_failed", uid=u, exc_info=True)

            glossary: dict[str, str] = {}
            if composer._wiki_store is not None:
                try:
                    mod_names = list({
                        n.properties.get("name", "")
                        for n in graph_nodes_by_uid.values()
                        if n.properties.get("name")
                    })
                    glossary = await composer._ctx.build_glossary(mod_names, mod_names)
                except Exception:
                    log.warning(
                        "incremental_glossary_build_failed",
                        repository=repository,
                        exc_info=True,
                    )

            contains_edges: list[dict[str, str]] = []
            if hasattr(query_port, "execute_query"):
                try:
                    uid_list = list(all_affected_uids)
                    cq = (
                        "MATCH (a)-[:CONTAINS]->(b) "
                        "WHERE a.uid IN $uids AND b.uid IN $uids "
                        "RETURN a.uid AS source, b.uid AS target"
                    )
                    cres = await query_port.execute_query(cq, {"uids": uid_list})
                    crows = getattr(cres, "data", []) or []
                    contains_edges = [
                        {"source": str(r.get("source", "")), "target": str(r.get("target", ""))}
                        for r in crows
                        if isinstance(r, dict)
                    ]
                except Exception:
                    log.debug("incremental_depth_sort_failed", exc_info=True)

            sorted_uids = self._sort_by_depth(list(all_affected_uids), contains_edges)
            just_generated: dict[str, WikiPage] = {}
            parent_pages_by_entity: dict[str, Any] = {}
            if composer._wiki_store is not None and contains_edges:
                parent_uids = {
                    str(e.get("source", ""))
                    for e in contains_edges
                    if e.get("source")
                }
                batch_parent_fn = getattr(
                    composer._wiki_store, "get_pages_by_entity_uids", None,
                )
                if batch_parent_fn is not None and parent_uids:
                    try:
                        parent_pages_by_entity = await batch_parent_fn(
                            repository, list(parent_uids),
                        )
                    except Exception:
                        log.debug("incremental_parent_pages_batch_failed", exc_info=True)

            for uid in sorted_uids:
                try:
                    graph_node = graph_nodes_by_uid.get(uid)
                    if graph_node is None:
                        continue
                    page_type = (
                        PageType.MODULE_OVERVIEW
                        if graph_node.label == NodeLabel.MODULE
                        else PageType.CLASS_DETAIL
                    )
                    tier = _importance_tiers.get(graph_node.uid)
                    code_budget = self._budget_for_tier(
                        tier, multiplier=token_budget_multiplier,
                    )
                    page_data = await self._collector.collect(
                        repository, graph_node, code_budget=code_budget,
                    )
                    if tier is not None:
                        page_data.importance_tier = tier
                    skeleton_strat = self._resolve_skeleton_strategy(tier)
                    parent_context = ""
                    parent_edges = [
                        e
                        for e in page_data.edges
                        if e.edge_type == EdgeType.CONTAINS and e.target_uid == uid
                    ]
                    if parent_edges and composer._wiki_store is not None:
                        try:
                            parent_uid = parent_edges[0].source_uid
                            parent_pg_cached = just_generated.get(parent_uid)
                            if parent_pg_cached is not None and hasattr(parent_pg_cached, "content"):
                                parent_context = str(parent_pg_cached.content)[:1200]
                            else:
                                parent_page = parent_pages_by_entity.get(parent_uid)
                                if parent_page is None and composer._wiki_store is not None:
                                    parent_page = await composer._wiki_store.get_page_by_entity_uid(
                                        repository, parent_uid,
                                    )
                                if parent_page and hasattr(parent_page, "content"):
                                    parent_context = str(parent_page.content)[:1200]
                        except Exception:
                            log.debug("incremental_parent_context_miss", uid=uid)
                    page = await composer.compose_page(
                        page_data,
                        page_type,
                        effective_config,
                        importance_tier=tier,
                        skeleton_strategy=skeleton_strat,
                        skeleton_light_model=skeleton_light_model,
                        parent_context=parent_context,
                        glossary=glossary,
                    )
                    if page is not None:
                        just_generated[uid] = page
                        page.metadata.enrichment_level = EnrichmentLevel.BASE
                        page._source_entity_uid = graph_node.uid  # type: ignore[attr-defined]
                        regenerated_pages.append(page)
                        updated_uids.append(uid)
                except Exception:
                    log.warning("incremental_entity_failed", uid=uid, exc_info=True)

            if regenerated_pages:
                await self._persist_pages_to_graph(
                    repository, regenerated_pages, language=language,
                )

            if updated_uids:
                await self._update_wiki_code_hashes(repository, updated_uids)
                current_version = last_version + 1
                await wiki_meta.set_wiki_generation_version(repository, current_version)
            else:
                current_version = last_version

            if progress_callback:
                await progress_callback({
                    "phase": "incremental_complete",
                    "pages_regenerated": len(regenerated_pages),
                    "version": current_version,
                })

            log.info(
                "incremental_complete",
                repository=repository,
                pages_regenerated=len(regenerated_pages),
                version=current_version,
            )

            return {
                "status": "success",
                "pages_regenerated": len(regenerated_pages),
                "changed_entities": len(diff.changed_uids),
                "affected_parents": len(diff.affected_parents),
                "version": current_version,
            }
        except Exception:
            log.error("incremental_failed", repository=repository, exc_info=True)
            return {"status": "failed", "pages_regenerated": len(regenerated_pages)}

    async def bump_affected_wiki_pages(
        self,
        repository: str,
        affected: AffectedPageSet,
        language: str = "en",
        token_budget_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        """Mark affected wiki pages as updated (version bump). Falls back to full regeneration on failure."""

        if not affected.page_uids:
            return {"pages_regenerated": 0, "pages_total": 0, "trigger": affected.trigger}

        if self._store is None or not hasattr(self._store, "execute_query"):
            return {
                "pages_regenerated": 0,
                "pages_total": len(affected.page_uids),
                "trigger": affected.trigger,
                "errors": [],
            }

        try:
            pages_regenerated = 0
            errors: list[str] = []

            for page_uid in affected.page_uids:
                try:
                    # Fetch existing WikiPage
                    page_q = (
                        "MATCH (wp:WikiPage {uid: $uid, repository: $repo}) "
                        "RETURN wp.path AS path, wp.title AS title, wp.repository AS repo"
                    )
                    result = await self._store.execute_query(
                        page_q, {"uid": page_uid, "repo": repository},
                    )
                    rows = getattr(result, "data", []) or []
                    if not rows:
                        continue

                    row = rows[0] if isinstance(rows[0], dict) else {"path": rows[0][0], "title": rows[0][1]}

                    page_path = row.get("path") or row.get("page_path", "")

                    if not page_path:
                        continue

                    # Increment version
                    version_q = (
                        "MATCH (wp:WikiPage {uid: $uid, repository: $repo}) "
                        "SET wp.version = COALESCE(wp.version, 1) + 1 "
                        "RETURN wp.version AS v"
                    )
                    await self._store.execute_query(
                        version_q, {"uid": page_uid, "repo": repository},
                    )
                    pages_regenerated += 1

                except Exception as exc:
                    log.warning("incremental_page_failed", page_uid=page_uid, error=str(exc))
                    errors.append(page_uid)

            if pages_regenerated > 0:
                await self._run_compilation_snapshot("default", repository)

            return {
                "pages_regenerated": pages_regenerated,
                "pages_total": len(affected.page_uids),
                "trigger": affected.trigger,
                "errors": errors,
            }
        except Exception as exc:
            log.warning(
                "incremental_generation_failed_fallback_to_full",
                repository=repository,
                error=str(exc),
            )
            try:
                await self.generate(
                    repository,
                    "repo",
                    "structure",
                    "json",
                    language=language,
                    token_budget_multiplier=token_budget_multiplier,
                )
                return {
                    "pages_regenerated": -1,
                    "pages_total": len(affected.page_uids),
                    "trigger": affected.trigger,
                    "fallback": True,
                }
            except Exception as full_exc:
                log.error("full_generation_fallback_also_failed", error=str(full_exc))
                return {
                    "pages_regenerated": 0,
                    "pages_total": len(affected.page_uids),
                    "trigger": affected.trigger,
                    "fallback": True,
                    "error": str(full_exc),
                }

    async def generate_stream_events(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
        llm_provider: str | None = None,
        token_budget_multiplier: float = 1.0,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``{"page": page_dict}`` per page, then ``{"complete": export_bundle}``."""
        # NOTE: generate_stream_events uses legacy recursive walk for streaming.
        # Phase 2 features (parent aggregation, business flows, backlinks, navigation)
        # are only available through the non-streaming _compose_all_pages path.
        # Aligning streaming with the two-pass architecture is planned for a future phase.
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        _importance_tiers: dict[str, ImportanceTier] = {}
        app_cfg = self._wiki_cfg
        if app_cfg.code_budget_enabled and self._wiki_store is not None:
            from wiki.importance_scorer import ImportanceScorer

            scorer = ImportanceScorer(
                self._wiki_store,
                core_percentile=app_cfg.importance_core_percentile,
                standard_percentile=app_cfg.importance_standard_percentile,
            )
            _importance_tiers = await scorer.score_all(repository)
            log.info(
                "importance_scoring_complete",
                repository=repository,
                entities=len(_importance_tiers),
            )
        structure = await self._planner.plan(
            repository,
            scope,
            importance_tiers=_importance_tiers or None,
        )
        community_markdown = ""
        if self._community_service and getattr(
            self._wiki_cfg, "community_context_enabled", True,
        ):
            try:
                cr = await self._community_service.get_cached(repository)
                community_markdown = format_communities_markdown(cr)
            except Exception:  # noqa: BLE001 — optional context: never fail wiki generation
                log.warning("community_context_failed", repository=repository, exc_info=True)
        composer = self._composer_for(llm_provider)
        wikilink_cache = WikiLinkCache()
        stream_cache_active = False
        if getattr(self._wiki_cfg, "wikilink_cache_enabled", True) and composer._wiki_store:
            try:
                loaded = await wikilink_cache.warm_up(composer._wiki_store, repository)
                log.info("wikilink_cache_warm_up", repository=repository, loaded=loaded)
                composer._wikilink_cache = wikilink_cache
                stream_cache_active = True
            except Exception:
                log.warning(
                    "wikilink_cache_warm_up_failed",
                    repository=repository,
                    exc_info=True,
                )
        _stream_sk_light_raw = str(
            getattr(self._wiki_cfg, "skeleton_light_model", "") or "",
        ).strip()
        stream_skeleton_light_model = _stream_sk_light_raw if _stream_sk_light_raw else None
        if self._deferred_enrichment:
            enriched = await self._deferred_enrichment.enrich_remaining(repository)
            log.info(
                "deferred_enrichment_complete",
                repository=repository,
                enriched_count=enriched,
            )
        if self._flow_inferencer:
            flows_created = await self._generate_business_flows(repository)
            log.info("business_flows_generated", repository=repository, count=flows_created)

        pages: list[WikiPage] = []
        degraded = False
        page_tier_map: dict[str, ImportanceTier] = {}

        async def walk_stream(
            node: WikiStructureNode, parent_ctx: str = "",
        ) -> AsyncIterator[WikiPage]:
            if node.page_type == PageType.REPO_OVERVIEW:
                page = self._make_repo_overview_page(
                    repository, structure, config, community_markdown=community_markdown,
                )
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                yield page
                for ch in node.children:
                    async for p in walk_stream(ch, parent_ctx):
                        yield p
                return
            graph_node = await self._resolve_structure_node(repository, node)
            tier = _importance_tiers.get(graph_node.uid)
            code_budget = self._budget_for_tier(
                tier, multiplier=token_budget_multiplier,
            )
            page_data = await self._collector.collect(repository, graph_node, code_budget=code_budget)
            if tier is not None:
                page_data.importance_tier = tier
            skeleton_strat = None
            if tier == ImportanceTier.SKELETON:
                raw = getattr(self._wiki_cfg, "skeleton_strategy", "template")
                try:
                    skeleton_strat = SkeletonStrategy(raw)
                except ValueError:
                    skeleton_strat = SkeletonStrategy.TEMPLATE
            page = await composer.compose_page(
                page_data,
                node.page_type,
                config,
                parent_context=parent_ctx,
                importance_tier=tier,
                skeleton_strategy=skeleton_strat,
                skeleton_light_model=stream_skeleton_light_model,
            )
            if page is None:
                for ch in node.children:
                    async for p in walk_stream(ch, parent_ctx):
                        yield p
                return
            if stream_cache_active:
                wikilink_cache.register(page.title, page.path)
            page.metadata.enrichment_level = EnrichmentLevel.BASE
            if tier is not None:
                page_tier_map[page.path] = tier
            yield page
            for ch in node.children:
                async for p in walk_stream(ch, parent_ctx):
                    yield p

        async for page in walk_stream(structure.root):
            pages.append(page)
            if config.mode == "full" and page.metadata.fallback_tier == 3:
                degraded = True
            yield {"page": page.to_dict()}

        await self._enrich_pages_after_compose(pages, page_tier_map, config, llm_provider)
        await self._persist_pages_to_graph(
            repository, pages, language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
        await self._sync_graph_references_into_page_content(
            repository,
            pages,
            language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
        await self._run_compilation_snapshot("default", repository)
        for page in pages:
            if page.page_type == PageType.REPO_OVERVIEW:
                continue
            yield {
                "enrichment": {
                    "page_path": page.path,
                    "level": _enrichment_level_for_api(page.metadata.enrichment_level),
                }
            }

        if self._deferred_enrichment:
            refreshed = await self._deferred_enrichment.refresh_stale_embeddings(repository)
            log.info(
                "embedding_refresh_complete",
                repository=repository,
                refreshed=refreshed,
            )

        bundle = self._export_service.bundle_generation_result(
            pages,
            structure,
            export_format="json",
            degraded=degraded,
        )
        yield {"complete": bundle}

    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        mode: str = "full",
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Generate cross-repo business-level wiki.

        1. List all indexed repositories
        2. Collect all modules from each repo
        3. Run LangGraph pipeline (entity classification, domain classification,
           page composition, quality gate, overview synthesis, link resolution)
        4. Create WikiSpace + WikiSection tree
        5. Persist pages and build cross-references
        """
        app_cfg = self._wiki_cfg

        if self._wiki_store is None:
            raise WikiScopeError("WikiStore required for business-level wiki generation")

        repos = await self._wiki_store.list_indexed_repositories()
        if not repos:
            return {
                "business_id": business_id,
                "domains": [],
                "pages_count": 0,
                "references_count": 0,
                "repositories": [],
                "partial_errors": [],
                "skipped_repos": [],
            }

        all_modules: dict[str, list[GraphNode]] = {}
        for r in repos:
            repo_name = r["repository"]
            modules = await self._graph.list_repository_modules(repo_name)
            if modules:
                all_modules[repo_name] = modules

        # --- Incremental: identify changed vs skipped repos ---
        changed_repos: set[str] = set(all_modules.keys())
        skipped_repos: list[str] = []
        if incremental and hasattr(self._wiki_store, "get_repo_wiki_freshness"):
            try:
                freshness = await self._wiki_store.get_repo_wiki_freshness(business_id)
                changed_repos = set()
                for repo_name in all_modules:
                    entry = freshness.get(repo_name)
                    if entry is None:
                        changed_repos.add(repo_name)
                        continue
                    li = entry.get("last_indexed")
                    lg = entry.get("last_generated")
                    if li is None or lg is None or str(li) > str(lg):
                        changed_repos.add(repo_name)
                    else:
                        skipped_repos.append(repo_name)
            except Exception:
                log.warning("freshness_check_failed", exc_info=True)
                changed_repos = set(all_modules.keys())
                skipped_repos = []

        # --- Domain-level incremental: detect affected domains ---
        existing_domain_tree: list | None = None
        affected_domain_names: list[str] | None = None

        if incremental and hasattr(self._wiki_store, "get_pipeline_domain_tree_snapshot"):
            try:
                snapshot = await self._wiki_store.get_pipeline_domain_tree_snapshot(
                    business_id,
                )
                if isinstance(snapshot, dict):
                    existing_domain_tree = snapshot.get("tree")
                else:
                    existing_domain_tree = None
            except Exception:
                log.warning("load_existing_domain_tree_failed", business_id=business_id, exc_info=True)

            try:
                domain_diff = await compute_domain_diff(
                    self._store, business_id, list(all_modules.keys()),
                )
                if domain_diff.is_empty:
                    log.info("wiki_no_domain_changes", business_id=business_id)
                else:
                    affected_domain_names = domain_diff.affected_domains
                    log.info(
                        "wiki_domain_diff",
                        business_id=business_id,
                        affected_domains=affected_domain_names,
                        changed_modules=domain_diff.total_changed,
                    )
            except Exception:
                log.warning("compute_domain_diff_failed", business_id=business_id, exc_info=True)

        total_repos = len(all_modules)
        if progress_callback:
            await progress_callback({
                "completed_repos": 0,
                "total_repos": total_repos,
                "current_repo": "",
                "phase": "classifying_domains",
            })

        llm_port = self._resolve_llm_port(llm_provider)

        from wiki.pipeline_orchestrator import run_langgraph_pipeline

        pipeline_result = await run_langgraph_pipeline(
            business_id=business_id,
            repositories=list(all_modules.keys()),
            all_modules=all_modules,
            llm=llm_port,
            existing_domain_tree=existing_domain_tree,
            is_incremental=incremental and (
                bool(skipped_repos)
                or bool(affected_domain_names)
                or (existing_domain_tree is not None and len(existing_domain_tree) > 0)
            ),
            affected_domains=affected_domain_names,
            graph_store=self._store,
            wiki_store=self._wiki_store,
            progress_callback=progress_callback,
            config_overrides={"language": language},
        )

        if progress_callback:
            await progress_callback({
                "completed_repos": 0,
                "total_repos": total_repos,
                "current_repo": "",
                "phase": "persisting_pages",
            })
        domain_mapping = pipeline_result.domain_mapping
        domain_tree = pipeline_result.domain_tree
        all_pages: list[WikiPage] = list(pipeline_result.pages)

        from wiki.dependency_graph import ModuleDependencyGraph

        all_entry_point_pairs: set[tuple[str, str]] = set()
        for repo_name, _repo_modules in all_modules.items():
            try:
                dep_graph = ModuleDependencyGraph(self._graph)
                module_graph = await dep_graph.build(repo_name)
                for ep in module_graph.entry_points:
                    all_entry_point_pairs.add((repo_name, ep))
            except Exception:
                log.warning("entry_point_collection_failed", repository=repo_name, exc_info=True)

        entry_points_by_repo: dict[str, list[str]] = {}
        for ep_repo, ep_name in all_entry_point_pairs:
            entry_points_by_repo.setdefault(ep_repo, []).append(ep_name)

        log.info(
            "domain_classification_done",
            business_id=business_id,
            domains=len(domain_mapping),
            total_modules=sum(len(v) for v in domain_mapping.values()),
        )
        tree_builder = WikiTreeBuilder()
        space_uid = tree_builder.generate_space_uid(business_id)
        await self._wiki_store.upsert_wiki_space(
            business_id=business_id,
            title=f"{business_id} Knowledge Base",
            description=f"Business-level wiki for {business_id}",
        )

        domain_names: list[str] = []
        sort_idx = 1

        has_nested_tree = domain_tree is not None and len(domain_tree) > 0

        if has_nested_tree:
            from dataclasses import asdict
            try:
                tree_serializable = [asdict(node) for node in domain_tree]
                review_status = pipeline_result.review_status if hasattr(pipeline_result, "review_status") else None
                await self._wiki_store.persist_pipeline_domain_tree(
                    business_id, tree_serializable, review_status,
                )
            except Exception:
                log.warning("persist_pipeline_domain_tree_failed", business_id=business_id, exc_info=True)

        domain_display_names = pipeline_result.domain_display_names
        for domain_name, repo_module_pairs in domain_mapping.items():
            section_uid = tree_builder.generate_domain_section_uid(business_id, domain_name)
            section_title = domain_display_names.get(domain_name, domain_name)
            await self._wiki_store.upsert_wiki_section(
                uid=section_uid,
                title=section_title,
                description=f"Business domain: {section_title}",
                section_type="business_domain",
                sort_order=sort_idx,
                auto_generated=True,
            )
            if not has_nested_tree:
                await self._wiki_store.add_has_child_edge(
                    parent_uid=space_uid,
                    parent_label="WikiSpace",
                    child_uid=section_uid,
                    child_label="WikiSection",
                    view_type="business_domain",
                    sort_order=sort_idx,
                )
            sort_idx += 1
            domain_names.append(domain_name)

        # Persist business_domain to graph nodes (Module + descendants)
        for domain_name, repo_module_pairs in domain_mapping.items():
            for repo, mod_name in repo_module_pairs:
                mod_nodes = [
                    m for m in all_modules.get(repo, [])
                    if m.properties.get("name") == mod_name
                ]
                if not mod_nodes:
                    continue
                mod_node = mod_nodes[0]
                try:
                    await self._graph.update_node_property(
                        mod_node.label,
                        mod_node.uid,
                        "business_domain",
                        domain_name,
                    )
                    descendants = await self._graph.find_descendants(
                        mod_node.uid, edge_type="CONTAINS", max_depth=3,
                    )
                    for child_uid in descendants:
                        try:
                            await self._graph.update_node_property(
                                NodeLabel.CLASS, child_uid, "business_domain", domain_name,
                            )
                        except Exception:
                            try:
                                await self._graph.update_node_property(
                                    NodeLabel.FUNCTION, child_uid, "business_domain", domain_name,
                                )
                            except Exception:
                                log.debug(
                                    "business_domain_function_update_failed",
                                    child_uid=child_uid,
                                    domain=domain_name,
                                    exc_info=True,
                                )
                except Exception:
                    log.warning(
                        "domain_persist_failed",
                        module=mod_name,
                        domain=domain_name,
                        exc_info=True,
                    )

        # Build code_structure view (repo-level sections)
        code_sort_idx = 0
        for repo_name in sorted(all_modules.keys()):
            repo_section_uid = tree_builder.generate_repo_section_uid(business_id, repo_name)
            await self._wiki_store.upsert_wiki_section(
                uid=repo_section_uid,
                title=repo_name,
                description=f"Repository: {repo_name}",
                section_type="code_module",
                sort_order=code_sort_idx,
                auto_generated=True,
            )
            await self._wiki_store.add_has_child_edge(
                parent_uid=space_uid,
                parent_label="WikiSpace",
                child_uid=repo_section_uid,
                child_label="WikiSection",
                view_type="code_structure",
                sort_order=code_sort_idx,
            )
            code_sort_idx += 1

        log.info(
            "domain_overviews_composed",
            business_id=business_id,
            overview_pages=len(all_pages),
            domains=len(domain_names),
        )

        if all_pages:
            await self._persist_pages_to_graph(business_id, all_pages, language=language)

            current_paths = [p.path for p in all_pages]
            if affected_domain_names:
                deleted = await self._persistence.cleanup_stale_wiki_pages_by_domain(
                    business_id,
                    current_paths,
                    affected_domain_names,
                )
            else:
                deleted = await self._persistence.cleanup_stale_wiki_pages(
                    business_id,
                    current_paths,
                )
            if deleted > 0:
                log.info(
                    "stale_domain_pages_cleaned",
                    business_id=business_id,
                    deleted=deleted,
                    incremental=incremental,
                )

            for repo_name in all_modules:
                try:
                    await self._bulk_set_wiki_code_hashes(repo_name)
                except Exception:
                    log.warning(
                        "business_wiki_hash_sync_failed",
                        repository=repo_name,
                        exc_info=True,
                    )

        await self._persist_resolved_pipeline_wikilinks(
            business_id, all_pages, pipeline_result.resolved_links,
        )

        partial_errors: list[dict[str, str]] = []
        total_repos = len(all_modules)
        completed_repos = 0

        # Determine which repos need per-repo wiki generation.
        repos_needing_generation: set[str] = set()
        if not app_cfg.business_wiki_skip_repo_pages:
            repos_needing_generation = set(all_modules.keys())

        if repos_needing_generation:
            gen_total = len(repos_needing_generation)
            log.info("per_repo_generation_starting", business_id=business_id, repo_count=gen_total)
            if progress_callback:
                await progress_callback({
                    "completed_repos": 0,
                    "total_repos": gen_total,
                    "current_repo": "",
                    "phase": "generating_pages",
                })

            sem = asyncio.Semaphore(max(1, int(app_cfg.business_repo_concurrency)))
            progress_lock = asyncio.Lock()

            async def run_one_repo(repo_name: str, repo_index: int) -> None:
                nonlocal completed_repos
                if repo_name not in changed_repos:
                    async with progress_lock:
                        completed_repos += 1
                        done_count = completed_repos
                    if progress_callback:
                        await progress_callback({
                            "completed_repos": done_count,
                            "total_repos": gen_total,
                            "current_repo": repo_name,
                            "phase": "generating_pages",
                            "skipped": True,
                        })
                    return

                async with sem:
                    try:
                        log.info(
                            "repo_wiki_generate_start",
                            repository=repo_name,
                            index=repo_index,
                            total=gen_total,
                            mode=mode,
                        )
                        await self.generate(
                            repo_name,
                            "repo",
                            mode,
                            "json",
                            language,
                            llm_provider,
                            token_budget_multiplier=token_budget_multiplier,
                            progress_callback=progress_callback,
                        )
                        log.info("repo_wiki_generate_done", repository=repo_name)
                    except Exception as exc:
                        log.warning(
                            "business_wiki_repo_failed",
                            repository=repo_name,
                            error=str(exc)[:200],
                            exc_info=True,
                        )
                        async with progress_lock:
                            partial_errors.append({"repository": repo_name, "error": str(exc)})

                async with progress_lock:
                    completed_repos += 1
                    done_count = completed_repos
                if progress_callback:
                    await progress_callback({
                        "completed_repos": done_count,
                        "total_repos": gen_total,
                        "current_repo": repo_name,
                        "phase": "generating_pages",
                        "skipped": False,
                    })

            await asyncio.gather(*(
                run_one_repo(repo_name, idx)
                for idx, repo_name in enumerate(repos_needing_generation, start=1)
            ))
        else:
            log.info(
                "per_repo_generation_skipped",
                business_id=business_id,
                reason="no repos need generation (skip_repo_pages=True, no new repos)",
            )

        all_section_names = list(domain_names)
        if domain_tree:
            def _flatten_tree_paths(nodes: list[DomainNode], prefix: str = "") -> list[str]:
                paths: list[str] = []
                for n in nodes:
                    p = f"{prefix}/{n.name}" if prefix else n.name
                    paths.append(p)
                    paths.extend(_flatten_tree_paths(n.children, p))
                return paths
            all_section_names.extend(_flatten_tree_paths(domain_tree))
            all_section_names.append("__root__")

        await self._persistence.cleanup_stale_domain_edges(
            business_id, all_section_names,
        )
        await self._persistence.cleanup_stale_domain_sections(
            business_id, all_section_names,
        )

        await self._link_pages_to_tree(
            business_id, domain_mapping, list(all_modules.keys()), tree_builder,
            skip_business_domain=has_nested_tree,
        )

        if domain_tree:
            try:
                pages_result = await self._wiki_store.get_wiki_pages_for_business(business_id)
                if not pages_result:
                    pages_result = await self._wiki_store.get_wiki_pages_for_business("default")
                pages_by_entity: dict[str, dict[str, Any]] = {}
                for page in pages_result:
                    entity_uid = page.get("entity_uid", "")
                    title = page.get("title", "")
                    uid = page.get("uid", "")
                    if entity_uid:
                        pages_by_entity[str(entity_uid)] = page
                    if title:
                        pages_by_entity[str(title)] = page
                    if uid:
                        pages_by_entity[str(uid)] = page
                await self._link_pages_to_nested_tree(
                    business_id, domain_tree, pages_by_entity, tree_builder,
                    language=language,
                )
            except Exception:
                log.warning(
                    "link_nested_tree_failed",
                    business_id=business_id,
                    exc_info=True,
                )

        # Build cross-page references (RELATED_TO edges)
        # Scope: Only modules that are part of domain_mapping (have assigned domains).
        # Class/Function entities inherit reachability through graph proximity.
        from wiki.related_pages_builder import RelatedPagesBuilder

        domain_module_uids: set[str] = set()
        for _domain, repo_mod_pairs in domain_mapping.items():
            for repo, mod_name in repo_mod_pairs:
                for m in all_modules.get(repo, []):
                    if m.properties.get("name") == mod_name:
                        domain_module_uids.add(m.uid)
                        break

        related_builder = RelatedPagesBuilder(self._graph)
        log.info(
            "related_pages_build_start",
            business_id=business_id,
            module_count=len(domain_module_uids),
        )
        for repo_name, repo_modules in all_modules.items():
            for mod in repo_modules:
                if mod.uid not in domain_module_uids:
                    continue
                mod_domain = mod.properties.get("business_domain")
                try:
                    await related_builder.build_and_persist(
                        entity_uid=mod.uid,
                        business_domain=mod_domain,
                    )
                except Exception:
                    log.warning("related_pages_build_failed", uid=mod.uid, exc_info=True)

        ref_count = 0
        try:
            from wiki.reference_generator import WikiReferenceGenerator

            ref_gen = WikiReferenceGenerator(self._wiki_store)
            ref_count = await ref_gen.generate()
        except Exception:
            log.warning(
                "business_wiki_reference_generation_failed",
                business_id=business_id,
                exc_info=True,
            )

        return {
            "business_id": business_id,
            "domains": domain_names,
            "pages_count": len(all_pages),
            "references_count": ref_count,
            "repositories": [r["repository"] for r in repos],
            "partial_errors": partial_errors,
            "skipped_repos": skipped_repos,
        }

    async def _link_pages_to_tree(self, *args: Any, **kwargs: Any) -> None:
        return await self._tree_linker.link_pages_to_tree(*args, **kwargs)

    async def _link_pages_to_nested_tree(self, *args: Any, **kwargs: Any) -> None:
        return await self._tree_linker.link_pages_to_nested_tree(*args, **kwargs)

    @staticmethod
    def _count_domain_modules(domain: DomainNode) -> int:
        return WikiTreeLinker.count_domain_modules(domain)

    def _budget_for_tier(self, tier: ImportanceTier | None, *, multiplier: float = 1.0) -> int:
        """Return the token budget for a given importance tier from app config."""
        return self._page_composer.budget_for_tier(tier, multiplier=multiplier)

    async def _enrich_pages_after_compose(self, *args: Any, **kwargs: Any) -> None:
        return await self._get_enrichment().enrich_pages_after_compose(*args, **kwargs)

    def _resolve_skeleton_strategy(self, tier: ImportanceTier | None) -> SkeletonStrategy | None:
        return self._page_composer.resolve_skeleton_strategy(tier)

    async def _compose_all_pages(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
        composer: WikiComposer,
        importance_tiers: dict[str, ImportanceTier] | None = None,
        llm_provider: str | None = None,
        *,
        community_markdown: str = "",
        token_budget_multiplier: float = 1.0,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> tuple[list[WikiPage], bool]:
        return await self._page_composer.compose_all_pages(
            repository,
            structure,
            config,
            composer,
            importance_tiers,
            llm_provider,
            community_markdown=community_markdown,
            token_budget_multiplier=token_budget_multiplier,
            progress_callback=progress_callback,
        )

    async def _resolve_structure_node(self, repository: str, node: WikiStructureNode) -> GraphNode:
        return await self._page_composer.resolve_structure_node(repository, node)

    def _make_repo_overview_page(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
        community_markdown: str = "",
    ) -> WikiPage:
        return self._page_composer.make_repo_overview_page(
            repository, structure, config, community_markdown=community_markdown,
        )

    async def _persist_pages_to_graph(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str = "en",
        skip_claim_tracking: bool = False,
    ) -> None:
        return await self._persistence.persist_pages_to_graph(
            repository, pages, language=language, skip_claim_tracking=skip_claim_tracking
        )

    @staticmethod
    def _business_wikipage_uid(business_id: str, path: str) -> str:
        """Canonical WikiPage node uid (matches ``persist_wiki_pages`` / ``WikiPagePersistence``)."""
        return f"WikiPage:{business_id}:{path}"

    async def _persist_resolved_pipeline_wikilinks(
        self,
        business_id: str,
        pages: list[WikiPage],
        resolved_links: dict[str, list[dict[str, str]]] | None,
    ) -> None:
        """Persist ``[[wikilink]]`` edges from LangGraph ``resolved_links`` into ``WIKI_REFERENCES``."""
        if self._wiki_store is None or not resolved_links or not pages:
            return
        add_edge = getattr(self._wiki_store, "add_wiki_reference_edge", None)
        if add_edge is None:
            return

        path_to_uid = {p.path: self._business_wikipage_uid(business_id, p.path) for p in pages}

        wikilink_count = 0
        for source_path, links in resolved_links.items():
            source_uid = path_to_uid.get(source_path)
            if not source_uid:
                continue
            if not isinstance(links, list):
                continue
            for link in links:
                if not isinstance(link, dict):
                    continue
                target_path = str(link.get("target_path") or "").strip()
                if not target_path:
                    continue
                target_uid = path_to_uid.get(target_path)
                if not target_uid:
                    continue
                try:
                    await add_edge(
                        source_uid=source_uid,
                        target_uid=target_uid,
                        relation_type="wikilink",
                        context=str(link.get("from_text") or ""),
                        auto_generated=True,
                    )
                    wikilink_count += 1
                except Exception:
                    log.debug(
                        "wikilink_edge_failed",
                        source=source_path,
                        target=target_path,
                        exc_info=True,
                    )

        log.info(
            "wikilinks_persisted",
            count=wikilink_count,
            business_id=business_id,
        )

    async def get_enrichment_status(self, repository: str) -> dict[str, Any]:
        """Return enrichment level distribution for wiki pages."""
        await self._ensure_repo(repository)
        return await self._get_enrichment().get_enrichment_status(
            repository,
            verify_repository=False,
        )

    async def trigger_enrichment(self, repository: str) -> dict[str, Any]:
        """Trigger enrichment for eligible wiki pages.

        Counts pages at BASE enrichment level and starts a background
        enrichment task if eligible pages exist.
        """
        await self._ensure_repo(repository)
        return await self._get_enrichment().trigger_enrichment(
            repository,
            verify_repository=False,
        )

    async def _execute_wiki_cypher(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Run Cypher against the wiki graph store (``.query`` or ``.execute_query``)."""
        p = params or {}
        graph = self._graph
        q = getattr(graph, "query", None)
        if callable(q):
            return await q(cypher, params=p)
        return await graph.execute_query(cypher, p)

    async def set_page_review_status(self, page_uid: str, status: str, notes: str) -> dict[str, Any]:
        """Set ``review_status`` / ``review_notes`` on a :WikiPage node."""
        if status not in _VALID_WIKI_REVIEW_STATUSES:
            raise ValueError("Invalid review status")
        cypher = (
            "MATCH (p:WikiPage {uid: $page_uid}) "
            "SET p.review_status = $status, p.review_notes = $notes, "
            "p.review_updated_at = timestamp() "
            "RETURN p.uid AS uid"
        )
        result = await self._execute_wiki_cypher(
            cypher,
            {"page_uid": page_uid, "status": status, "notes": notes},
        )
        rows = _graph_query_positional_rows(result)
        if not rows:
            raise ValueError(f"WikiPage uid={page_uid} not found")
        return {"status": status, "page_uid": page_uid, "notes": notes}

    async def trigger_page_regeneration(self, page_uid: str, heal_hints: str = "") -> dict[str, Any]:
        """Queue async regeneration of one wiki page via :class:`WikiPageAgent`."""
        cypher = (
            "MATCH (p:WikiPage {uid: $page_uid}) "
            "OPTIONAL MATCH (p)-[:BELONGS_TO]->(d:Domain) "
            "RETURN d.name AS domain, p.repository AS repository, p.title AS title, p.uid AS uid"
        )
        graph = self._store if self._store is not None else self._graph
        result = await graph.execute_query(cypher, {"page_uid": page_uid})
        rows = getattr(result, "data", []) or []
        if not rows or not isinstance(rows[0], dict):
            raise ValueError(f"WikiPage uid={page_uid} not found")
        row = rows[0]
        domain = row.get("domain")
        repository = row.get("repository")
        title = row.get("title")

        task_id = f"regen-{page_uid}-{int(time.time())}"

        async def _run_regeneration() -> None:
            try:
                graph_store = self._store if self._store is not None else self._graph
                from wiki.page_agent import WikiPageAgent

                agent = WikiPageAgent(self._llm, graph_store)
                hints = heal_hints.strip() if heal_hints else None
                module_names = [title] if (title or "").strip() else [page_uid]
                domain_name = (domain or "default") if domain else "default"
                new_content = await agent.generate(
                    module_names,
                    domain_name,
                    baseline_context=hints,
                )
                if new_content and self._wiki_store is not None:
                    await self._wiki_store.update_wiki_page_content(
                        page_uid,
                        new_content,
                        source="system-regeneration",
                        edit_reason=heal_hints or "",
                    )
            except Exception:
                log.exception("page_regeneration_failed", page_uid=page_uid)

        if self._task_supervisor is not None:
            self._task_supervisor.spawn(
                lambda: _run_regeneration(),
                name=f"regen-{page_uid}",
            )
        else:
            asyncio.create_task(_run_regeneration())

        return {"task_id": task_id, "page_uid": page_uid, "status": "accepted"}

    async def _run_enrichment_background(self, *args: Any, **kwargs: Any) -> None:
        return await self._get_enrichment().run_enrichment_background(*args, **kwargs)
