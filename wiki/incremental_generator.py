"""Incremental wiki updates for a single repository."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from core.config import AppWikiFlags as WikiAppConfig
from core.log import get_logger
from store.schema import EdgeType, GraphNode, NodeLabel
from store.wiki_store import WikiStore
from wiki.composer import WikiComposer
from wiki.data_collector import WikiDataCollector
from wiki.incremental_diff import compute_wiki_diff
from wiki.models import EnrichmentLevel, ImportanceTier, PageType, SkeletonStrategy, WikiConfig, WikiPage
from wiki.page_composer_service import WikiPageComposerService
from wiki.persistence import WikiPagePersistence
from wiki.protocols import WikiGraphStorePort
from wiki.token_budget import TokenBudgetResolver

log = get_logger(__name__)


class IncrementalWikiGenerator:
    """Handles incremental wiki updates for a single repository."""

    def __init__(
        self,
        *,
        store: WikiGraphStorePort | None,
        graph: Any,
        wiki_cfg: WikiAppConfig,
        wiki_store: WikiStore | None,
        persistence: WikiPagePersistence,
        collector: WikiDataCollector,
        page_composer: WikiPageComposerService,
        budget_resolver: TokenBudgetResolver,
        composer_factory: Callable[[str | None], WikiComposer],
        config_for: Callable[[str, str, str, str], WikiConfig],
        ensure_repo: Callable[[str], Awaitable[None]],
        persist_pages: Callable[..., Awaitable[None]],
    ) -> None:
        self._store = store
        self._graph = graph
        self._wiki_cfg = wiki_cfg
        self._wiki_store = wiki_store
        self._persistence = persistence
        self._collector = collector
        self._page_composer = page_composer
        self._budget_resolver = budget_resolver
        self._composer_factory = composer_factory
        self._config_for = config_for
        self._ensure_repo = ensure_repo
        self._persist_pages = persist_pages

    @staticmethod
    def sort_by_depth(
        uids: list[str],
        contains_edges: list[dict[str, str]],
    ) -> list[str]:
        """Sort uids by graph depth — leaves first, roots last."""
        return WikiPageComposerService.sort_by_depth(uids, contains_edges)

    async def update_wiki_code_hashes(self, repository: str, uids: list[str]) -> None:
        """After successful wiki page generation, set wiki_code_hash = code_hash."""
        return await self._persistence.update_wiki_code_hashes(repository, uids)

    def resume_source_content_hash(self, graph_node: GraphNode, source_content: str) -> str:
        """Prefer graph ``code_hash`` (matches incremental ``wiki_code_hash``); fallback to hashed sources."""
        return self._page_composer.resume_source_content_hash(graph_node, source_content)

    async def load_wikipage_for_resume_entity(
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

    def _budget_for_tier(self, tier: ImportanceTier | None, *, multiplier: float = 1.0) -> int:
        return self._page_composer.budget_for_tier(tier, multiplier=multiplier)

    def _resolve_skeleton_strategy(self, tier: ImportanceTier | None) -> SkeletonStrategy | None:
        return self._page_composer.resolve_skeleton_strategy(tier)

    async def generate(
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
            composer = self._composer_factory(llm_provider)

            graph_nodes_by_uid: dict[str, GraphNode] = {}
            batch_find = getattr(self._graph, "find_nodes_by_uids", None)
            if batch_find is not None:
                try:
                    graph_nodes_by_uid = await batch_find(
                        repository,
                        list(all_affected_uids),
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
                    mod_names = list(
                        {n.properties.get("name", "") for n in graph_nodes_by_uid.values() if n.properties.get("name")}
                    )
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

            sorted_uids = self.sort_by_depth(list(all_affected_uids), contains_edges)
            just_generated: dict[str, WikiPage] = {}
            parent_pages_by_entity: dict[str, Any] = {}
            if composer._wiki_store is not None and contains_edges:
                parent_uids = {str(e.get("source", "")) for e in contains_edges if e.get("source")}
                batch_parent_fn = getattr(
                    composer._wiki_store,
                    "get_pages_by_entity_uids",
                    None,
                )
                if batch_parent_fn is not None and parent_uids:
                    try:
                        parent_pages_by_entity = await batch_parent_fn(
                            repository,
                            list(parent_uids),
                        )
                    except Exception:
                        log.debug("incremental_parent_pages_batch_failed", exc_info=True)

            for uid in sorted_uids:
                try:
                    graph_node = graph_nodes_by_uid.get(uid)
                    if graph_node is None:
                        continue
                    page_type = (
                        PageType.MODULE_OVERVIEW if graph_node.label == NodeLabel.MODULE else PageType.CLASS_DETAIL
                    )
                    tier = _importance_tiers.get(graph_node.uid)
                    code_budget = self._budget_for_tier(
                        tier,
                        multiplier=token_budget_multiplier,
                    )
                    page_data = await self._collector.collect(
                        repository,
                        graph_node,
                        code_budget=code_budget,
                    )
                    if tier is not None:
                        page_data.importance_tier = tier
                    skeleton_strat = self._resolve_skeleton_strategy(tier)
                    parent_context = ""
                    parent_edges = [
                        e for e in page_data.edges if e.edge_type == EdgeType.CONTAINS and e.target_uid == uid
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
                                        repository,
                                        parent_uid,
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
                await self._persist_pages(
                    repository,
                    regenerated_pages,
                    language=language,
                )
                await self.update_wiki_code_hashes(repository, updated_uids)
                current_version = last_version + 1
                await wiki_meta.set_wiki_generation_version(repository, current_version)
            else:
                current_version = last_version

            if progress_callback:
                await progress_callback(
                    {
                        "phase": "incremental_complete",
                        "pages_regenerated": len(regenerated_pages),
                        "version": current_version,
                    }
                )

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
