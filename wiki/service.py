"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from core.config import AppWikiFlags as WikiAppConfig
from core.config import EmbeddingConfig, get_settings
from core.log import get_logger
from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from store.schema import GraphNode
from store.wiki_store import WikiStore
from wiki.business_pipeline_runner import BusinessPipelineRunner
from wiki.community_context import CachedCommunityService, format_communities_markdown
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import DataCollectorPort, WikiDataCollector
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.dependency_graph import DomainNode
from wiki.export_service import WikiExportService
from wiki.flow_writer import BusinessFlowWriter
from wiki.incremental_generator import IncrementalWikiGenerator
from wiki.llm_port import LLMPort
from wiki.memory_loop import MemoryLoop
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    SkeletonStrategy,
    WikiConfig,
    WikiPage,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)
from wiki.page_composer_service import WikiPageComposerService
from wiki.persistence import WikiPagePersistence
from wiki.protocols import WikiGraphStorePort
from wiki.stream_generator import WikiStreamGenerator
from wiki.structure_planner import WikiStructurePlanner
from wiki.token_budget import TokenBudgetResolver
from wiki.tree_linker import WikiTreeLinker

if TYPE_CHECKING:
    from indexer.business_flow_inferencer import BusinessFlowInferencer
    from wiki.change_detector import AffectedPageSet
    from wiki.enrichment_coordinator import WikiEnrichmentCoordinator

log = get_logger(__name__)

_VALID_WIKI_REVIEW_STATUSES = frozenset(
    {
        "approved",
        "needs_revision",
        "pending_review",
        "revised",
    }
)


def _graph_query_positional_rows(result: Any) -> list[list[Any]]:
    rs = getattr(result, "result_set", None)
    if isinstance(rs, list):
        return rs
    raw = getattr(result, "raw", None)
    return raw if isinstance(raw, list) else []


