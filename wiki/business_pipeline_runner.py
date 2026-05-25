"""LangGraph-based business wiki generation pipeline."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from core.config import AppWikiFlags as WikiAppConfig
from core.config import EmbeddingConfig
from core.log import get_logger
from llm.provider_factory import LLMProviderFactory
from store.schema import GraphNode, NodeLabel
from store.wiki_store import WikiStore
from wiki.community_context import CachedCommunityService
from wiki.dependency_graph import DomainNode
from wiki.flow_writer import BusinessFlowWriter
from wiki.llm_port import LLMPort
from wiki.memory_loop import MemoryLoop
from wiki.models import WikiPage
from wiki.persistence import WikiPagePersistence
from wiki.protocols import WikiGraphStorePort
from wiki.structure_planner import WikiScopeError
from wiki.token_budget import TokenBudgetResolver
from wiki.tree_builder import WikiTreeBuilder
from wiki.tree_linker import WikiTreeLinker

log = get_logger(__name__)


class BusinessPipelineRunner:
    """Runs the LangGraph-based business wiki generation pipeline."""

    def __init__(
        self,
        *,
        store: WikiGraphStorePort | None,
        graph: Any,
        wiki_cfg: WikiAppConfig,
        wiki_store: WikiStore | None,
        persistence: WikiPagePersistence,
        llm_factory: LLMProviderFactory | None,
        embedding_cfg: EmbeddingConfig,
        budget_resolver: TokenBudgetResolver,
        flow_writer: BusinessFlowWriter,
        tree_linker: WikiTreeLinker,
        memory_loop: MemoryLoop | None,
        community_service: CachedCommunityService | None,
        llm_resolver: Callable[[str | None], LLMPort | None],
        redis_conn: Any | None,
        task_supervisor: Any | None,
        repo_generator: Callable[..., Awaitable[dict[str, Any]]],
        persist_pages: Callable[..., Awaitable[None]],
        bulk_set_wiki_code_hashes: Callable[[str], Awaitable[None]],
        persist_resolved_wikilinks: Callable[..., Awaitable[None]],
    ) -> None:
        self._store = store
        self._graph = graph
        self._wiki_cfg = wiki_cfg
        self._wiki_store = wiki_store
        self._persistence = persistence
        self._llm_factory = llm_factory
        self._embedding_cfg = embedding_cfg
        self._budget_resolver = budget_resolver
        self._flow_writer = flow_writer
        self._tree_linker = tree_linker
        self._memory_loop = memory_loop
        self._community_service = community_service
        self._llm_resolver = llm_resolver
        self._redis = redis_conn
        self._task_supervisor = task_supervisor
        self._repo_generator = repo_generator
        self._persist_pages = persist_pages
        self._bulk_set_wiki_code_hashes = bulk_set_wiki_code_hashes
        self._persist_resolved_wikilinks = persist_resolved_wikilinks

    @staticmethod
    def business_wikipage_uid(business_id: str, path: str) -> str:
        """Canonical WikiPage node uid (matches ``persist_wiki_pages`` / ``WikiPagePersistence``)."""
        return f"WikiPage:{business_id}:{path}"

    @staticmethod
    def _flatten_tree_paths(nodes: list[DomainNode], prefix: str = "") -> list[str]:
        paths: list[str] = []
        for n in nodes:
            p = f"{prefix}/{n.name}" if prefix else n.name
            paths.append(p)
            paths.extend(BusinessPipelineRunner._flatten_tree_paths(n.children, p))
        return paths

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

        path_to_uid = {p.path: self.business_wikipage_uid(business_id, p.path) for p in pages}

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

    async def run(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        mode: str = "full",
        force_full_run: bool = False,
        config_overrides: dict[str, Any] | None = None,
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
    ) -> dict[str, Any]:
        """Generate cross-repo business-level wiki."""
        app_cfg = self._wiki_cfg
        incremental = incremental and app_cfg.incremental_enabled

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
                log.error("freshness_check_failed", exc_info=True)
                changed_repos = set(all_modules.keys())
                skipped_repos = []

        # Business wikis store pages with repository=business_id, so the per-repo
        # freshness join (Module.repository vs WikiPage.repository) can't match.
        # Fall back to a business-level check when per-repo yields all-changed.
        business_level_no_changes = False
        if incremental and changed_repos == set(all_modules.keys()) and all_modules:
            try:
                result = await self._store.execute_query(
                    "MATCH (m:Module) WHERE m.repository IS NOT NULL "
                    "WITH max(coalesce(m.indexed_at, '')) AS max_indexed "
                    "OPTIONAL MATCH (wp:WikiPage {repository: $biz_id}) "
                    "WITH max_indexed, max(coalesce(wp.generated_at, '')) AS max_generated "
                    "RETURN "
                    "CASE WHEN max_indexed = '' THEN null ELSE max_indexed END AS max_indexed, "
                    "CASE WHEN max_generated = '' THEN null ELSE max_generated END AS max_generated",
                    {"biz_id": business_id},
                )
                rows = getattr(result, "data", None) or []
                if rows and isinstance(rows[0], dict):
                    max_idx = rows[0].get("max_indexed")
                    max_gen = rows[0].get("max_generated")
                    if max_idx and max_gen and str(max_gen) >= str(max_idx):
                        business_level_no_changes = True
                        log.info(
                            "business_freshness_no_changes",
                            business_id=business_id,
                            max_indexed=max_idx,
                            max_generated=max_gen,
                        )
                    else:
                        log.info(
                            "business_freshness_has_changes",
                            business_id=business_id,
                            max_indexed=max_idx,
                            max_generated=max_gen,
                        )
            except Exception:
                log.warning("business_freshness_check_failed", exc_info=True)

        # --- Domain-level incremental: detect affected domains ---
        existing_domain_tree: list | None = None
        affected_domain_names: list[str] | None = None
        affected_module_names: list[str] = []
        existing_domain_mapping: dict[str, list[tuple[str, str]]] = {}

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
                from wiki.incremental_diff import compute_domain_diff

                domain_diff = await compute_domain_diff(
                    self._store,
                    business_id,
                    list(all_modules.keys()),
                )
                if domain_diff.is_empty:
                    log.info("wiki_no_domain_changes", business_id=business_id)
                else:
                    affected_domain_names = domain_diff.affected_domains
                    uid_to_compound: dict[str, str] = {}
                    for repo, mod_list in all_modules.items():
                        for mod in mod_list:
                            mod_name = str(mod.properties.get("name", "") or "")
                            if mod.uid and mod_name:
                                uid_to_compound[mod.uid] = f"{repo}|{mod_name}"
                    affected_module_names = [
                        uid_to_compound[uid] for uid in domain_diff.changed_module_uids if uid in uid_to_compound
                    ]
                    log.info(
                        "wiki_domain_diff",
                        business_id=business_id,
                        affected_domains=affected_domain_names,
                        changed_modules=domain_diff.total_changed,
                    )
            except Exception:
                log.warning("compute_domain_diff_failed", business_id=business_id, exc_info=True)

        pinned_modules: dict[str, str] = {}
        if incremental:
            try:
                pinned_raw = await self._persistence.list_pinned_modules(business_id) or []
                pinned_modules = {
                    str(p["module_name"]): str(p["domain_slug"])
                    for p in pinned_raw
                    if p.get("module_name") and p.get("domain_slug")
                }
            except Exception:
                log.warning("pinned_modules_load_failed", business_id=business_id, exc_info=True)

        if existing_domain_tree:
            from wiki.pipeline_orchestrator import domain_tree_to_mapping

            existing_domain_mapping = domain_tree_to_mapping(existing_domain_tree, all_modules)

        no_content_changes = (
            incremental and affected_domain_names is None and (not changed_repos or business_level_no_changes)
        )
        log.info(
            "no_content_changes_eval",
            incremental=incremental,
            affected_domain_names=affected_domain_names,
            changed_repos_count=len(changed_repos),
            business_level_no_changes=business_level_no_changes,
            no_content_changes=no_content_changes,
        )

        total_repos = len(all_modules)
        if progress_callback:
            await progress_callback(
                {
                    "completed_repos": 0,
                    "total_repos": total_repos,
                    "current_repo": "",
                    "phase": "classifying_domains",
                }
            )

        llm_port = self._llm_resolver(llm_provider)

        from wiki.llm_rate_limiter import create_llm_rate_limiter
        from wiki.pipeline_orchestrator import (
            load_cached_pipeline_result,
            load_existing_module_summaries,
            run_langgraph_pipeline,
        )

        existing_summaries = await load_existing_module_summaries(business_id, all_modules)

        llm_rate_limiter = create_llm_rate_limiter(
            rpm_limit=app_cfg.llm_global_rpm_limit,
            tpm_limit=app_cfg.llm_global_tpm_limit,
        )

        if no_content_changes and not force_full_run:
            log.info(
                "no_content_changes_skip_pipeline",
                business_id=business_id,
                message="No content changes detected, skipping pipeline",
            )
            pipeline_result = await load_cached_pipeline_result(
                business_id,
                all_modules,
                wiki_store=self._wiki_store,
                existing_domain_tree=existing_domain_tree,
                existing_domain_mapping=existing_domain_mapping or None,
            )
        else:
            pipeline_result = await run_langgraph_pipeline(
                business_id=business_id,
                repositories=list(all_modules.keys()),
                all_modules=all_modules,
                llm=llm_port,
                existing_domain_tree=existing_domain_tree,
                existing_domain_mapping=existing_domain_mapping or None,
                existing_summaries=existing_summaries or None,
                affected_modules=affected_module_names or None,
                pinned_modules=pinned_modules or None,
                is_incremental=incremental
                and (
                    bool(skipped_repos)
                    or bool(affected_domain_names)
                    or (existing_domain_tree is not None and len(existing_domain_tree) > 0)
                ),
                affected_domains=affected_domain_names,
                graph_store=self._store,
                wiki_store=self._wiki_store,
                progress_callback=progress_callback,
                config_overrides={"language": language, **(config_overrides or {})},
                budget_resolver=self._budget_resolver,
                llm_rate_limiter=llm_rate_limiter,
            )

        if progress_callback:
            await progress_callback(
                {
                    "completed_repos": 0,
                    "total_repos": total_repos,
                    "current_repo": "",
                    "phase": "persisting_pages",
                }
            )
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
                    business_id,
                    tree_serializable,
                    review_status,
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
                mod_nodes = [m for m in all_modules.get(repo, []) if m.properties.get("name") == mod_name]
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
                        mod_node.uid,
                        edge_type="CONTAINS",
                        max_depth=3,
                    )
                    for child_uid in descendants:
                        try:
                            await self._graph.update_node_property(
                                NodeLabel.CLASS,
                                child_uid,
                                "business_domain",
                                domain_name,
                            )
                        except Exception:
                            try:
                                await self._graph.update_node_property(
                                    NodeLabel.FUNCTION,
                                    child_uid,
                                    "business_domain",
                                    domain_name,
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
            await self._persist_pages(
                business_id,
                all_pages,
                language=language,
                skip_claim_tracking=no_content_changes,
                skip_embedding=no_content_changes,
            )

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

        await self._persist_resolved_wikilinks(
            business_id,
            all_pages,
            pipeline_result.resolved_links,
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
                await progress_callback(
                    {
                        "completed_repos": 0,
                        "total_repos": gen_total,
                        "current_repo": "",
                        "phase": "generating_pages",
                    }
                )

            sem = asyncio.Semaphore(max(1, int(app_cfg.business_repo_concurrency)))
            progress_lock = asyncio.Lock()

            async def run_one_repo(repo_name: str, repo_index: int) -> None:
                nonlocal completed_repos
                if repo_name not in changed_repos:
                    async with progress_lock:
                        completed_repos += 1
                        done_count = completed_repos
                    if progress_callback:
                        await progress_callback(
                            {
                                "completed_repos": done_count,
                                "total_repos": gen_total,
                                "current_repo": repo_name,
                                "phase": "generating_pages",
                                "skipped": True,
                            }
                        )
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
                        await self._repo_generator(
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
                    await progress_callback(
                        {
                            "completed_repos": done_count,
                            "total_repos": gen_total,
                            "current_repo": repo_name,
                            "phase": "generating_pages",
                            "skipped": False,
                        }
                    )

            await asyncio.gather(
                *(run_one_repo(repo_name, idx) for idx, repo_name in enumerate(repos_needing_generation, start=1))
            )
        else:
            log.info(
                "per_repo_generation_skipped",
                business_id=business_id,
                reason="no repos need generation (skip_repo_pages=True, no new repos)",
            )

        all_section_names = list(domain_names)
        if domain_tree:
            all_section_names.extend(self._flatten_tree_paths(domain_tree))
            all_section_names.append("__root__")

        await self._persistence.cleanup_stale_domain_edges(
            business_id,
            all_section_names,
        )
        await self._persistence.cleanup_stale_domain_sections(
            business_id,
            all_section_names,
        )

        await self._tree_linker.link_pages_to_tree(
            business_id,
            domain_mapping,
            list(all_modules.keys()),
            tree_builder,
            skip_business_domain=has_nested_tree,
        )

        if domain_tree:
            try:
                repos_list = list(all_modules.keys()) + [business_id]
                pages_q = (
                    "MATCH (wp:WikiPage) "
                    "WHERE wp.repository IN $repos "
                    "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
                    "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
                    "wp.content AS content, wp.page_type AS page_type, "
                    "wp.repository AS repository, "
                    "coalesce(e.uid, '') AS entity_uid, "
                    "coalesce(wp.canonical_key, '') AS canonical_key "
                    "ORDER BY wp.path"
                )
                pages_query_result = await self._wiki_store.execute_query(
                    pages_q,
                    {"repos": repos_list},
                )
                pages_result = getattr(pages_query_result, "data", None) or []
                if not pages_result:
                    fallback_result = await self._wiki_store.execute_query(
                        pages_q,
                        {"repos": ["default"]},
                    )
                    pages_result = getattr(fallback_result, "data", None) or []
                pages_by_entity: dict[str, dict[str, Any]] = {}
                for page in pages_result:
                    row = {
                        "uid": str(page.get("uid") or ""),
                        "title": str(page.get("title") or ""),
                        "path": str(page.get("path") or ""),
                        "content": str(page.get("content") or ""),
                        "page_type": str(page.get("page_type") or ""),
                        "repository": str(page.get("repository") or ""),
                        "entity_uid": str(page.get("entity_uid") or ""),
                        "canonical_key": str(page.get("canonical_key") or ""),
                    }
                    entity_uid = row["entity_uid"]
                    title = row["title"]
                    uid = row["uid"]
                    if entity_uid:
                        pages_by_entity[entity_uid] = row
                    if title:
                        pages_by_entity[title] = row
                    if uid:
                        pages_by_entity[uid] = row
                reassembly_succeeded = bool(pipeline_result.reassembly_actions)
                await self._tree_linker.link_pages_to_nested_tree(
                    business_id,
                    domain_tree,
                    pages_by_entity,
                    tree_builder,
                    language=language,
                    reassembly_succeeded=reassembly_succeeded,
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
