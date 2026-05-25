"""Streaming wiki page generation."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from core.config import AppWikiFlags as WikiAppConfig
from core.log import get_logger
from store.wiki_store import WikiStore
from wiki.community_context import CachedCommunityService, format_communities_markdown
from wiki.composer import WikiComposer
from wiki.data_collector import WikiDataCollector
from wiki.export_service import WikiExportService
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    SkeletonStrategy,
    WikiConfig,
    WikiPage,
    WikiStructureNode,
    parse_scope,
)
from wiki.structure_planner import WikiStructurePlanner
from wiki.wikilink_cache import WikiLinkCache

log = get_logger(__name__)


def enrichment_level_for_api(level: object | None) -> str | None:
    if level is None:
        return None
    if isinstance(level, EnrichmentLevel):
        return level.value
    return str(level)


class WikiStreamGenerator:
    """Yields per-page stream events during wiki generation."""

    def __init__(
        self,
        *,
        graph: Any,
        wiki_cfg: WikiAppConfig,
        wiki_store: WikiStore | None,
        planner: WikiStructurePlanner,
        collector: WikiDataCollector,
        export_service: WikiExportService,
        community_service: CachedCommunityService | None,
        deferred_enrichment: Any | None,
        flow_inferencer: Any | None,
        composer_factory: Callable[[str | None], WikiComposer],
        config_for: Callable[[str, str, str, str], WikiConfig],
        ensure_repo: Callable[[str], Awaitable[None]],
        generate_business_flows: Callable[[str], Awaitable[int]],
        budget_for_tier: Callable[..., int],
        resolve_structure_node: Callable[[str, WikiStructureNode], Awaitable[Any]],
        make_repo_overview_page: Callable[..., WikiPage],
        enrich_pages_after_compose: Callable[..., Awaitable[None]],
        persist_pages: Callable[..., Awaitable[None]],
        sync_graph_references: Callable[..., Awaitable[None]],
        run_compilation_snapshot: Callable[[str, str], Awaitable[None]],
    ) -> None:
        self._graph = graph
        self._wiki_cfg = wiki_cfg
        self._wiki_store = wiki_store
        self._planner = planner
        self._collector = collector
        self._export_service = export_service
        self._community_service = community_service
        self._deferred_enrichment = deferred_enrichment
        self._flow_inferencer = flow_inferencer
        self._composer_factory = composer_factory
        self._config_for = config_for
        self._ensure_repo = ensure_repo
        self._generate_business_flows = generate_business_flows
        self._budget_for_tier = budget_for_tier
        self._resolve_structure_node = resolve_structure_node
        self._make_repo_overview_page = make_repo_overview_page
        self._enrich_pages_after_compose = enrich_pages_after_compose
        self._persist_pages = persist_pages
        self._sync_graph_references = sync_graph_references
        self._run_compilation_snapshot = run_compilation_snapshot

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
        composer = self._composer_factory(llm_provider)
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
        error_count = 0

        class _StreamPageError:
            __slots__ = ("path", "error")

            def __init__(self, path: str, error: str) -> None:
                self.path = path
                self.error = error

        async def walk_stream(
            node: WikiStructureNode,
            parent_ctx: str = "",
        ) -> AsyncIterator[WikiPage | _StreamPageError]:
            if node.page_type == PageType.REPO_OVERVIEW:
                page = self._make_repo_overview_page(
                    repository,
                    structure,
                    config,
                    community_markdown=community_markdown,
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
                tier,
                multiplier=token_budget_multiplier,
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
            try:
                page = await composer.compose_page(
                    page_data,
                    node.page_type,
                    config,
                    parent_context=parent_ctx,
                    importance_tier=tier,
                    skeleton_strategy=skeleton_strat,
                    skeleton_light_model=stream_skeleton_light_model,
                )
            except Exception as exc:
                log.warning(
                    "stream_compose_page_failed",
                    node_path=node.path,
                    exc_info=True,
                )
                yield _StreamPageError(node.path, str(exc)[:200])
                for ch in node.children:
                    async for p in walk_stream(ch, parent_ctx):
                        yield p
                return
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

        async for item in walk_stream(structure.root):
            if isinstance(item, _StreamPageError):
                error_count += 1
                yield {"type": "page_error", "path": item.path, "error": item.error}
                continue
            page = item
            pages.append(page)
            if config.mode == "full" and page.metadata.fallback_tier == 3:
                degraded = True
            yield {"page": page.to_dict()}

        await self._enrich_pages_after_compose(pages, page_tier_map, config, llm_provider)
        await self._persist_pages(
            repository,
            pages,
            language=language,
            skip_claim_tracking=(config.mode == "structure"),
        )
        await self._sync_graph_references(
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
                    "level": enrichment_level_for_api(page.metadata.enrichment_level),
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
        if error_count:
            bundle["error_count"] = error_count
        yield {"complete": bundle}