def _compilation_snapshot_to_page_dicts(data: dict[str, str], repository: str, layered: bool) -> list[dict[str, Any]]:
    """Map snapshot markdown blobs to the dict shape expected by ``persist_wiki_pages``."""
    ts = datetime.now(UTC).isoformat()
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
        self._background_tasks: set[asyncio.Task] = set()
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
                log.warning("snapshot_persist_pages_failed", repository=repo, exc_info=True)

        try:
            _snap_timeout = 120
            log.info("compilation_snapshot_start", repository=repository)
            await asyncio.wait_for(
                snap.generate_and_persist(business_id, repository, persist_fn=_persist_snapshot),
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
            self._wiki_cfg,
            "community_context_enabled",
            True,
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
            repository,
            pages,
            language=language,
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
                self._wiki_store if self._wiki_store is not None else (WikiStore(query_port) if query_port else None)
            )
            if wiki_meta:
                await self._bulk_set_wiki_code_hashes(repository)
                current_ver = await wiki_meta.get_wiki_generation_version(repository)
                await wiki_meta.set_wiki_generation_version(
                    repository,
                    (current_ver or 0) + 1,
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
        return IncrementalWikiGenerator.sort_by_depth(uids, contains_edges)

    def _resume_source_content_hash(self, graph_node: GraphNode, source_content: str) -> str:
        """Prefer graph ``code_hash`` (matches incremental ``wiki_code_hash``); fallback to hashed sources."""
        return self._incremental_generator().resume_source_content_hash(graph_node, source_content)

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
        return await self._incremental_generator().load_wikipage_for_resume_entity(
            repository,
            graph_node,
            structure_path=structure_path,
            structure_title=structure_title,
            structure_page_type=structure_page_type,
            config=config,
        )

    def _incremental_generator(self) -> IncrementalWikiGenerator:
        return IncrementalWikiGenerator(
            store=self._store,
            graph=self._graph,
            wiki_cfg=self._wiki_cfg,
            wiki_store=self._wiki_store,
            persistence=self._persistence,
            collector=self._collector,
            page_composer=self._page_composer,
            budget_resolver=self._budget_resolver,
            composer_factory=self._composer_for,
            config_for=self._config_for,
            ensure_repo=self._ensure_repo,
            persist_pages=self._persist_pages_to_graph,
        )

    def _business_pipeline_runner(self) -> BusinessPipelineRunner:
        return BusinessPipelineRunner(
            store=self._store,
            graph=self._graph,
            wiki_cfg=self._wiki_cfg,
            wiki_store=self._wiki_store,
            persistence=self._persistence,
            llm_factory=getattr(self, "_llm_factory", None),
            embedding_cfg=getattr(self, "_embedding_cfg", None),
            budget_resolver=self._budget_resolver,
            flow_writer=getattr(self, "_flow_writer", None),
            tree_linker=self._tree_linker,
            memory_loop=getattr(self, "_memory_loop", None),
            community_service=getattr(self, "_community_service", None),
            llm_resolver=getattr(self, "_resolve_llm_port", lambda _p: getattr(self, "_llm", None)),
            redis_conn=getattr(self, "_redis", None),
            task_supervisor=getattr(self, "_task_supervisor", None),
            repo_generator=self.generate,
            persist_pages=self._persist_pages_to_graph,
            bulk_set_wiki_code_hashes=self._bulk_set_wiki_code_hashes,
            persist_resolved_wikilinks=self._persist_resolved_pipeline_wikilinks,
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
        gen = self._incremental_generator()
        return await gen.generate(
            repository,
            config,
            llm_provider,
            progress_callback,
            language=language,
            token_budget_multiplier=token_budget_multiplier,
        )

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
                        page_q,
                        {"uid": page_uid, "repo": repository},
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
                        version_q,
                        {"uid": page_uid, "repo": repository},
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

    def _stream_generator(self) -> WikiStreamGenerator:
        return WikiStreamGenerator(
            graph=self._graph,
            wiki_cfg=self._wiki_cfg,
            wiki_store=self._wiki_store,
            planner=self._planner,
            collector=self._collector,
            export_service=self._export_service,
            community_service=getattr(self, "_community_service", None),
            deferred_enrichment=getattr(self, "_deferred_enrichment", None),
            flow_inferencer=getattr(self, "_flow_inferencer", None),
            composer_factory=self._composer_for,
            config_for=self._config_for,
            ensure_repo=self._ensure_repo,
            generate_business_flows=self._generate_business_flows,
            budget_for_tier=self._budget_for_tier,
            resolve_structure_node=self._resolve_structure_node,
            make_repo_overview_page=self._make_repo_overview_page,
            enrich_pages_after_compose=self._enrich_pages_after_compose,
            persist_pages=self._persist_pages_to_graph,
            sync_graph_references=self._sync_graph_references_into_page_content,
            run_compilation_snapshot=self._run_compilation_snapshot,
        )

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
        async for event in self._stream_generator().generate_stream_events(
            repository,
            scope_raw,
            mode,
            format,
            language=language,
            llm_provider=llm_provider,
            token_budget_multiplier=token_budget_multiplier,
        ):
            yield event

    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        mode: str = "full",
        config_overrides: dict[str, Any] | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Generate cross-repo business-level wiki."""
        runner = self._business_pipeline_runner()
        return await runner.run(
            business_id,
            language,
            llm_provider,
            token_budget_multiplier=token_budget_multiplier,
            incremental=incremental,
            mode=mode,
            config_overrides=config_overrides,
            progress_callback=progress_callback,
        )

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
            repository,
            structure,
            config,
            community_markdown=community_markdown,
        )

    async def _persist_pages_to_graph(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str = "en",
        skip_claim_tracking: bool = False,
        skip_embedding: bool = False,
    ) -> None:
        return await self._persistence.persist_pages_to_graph(
            repository,
            pages,
            language=language,
            skip_claim_tracking=skip_claim_tracking,
            skip_embedding=skip_embedding,
        )

    @staticmethod
    def _business_wikipage_uid(business_id: str, path: str) -> str:
        """Canonical WikiPage node uid (matches ``persist_wiki_pages`` / ``WikiPagePersistence``)."""
        return BusinessPipelineRunner.business_wikipage_uid(business_id, path)

    async def _persist_resolved_pipeline_wikilinks(
        self,
        business_id: str,
        pages: list[WikiPage],
        resolved_links: dict[str, list[dict[str, str]]] | None,
    ) -> None:
        """Persist ``[[wikilink]]`` edges from LangGraph ``resolved_links`` into ``WIKI_REFERENCES``."""
        await self._business_pipeline_runner()._persist_resolved_pipeline_wikilinks(
            business_id,
            pages,
            resolved_links,
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
            task = asyncio.create_task(_run_regeneration())
            self._background_tasks.add(task)
            task.add_done_callback(self._background_tasks.discard)

        return {"task_id": task_id, "page_uid": page_uid, "status": "accepted"}

    async def _run_enrichment_background(self, *args: Any, **kwargs: Any) -> None:
        return await self._get_enrichment().run_enrichment_background(*args, **kwargs)
