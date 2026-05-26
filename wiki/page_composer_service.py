"""Wiki page composition: two-pass compose, backlinks, progressive persist."""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from core.log import get_logger
from store.schema import GraphNode, NodeLabel
from wiki.backlink_builder import BacklinkBuilder
from wiki.composer import WikiComposer
from wiki.delegation import evaluate_delegation, group_children_by_graph
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
)
from wiki.structure_planner import WikiScopeError
from wiki.wikilink_cache import WikiLinkCache

if TYPE_CHECKING:
    from wiki.enrichment_coordinator import WikiEnrichmentCoordinator

log = get_logger(__name__)


class WikiPageComposerService:
    """Composes wiki pages from structure nodes using a two-pass strategy."""

    def __init__(
        self,
        graph: Any,
        collector: Any,
        wiki_store: Any | None,
        wiki_cfg: Any,
        store: Any | None,
        budget_resolver: Any,
        llm: Any | None,
        persistence: Any,
        enrichment: WikiEnrichmentCoordinator,
        composer_factory: Callable[[str | None], WikiComposer],
        llm_resolver: Callable[[str | None], Any],
        memory_loop: Any | None = None,
        community_service: Any | None = None,
    ) -> None:
        self._graph = graph
        self._collector = collector
        self._wiki_store = wiki_store
        self._wiki_cfg = wiki_cfg
        self._store = store
        self._budget_resolver = budget_resolver
        self._llm = llm
        self._persistence = persistence
        self._enrichment = enrichment
        self._composer_for = composer_factory
        self._resolve_llm_port = llm_resolver
        self._memory_loop = memory_loop
        self._community_service = community_service

    @staticmethod
    def sort_by_depth(
        uids: list[str],
        contains_edges: list[dict[str, str]],
    ) -> list[str]:
        """Sort uids by graph depth — leaves first, roots last."""

        children: dict[str, set[str]] = {}
        for edge in contains_edges:
            src = str(edge.get("source", "") or "")
            tgt = str(edge.get("target", "") or "")
            children.setdefault(src, set()).add(tgt)

        uid_set = set(uids)

        def depth(uid: str, visited: set[str] | None = None) -> int:
            if visited is None:
                visited = set()
            if uid in visited:
                return 0
            visited.add(uid)
            kids = children.get(uid, set()) & uid_set
            if not kids:
                return 0
            return 1 + max(depth(k, visited) for k in kids)

        return sorted(uids, key=lambda u: depth(u))

    def resume_source_content_hash(self, graph_node: GraphNode, source_content: str) -> str:
        """Prefer graph ``code_hash`` (matches incremental ``wiki_code_hash``); fallback to hashed sources."""
        props = graph_node.properties or {}
        ch = props.get("code_hash")
        if isinstance(ch, str) and ch.strip():
            return ch.strip()
        return hashlib.sha256(source_content.encode()).hexdigest()

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
        if self._wiki_store is None:
            return None
        if not hasattr(self._wiki_store, "execute_query"):
            return None
        try:
            from store.schema import EdgeType

            _se = EdgeType.SOURCE_ENTITY.value
            q = (
                f"MATCH (wp:WikiPage {{repository: $repo}})-[:{_se}]->(e {{uid: $uid}}) "
                "RETURN coalesce(wp.path, '') AS path, coalesce(wp.title, '') AS title, "
                "coalesce(wp.content, '') AS content, coalesce(wp.page_type, '') AS pt LIMIT 1"
            )
            r = await self._wiki_store.execute_query(
                q, {"repo": repository, "uid": graph_node.uid},
            )
            rows = getattr(r, "data", []) or []
            if not rows or not isinstance(rows[0], dict):
                return None
            row = rows[0]
            pt_raw = str(row.get("pt") or structure_page_type.value)
            try:
                pt = PageType(pt_raw)
            except ValueError:
                pt = structure_page_type
            return WikiPage(
                path=str(row.get("path") or structure_path),
                title=str(row.get("title") or structure_title),
                page_type=pt,
                content=str(row.get("content") or ""),
                diagrams=[],
                source_locations=[],
                metadata=WikiPageMetadata(
                    node_count=0,
                    edge_count=0,
                    generation_mode=config.mode,
                    fallback_tier=None,
                ),
                method_locations=[],
            )
        except Exception:
            log.debug("resume_load_wikipage_failed", uid=graph_node.uid, exc_info=True)
            return None

    def budget_for_tier(self, tier: ImportanceTier | None, *, multiplier: float = 1.0) -> int:
        """Return the token budget for a given importance tier from app config."""
        app_cfg = self._wiki_cfg
        if tier == ImportanceTier.CORE:
            base = app_cfg.core_code_budget
        elif tier == ImportanceTier.STANDARD:
            base = app_cfg.standard_code_budget
        elif tier == ImportanceTier.SKELETON:
            base = app_cfg.skeleton_code_budget
        else:
            base = app_cfg.standard_code_budget
        return int(base * multiplier)

    def resolve_skeleton_strategy(self, tier: ImportanceTier | None) -> SkeletonStrategy | None:
        if tier != ImportanceTier.SKELETON:
            return None
        raw = getattr(self._wiki_cfg, "skeleton_strategy", "template")
        try:
            return SkeletonStrategy(raw)
        except ValueError:
            return SkeletonStrategy.TEMPLATE

    async def compose_all_pages(
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
        import time as _time

        from wiki.helpers import (
            _build_lightweight_glossary,
            _build_lightweight_parent_context,
            _collect_nodes_by_depth,
            _expected_wiki_page_paths_dfs,
            _extract_summary,
            _populate_navigation_context,
        )

        pages: list[WikiPage] = []
        degraded = False
        tiers = importance_tiers or {}
        page_tier_map: dict[str, ImportanceTier] = {}
        summary_index: dict[str, WikiPageSummary] = {}
        _t0 = _time.monotonic()
        _PAGE_TIMEOUT = 120

        wikilink_cache = WikiLinkCache()
        cache_active = False
        if getattr(self._wiki_cfg, "wikilink_cache_enabled", True) and composer._wiki_store:
            try:
                loaded = await wikilink_cache.warm_up(composer._wiki_store, repository)
                log.info("wikilink_cache_warm_up", repository=repository, loaded=loaded)
                composer._wikilink_cache = wikilink_cache
                cache_active = True
            except Exception:
                log.warning(
                    "wikilink_cache_warm_up_failed",
                    repository=repository,
                    exc_info=True,
                )

        leaves, parents_by_depth = _collect_nodes_by_depth(structure.root)
        _total_nodes = len(leaves) + len(parents_by_depth)
        log.info(
            "compose_all_pages_start",
            repository=repository,
            total_nodes=_total_nodes,
            leaves=len(leaves),
            parents=len(parents_by_depth),
        )

        sem_limit = max(1, int(getattr(self._wiki_cfg, "compose_concurrency", 3)))
        sem = asyncio.Semaphore(sem_limit)

        _sk_light_raw = str(getattr(self._wiki_cfg, "skeleton_light_model", "") or "").strip()
        skeleton_light_model = _sk_light_raw if _sk_light_raw else None

        resume_enabled = getattr(self._wiki_cfg, "resume_from_saved", False)
        existing_page_hashes: dict[str, str] = {}
        if resume_enabled and self._store is not None and hasattr(self._store, "execute_query"):
            try:
                rhq = (
                    "MATCH (wp:WikiPage {repository: $repo})-[:SOURCE_ENTITY]->(e) "
                    "RETURN coalesce(wp.path, '') AS path, coalesce(e.wiki_code_hash, '') AS wiki_h"
                )
                rhres = await self._store.execute_query(rhq, {"repo": repository})
                for row in getattr(rhres, "data", None) or []:
                    if isinstance(row, dict):
                        pth = str(row.get("path") or "")
                        wh = str(row.get("wiki_h") or "")
                        if pth and wh:
                            existing_page_hashes[pth] = wh
            except Exception:
                log.debug("resume_hash_preload_failed", repository=repository, exc_info=True)

        log.info(
            "compose_phase_start",
            repository=repository,
            phase="leaf_compose",
            count=len(leaves),
        )
        if progress_callback:
            await progress_callback(
                {
                    "repository": repository,
                    "phase": "wiki_compose",
                    "subphase": "leaf_compose",
                    "status": "started",
                    "total_leaves": len(leaves),
                    "total_parents": len(parents_by_depth),
                },
            )

        # Build lightweight glossary from graph entities
        _glossary: dict[str, str] = {}
        if self._store is not None:
            try:
                _gq = (
                    "MATCH (n {repository: $repo}) "
                    "WHERE n.business_summary IS NOT NULL AND n.business_summary <> '' "
                    "AND n.name IS NOT NULL AND n.name <> '' "
                    "RETURN n.name, n.business_summary ORDER BY n.name LIMIT 500"
                )
                _gres = await self._store.execute_query(_gq, {"repo": repository})
                _glossary_nodes: list[GraphNode] = []
                for row in getattr(_gres, "raw", []) or []:
                    _glossary_nodes.append(
                        GraphNode(
                            label=NodeLabel.MODULE,
                            properties={
                                "name": str(row[0] or ""),
                                "business_summary": str(row[1] or ""),
                            },
                            uid="",
                        )
                    )
                _glossary = _build_lightweight_glossary(_glossary_nodes)
            except Exception:
                log.debug("glossary_build_failed", repository=repository, exc_info=True)

        # Build leaf → parent structure node map for parent context
        _parent_struct_map: dict[str, WikiStructureNode] = {}

        def _map_parents(node: WikiStructureNode) -> None:
            for child in node.children:
                if child.is_leaf:
                    _parent_struct_map[child.path] = node
                _map_parents(child)

        _map_parents(structure.root)

        # Pre-resolve parent graph nodes
        _parent_graph_cache: dict[str, GraphNode | None] = {}
        _unique_parents = {id(n): n for n in _parent_struct_map.values()}.values()
        for _pnode in _unique_parents:
            try:
                _pg = await self.resolve_structure_node(repository, _pnode)
                _parent_graph_cache[_pnode.path] = _pg
            except Exception:
                _parent_graph_cache[_pnode.path] = None

        async def compose_leaf(node: WikiStructureNode) -> WikiPage | None:
            nonlocal degraded
            async with sem:
                try:
                    graph_node = await asyncio.wait_for(
                        self.resolve_structure_node(repository, node),
                        timeout=30,
                    )
                except TimeoutError:
                    log.warning("resolve_leaf_timeout", path=node.path)
                    return None
                except Exception:
                    log.warning("resolve_leaf_error", path=node.path, exc_info=True)
                    return None
                tier = tiers.get(graph_node.uid)
                code_budget = self.budget_for_tier(
                    tier, multiplier=token_budget_multiplier,
                )
                try:
                    page_data = await asyncio.wait_for(
                        self._collector.collect(repository, graph_node, code_budget=code_budget),
                        timeout=60,
                    )
                except TimeoutError:
                    log.warning("collector_leaf_timeout", path=node.path)
                    return None
                if tier is not None:
                    page_data.importance_tier = tier
                skeleton_strat = self.resolve_skeleton_strategy(tier)

                src_concat = "".join(cs.source for cs in page_data.code_snippets)
                page_res: WikiPage | None = None
                if resume_enabled and existing_page_hashes and composer._wiki_store is not None:
                    ex_h = existing_page_hashes.get(node.path)
                    cur_h = self.resume_source_content_hash(graph_node, src_concat)
                    if ex_h and cur_h and ex_h == cur_h:
                        log.debug("resume_skip_unchanged", path=node.path)
                        page_res = await self.load_wikipage_for_resume_entity(
                            repository,
                            graph_node,
                            structure_path=node.path,
                            structure_title=node.title,
                            structure_page_type=node.page_type,
                            config=config,
                        )
                page: WikiPage | None = page_res
                if page is None:
                    _biz_domain = graph_node.properties.get("business_domain")
                    _is_entry = bool(
                        set(graph_node.properties.get("semantic_roles", []) or [])
                        & {"http_controller", "rpc_provider", "message_listener", "scheduled_task"}
                    )
                    _parent_sn = _parent_struct_map.get(node.path)
                    _parent_gn = (
                        _parent_graph_cache.get(_parent_sn.path) if _parent_sn else None
                    )
                    _parent_ctx = _build_lightweight_parent_context(_parent_gn)
                    try:
                        page = await asyncio.wait_for(
                            composer.compose_page(
                                page_data,
                                node.page_type,
                                config,
                                parent_context=_parent_ctx,
                                glossary=_glossary,
                                importance_tier=tier,
                                skeleton_strategy=skeleton_strat,
                                skeleton_light_model=skeleton_light_model,
                                business_domain=_biz_domain,
                                is_entry_point=_is_entry,
                            ),
                            timeout=_PAGE_TIMEOUT,
                        )
                    except TimeoutError:
                        log.warning("compose_leaf_timeout", path=node.path)
                        return None
                if page is None:
                    return None
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                page._source_entity_uid = graph_node.uid  # type: ignore[attr-defined]
                page._structure_path = node.path  # type: ignore[attr-defined]
                if tier is not None:
                    page_tier_map[page.path] = tier
                if config.mode == "full" and page.metadata.fallback_tier == 3:
                    degraded = True
                if cache_active:
                    wikilink_cache.register(page.title, page.path)
                return page

        batch_size = int(getattr(self._wiki_cfg, "progressive_persist_batch_size", 20))
        progressive = getattr(self._wiki_cfg, "progressive_persist_enabled", True)

        for batch_start in range(0, len(leaves), batch_size):
            batch = leaves[batch_start : batch_start + batch_size]
            leaf_results = await asyncio.gather(*(compose_leaf(n) for n in batch))

            batch_pages: list[WikiPage] = []
            for page in leaf_results:
                if page is not None:
                    pages.append(page)
                    batch_pages.append(page)
                    uid = getattr(page, "_source_entity_uid", "")
                    struct_path = getattr(page, "_structure_path", page.path)
                    _sum = _extract_summary(page, entity_uid=uid)
                    summary_index[struct_path] = _sum
                    if page.path != struct_path:
                        summary_index[page.path] = _sum

            if progressive and batch_pages and self._store is not None:
                try:
                    await self._persistence.persist_pages_to_graph(
                        repository,
                        batch_pages,
                        language=config.language,
                        skip_claim_tracking=(config.mode == "structure"),
                    )
                    log.info(
                        "progressive_persist_leaf_batch",
                        repository=repository,
                        batch_start=batch_start,
                        batch_saved=len(batch_pages),
                    )
                except Exception:
                    log.warning(
                        "progressive_persist_leaf_failed",
                        repository=repository,
                        batch_start=batch_start,
                        exc_info=True,
                    )

        log.info(
            "compose_phase_complete",
            repository=repository,
            phase="leaf_compose",
            pages_composed=len(pages),
            elapsed_s=round(_time.monotonic() - _t0, 1),
        )
        if progress_callback:
            await progress_callback(
                {
                    "repository": repository,
                    "phase": "wiki_compose",
                    "subphase": "leaf_compose",
                    "status": "complete",
                    "pages": len(pages),
                },
            )

        log.info(
            "compose_phase_start",
            repository=repository,
            phase="parent_aggregate",
            count=len(parents_by_depth),
        )
        if progress_callback:
            await progress_callback(
                {
                    "repository": repository,
                    "phase": "wiki_compose",
                    "subphase": "parent_aggregate",
                    "status": "started",
                    "total_parents": len(parents_by_depth),
                },
            )

        progressive_parents = getattr(self._wiki_cfg, "progressive_persist_enabled", True)
        prev_depth: int | None = None
        depth_batch: list[WikiPage] = []

        for _depth, parent_node in parents_by_depth:
            if (
                progressive_parents
                and prev_depth is not None
                and _depth != prev_depth
                and depth_batch
                and self._store is not None
            ):
                try:
                    await self._persistence.persist_pages_to_graph(
                        repository,
                        depth_batch,
                        language=config.language,
                        skip_claim_tracking=(config.mode == "structure"),
                    )
                    log.info(
                        "progressive_persist_parent_depth",
                        repository=repository,
                        completed_depth=prev_depth,
                        batch_saved=len(depth_batch),
                    )
                except Exception:
                    log.warning(
                        "progressive_persist_parent_depth_failed",
                        repository=repository,
                        completed_depth=prev_depth,
                        exc_info=True,
                    )
                depth_batch.clear()

            try:
                if parent_node.page_type == PageType.REPO_OVERVIEW:
                    page = self.make_repo_overview_page(
                        repository, structure, config, community_markdown=community_markdown,
                    )
                    page.metadata.enrichment_level = EnrichmentLevel.BASE
                    page._structure_path = parent_node.path  # type: ignore[attr-defined]
                    pages.append(page)
                    if progressive_parents:
                        depth_batch.append(page)
                    continue
                try:
                    graph_node = await asyncio.wait_for(
                        self.resolve_structure_node(repository, parent_node),
                        timeout=30,
                    )
                except TimeoutError:
                    log.warning("resolve_parent_timeout", path=parent_node.path)
                    continue
                except Exception:
                    log.warning("resolve_parent_error", path=parent_node.path, exc_info=True)
                    continue
                tier = tiers.get(graph_node.uid)
                code_budget = self.budget_for_tier(
                    tier, multiplier=token_budget_multiplier,
                )
                try:
                    page_data = await asyncio.wait_for(
                        self._collector.collect(repository, graph_node, code_budget=code_budget),
                        timeout=60,
                    )
                except TimeoutError:
                    log.warning("collector_parent_timeout", path=parent_node.path)
                    continue
                if tier is not None:
                    page_data.importance_tier = tier

                resume_src_concat = "".join(cs.source for cs in page_data.code_snippets)
                page_early: WikiPage | None = None
                if resume_enabled and existing_page_hashes and composer._wiki_store is not None:
                    rex = existing_page_hashes.get(parent_node.path)
                    rcur = self.resume_source_content_hash(graph_node, resume_src_concat)
                    if rex and rcur and rex == rcur:
                        log.debug("resume_skip_unchanged", path=parent_node.path)
                        page_early = await self.load_wikipage_for_resume_entity(
                            repository,
                            graph_node,
                            structure_path=parent_node.path,
                            structure_title=parent_node.title,
                            structure_page_type=parent_node.page_type,
                            config=config,
                        )

                child_summaries = [
                    summary_index[ch.path] for ch in parent_node.children if ch.path in summary_index
                ]
                edges: list[tuple[str, str]] = []

                page: WikiPage | None = page_early
                if page is None:
                    if getattr(self._wiki_cfg, "delegation_enabled", True):
                        decision = evaluate_delegation(
                            children_count=len(parent_node.children),
                            total_code_lines=0,  # code lines not tracked on structure nodes
                            max_children=getattr(self._wiki_cfg, "delegation_max_children", 30),
                            max_code_lines=getattr(self._wiki_cfg, "delegation_max_code_lines", 5000),
                        )
                        if decision.should_delegate and child_summaries:
                            child_paths = [
                                ch.path for ch in parent_node.children if ch.path in summary_index
                            ]
                            edges = []
                            if (
                                child_paths
                                and self._store is not None
                                and callable(getattr(self._store, "find_edges_between", None))
                            ):
                                try:
                                    edges = await self._store.find_edges_between(
                                        repository,
                                        child_paths,
                                        edge_types=["CALLS", "IMPORTS"],
                                    )
                                except Exception:
                                    log.warning(
                                        "delegation_edge_query_failed",
                                        path=parent_node.path,
                                        exc_info=True,
                                    )
                                    edges = []
                            groups = group_children_by_graph(
                                [ch for ch in parent_node.children if ch.path in summary_index],
                                edges,
                                max_group_size=getattr(self._wiki_cfg, "delegation_max_children", 30),
                            )
                            if len(groups) > 1:
                                group_summaries: list[WikiPageSummary] = []
                                for group in groups:
                                    group_child_sums = [
                                        summary_index[ch.path]
                                        for ch in group
                                        if ch.path in summary_index
                                    ]
                                    if group_child_sums:
                                        combined = "; ".join(s.summary[:50] for s in group_child_sums)
                                        group_summaries.append(
                                            WikiPageSummary(
                                                entity_uid=f"virtual:{parent_node.path}:{len(group_summaries)}",
                                                title=f"Group: {group_child_sums[0].title} etc.",
                                                path=parent_node.path,
                                                summary=combined[:200],
                                                importance_tier=None,
                                                page_type=PageType.MODULE_OVERVIEW,
                                            )
                                        )
                                if group_summaries:
                                    child_summaries = group_summaries
                                    log.info(
                                        "delegation_applied",
                                        path=parent_node.path,
                                        groups=len(groups),
                                        reason=decision.reason,
                                    )
                    skeleton_strat = self.resolve_skeleton_strategy(tier)
                    if tier == ImportanceTier.SKELETON and skeleton_strat == SkeletonStrategy.SKIP:
                        continue
                    try:
                        if child_summaries:
                            inter_child_edges_dicts = (
                                [
                                    {"source": s, "edge_type": "CALLS", "target": t}
                                    for s, t in edges
                                ]
                                if edges
                                else None
                            )
                            page = await asyncio.wait_for(
                                composer.compose_parent_page(
                                    page_data,
                                    parent_node.page_type,
                                    config,
                                    child_summaries,
                                    inter_child_edges=inter_child_edges_dicts,
                                ),
                                timeout=_PAGE_TIMEOUT,
                            )
                        else:
                            skeleton_strat = self.resolve_skeleton_strategy(tier)
                            page = await asyncio.wait_for(
                                composer.compose_page(
                                    page_data,
                                    parent_node.page_type,
                                    config,
                                    importance_tier=tier,
                                    skeleton_strategy=skeleton_strat,
                                    skeleton_light_model=skeleton_light_model,
                                ),
                                timeout=_PAGE_TIMEOUT,
                            )
                    except TimeoutError:
                        log.warning("compose_parent_timeout", path=parent_node.path)
                        continue
                if page is None:
                    continue
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                page._source_entity_uid = graph_node.uid  # type: ignore[attr-defined]
                page._structure_path = parent_node.path  # type: ignore[attr-defined]
                if tier is not None:
                    page_tier_map[page.path] = tier
                if config.mode == "full" and page.metadata.fallback_tier == 3:
                    degraded = True
                pages.append(page)
                _psum = _extract_summary(page, entity_uid=graph_node.uid)
                summary_index[parent_node.path] = _psum
                if page.path != parent_node.path:
                    summary_index[page.path] = _psum
                if cache_active:
                    wikilink_cache.register(page.title, page.path)
                if progressive_parents:
                    depth_batch.append(page)
            finally:
                prev_depth = _depth

        if (
            progressive_parents
            and depth_batch
            and self._store is not None
        ):
            try:
                await self._persistence.persist_pages_to_graph(
                    repository,
                    depth_batch,
                    language=config.language,
                    skip_claim_tracking=(config.mode == "structure"),
                )
                log.info(
                    "progressive_persist_parent_depth",
                    repository=repository,
                    completed_depth=prev_depth,
                    batch_saved=len(depth_batch),
                )
            except Exception:
                log.warning(
                    "progressive_persist_parent_depth_failed",
                    repository=repository,
                    completed_depth=prev_depth,
                    exc_info=True,
                )

        log.info(
            "compose_phase_complete",
            repository=repository,
            phase="parent_aggregate",
            pages_composed=len(pages),
            elapsed_s=round(_time.monotonic() - _t0, 1),
        )
        if progress_callback:
            await progress_callback(
                {
                    "repository": repository,
                    "phase": "wiki_compose",
                    "subphase": "parent_aggregate",
                    "status": "complete",
                    "pages": len(pages),
                },
            )

        if getattr(self._wiki_cfg, "business_flow_aggregation_enabled", True):
            try:
                from wiki.business_flow_composer import BusinessFlowPageComposer

                community_svc = self._community_service
                llm_bridge = self._resolve_llm_port(llm_provider)
                if community_svc:
                    flow_composer = BusinessFlowPageComposer(llm_bridge, community_svc)
                    uid_to_path: dict[str, str] = {}
                    for page in pages:
                        uid = getattr(page, "_source_entity_uid", "")
                        if uid:
                            uid_to_path[uid] = page.path
                    min_size = getattr(self._wiki_cfg, "business_flow_min_community_size", 3)
                    flow_pages = await flow_composer.compose_flows(
                        repository,
                        summary_index,
                        uid_to_path,
                        config,
                        min_community_size=min_size,
                    )
                    pages.extend(flow_pages)
                    log.info(
                        "business_flow_phase_complete",
                        repository=repository,
                        flow_pages=len(flow_pages),
                    )
                else:
                    log.warning(
                        "business_flow_phase_skipped",
                        repository=repository,
                        reason="community_service_unavailable",
                    )
            except Exception:
                log.warning(
                    "business_flow_phase_failed",
                    repository=repository,
                    exc_info=True,
                )

        path_order = {p: i for i, p in enumerate(_expected_wiki_page_paths_dfs(structure.root))}
        pages.sort(
            key=lambda pg: path_order.get(getattr(pg, "_structure_path", pg.path), 1 << 30),
        )

        pages_by_struct_path = {getattr(p, "_structure_path", p.path): p for p in pages}
        _populate_navigation_context(structure.root, pages_by_struct_path)

        backlink_builder = BacklinkBuilder()
        try:
            await backlink_builder.build_backlinks(pages, self._graph, wikilink_cache, repository)
        except Exception:
            log.warning("backlink_building_failed", repository=repository, exc_info=True)

        _elapsed = _time.monotonic() - _t0
        log.info(
            "compose_all_pages_done",
            repository=repository,
            pages_composed=len(pages),
            total_time_s=round(_elapsed, 1),
        )
        if progress_callback:
            await progress_callback(
                {
                    "repository": repository,
                    "phase": "wiki_compose",
                    "subphase": "navigation",
                    "status": "complete",
                    "pages": len(pages),
                },
            )
        await self._enrichment.enrich_pages_after_compose(pages, page_tier_map, config, llm_provider)
        return pages, degraded

    async def resolve_structure_node(self, repository: str, node: WikiStructureNode) -> GraphNode:
        if node.page_type == PageType.MODULE_OVERVIEW:
            g = await self._graph.find_node_by_path(repository, node.path)
        else:
            g = await self._graph.find_node_by_fqn(repository, node.path)
            if g is None:
                g = await self._graph.find_node_by_path(repository, node.path)
        if g is None:
            raise WikiScopeError(f"No graph node for wiki path {node.path!r} in repository {repository!r}")
        return g

    def make_repo_overview_page(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
        community_markdown: str = "",
    ) -> WikiPage:
        lines = [
            f"# {structure.repository}",
            "",
            "Repository overview generated from the knowledge graph.",
            "",
            f"- Planned wiki pages: {structure.total_pages}",
        ]
        content = "\n".join(lines)
        if community_markdown.strip():
            content = f"{content}\n\n{community_markdown.rstrip()}\n"
        return WikiPage(
            path="README.md",
            title=structure.repository,
            page_type=PageType.REPO_OVERVIEW,
            content=content,
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(
                node_count=0,
                edge_count=0,
                generation_mode=config.mode,
                fallback_tier=None,
            ),
        )
