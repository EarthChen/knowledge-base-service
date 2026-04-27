"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from config import EmbeddingConfig, WikiConfig as WikiAppConfig
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from store.schema import GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.confidence_inputs import gather_confidence_inputs, set_wiki_page_confidence_scores
from wiki.community_context import format_communities_markdown
from wiki.confidence_scorer import confidence_scorer_from_wiki_app_config
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.context import WikiContextBuilder
from wiki.data_collector import DataCollectorPort, WikiDataCollector
from wiki.exporter import WikiExporter
from wiki.memory_loop import MemoryLoop
from wiki.models import (
    EnrichmentLevel,
    ImportanceTier,
    PageType,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)
from wiki.structure_planner import WikiScopeError, WikiStructurePlanner
from wiki.tree_builder import WikiTreeBuilder

from log import get_logger

if TYPE_CHECKING:
    from indexer.business_flow_inferencer import BusinessFlowInferencer
    from wiki.change_detector import AffectedPageSet

log = get_logger(__name__)


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


class WikiRepoNotFoundError(Exception):
    """Raised when the repository is not present in the index."""

    def __init__(self, repository: str) -> None:
        self.repository = repository
        super().__init__(repository)


class WikiService:
    """Wiki generation pipeline with injectable graph and optional LLM."""

    def __init__(
        self,
        graph: DataCollectorPort,
        llm: Any | None,
        repository_exists: Callable[[str], Awaitable[bool]],
        llm_factory: LLMProviderFactory | None = None,
        store: Any | None = None,
        deferred_enrichment: DeferredEnrichmentService | None = None,
        flow_inferencer: BusinessFlowInferencer | None = None,
        wiki_store: Any | None = None,
        memory_loop: MemoryLoop | None = None,
        community_service: Any | None = None,
        *,
        wiki_config: WikiAppConfig,
        embedding_config: EmbeddingConfig,
    ) -> None:
        self._graph = graph
        self._planner = WikiStructurePlanner(graph)
        self._wiki_store = wiki_store
        self._wiki_cfg = wiki_config
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
        self._exporter = WikiExporter()
        self._repository_exists = repository_exists
        self._store = store
        self._deferred_enrichment = deferred_enrichment
        self._flow_inferencer = flow_inferencer
        self._memory_loop = memory_loop
        self._community_service = community_service

    def _composer_for(self, llm_provider: str | None) -> WikiComposer:
        llm_port = self._resolve_llm_port(llm_provider)
        return WikiComposer(
            llm_port,
            WikiContextBuilder(llm_port),
            store=self._graph,
            wiki_store=self._wiki_store,
            memory_loop=self._memory_loop,
        )

    def _resolve_llm_port(self, llm_provider: str | None) -> Any | None:
        if self._llm_factory is not None:
            provider = self._llm_factory.get_provider(llm_provider)
            return LLMPortBridge(provider)
        return self._llm

    def _confidence_scoring_enabled(self) -> bool:
        return bool(getattr(self._wiki_cfg, "confidence_scoring_enabled", False))

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
            await snap.generate_and_persist(
                business_id, repository, persist_fn=_persist_snapshot
            )
            log.info("compilation_snapshot_built", repository=repository)
        except Exception:
            log.warning("compilation_snapshot_failed", repository=repository, exc_info=True)

    async def _ensure_repo(self, repository: str) -> None:
        if not await self._repository_exists(repository):
            raise WikiRepoNotFoundError(repository)

    async def ensure_repository(self, repository: str) -> None:
        """Raise ``WikiRepoNotFoundError`` when the repository is not indexed."""
        await self._ensure_repo(repository)

    def _config_for(
        self,
        mode: str,
        format: str,
        repository: str,
        language: str = "en",
    ) -> WikiConfig:
        return WikiConfig(repository=repository, mode=mode, format=format, language=language)

    async def _generate_business_flows(self, repository: str) -> int:
        """Infer BusinessFlow nodes from entry-point call chains."""
        if not self._flow_inferencer:
            return 0
        if not self._flow_inferencer._business_flow_enabled:
            return 0

        entry_points = await self._flow_inferencer.find_entry_points()
        created = 0
        for ep in entry_points:
            chain = await self._build_call_chain(ep)
            if not chain:
                continue
            flow = await self._flow_inferencer.infer_from_chain(chain)
            if flow:
                await self._persist_flow(flow, repository)
                created += 1
        return created

    async def _build_call_chain(self, entry_point: dict[str, Any]) -> list[dict[str, str]]:
        """Build a call chain starting from an entry point by traversing CALLS edges."""
        if self._store is None:
            return []
        uid = entry_point.get("uid", "")
        if not uid:
            return []
        q = (
            "MATCH path = (start:Function {uid: $uid})-[:CALLS*1..5]->(callee:Function) "
            "RETURN callee.uid AS uid, callee.name AS name, "
            "callee.business_summary AS business_summary, callee.file AS file "
            "ORDER BY length(path)"
        )
        result = await self._store.execute_query(q, {"uid": uid})
        raw = getattr(result, "raw", None)
        if isinstance(raw, list):
            rows = raw
        else:
            rs = getattr(result, "result_set", None)
            rows = list(rs) if isinstance(rs, (list, tuple)) else []
        chain: list[dict[str, str]] = [
            {
                "name": str(entry_point.get("name", "") or ""),
                "business_summary": str(entry_point.get("business_summary", "") or ""),
                "file": str(entry_point.get("file", "") or ""),
            }
        ]
        seen: set[str] = {uid}
        for row in rows:
            row_uid = row[0]
            if row_uid in seen:
                continue
            seen.add(str(row_uid))
            chain.append(
                {
                    "name": str(row[1] or ""),
                    "business_summary": str(row[2] or ""),
                    "file": str(row[3] or ""),
                }
            )
        return chain

    async def _persist_flow(self, flow: dict[str, Any], repository: str) -> None:
        """Persist a BusinessFlow node to the graph."""
        if self._store is None:
            return
        flow_name = flow.get("flow_name", "unnamed_flow")
        uid = f"BusinessFlow:{repository}:{flow_name}"
        q = (
            "MERGE (bf:BusinessFlow {uid: $uid}) "
            "SET bf.name = $name, bf.description = $desc, "
            "bf.category = $cat, bf.repository = $repo, "
            "bf.steps = $steps"
        )
        await self._store.execute_query(
            q,
            {
                "uid": uid,
                "name": flow_name,
                "desc": flow.get("description", ""),
                "cat": flow.get("category", ""),
                "repo": repository,
                "steps": json.dumps(flow.get("steps", []), ensure_ascii=False),
            },
        )

    async def generate(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
        llm_provider: str | None = None,
        token_budget_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)
        community_markdown = ""
        if self._community_service and getattr(
            self._wiki_cfg, "community_context_enabled", True,
        ):
            try:
                cr = await self._community_service.get_cached(repository)
                community_markdown = format_communities_markdown(cr)
            except Exception:  # noqa: BLE001 — optional context: never fail wiki generation
                log.warning("community_context_failed", repository=repository, exc_info=True)
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
        )
        await self._persist_pages_to_graph(repository, pages, language=language)
        await self._run_compilation_snapshot("default", repository)
        if self._deferred_enrichment:
            refreshed = await self._deferred_enrichment.refresh_stale_embeddings(repository)
            log.info(
                "embedding_refresh_complete",
                repository=repository,
                refreshed=refreshed,
            )

        if format == "markdown" and len(pages) == 1:
            return {
                "content": self._exporter.export_markdown_single(pages[0]),
                "format": "markdown",
                "degraded": degraded,
            }

        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        return bundle

    async def generate_incremental(
        self,
        repository: str,
        affected: AffectedPageSet,
        language: str = "en",
        token_budget_multiplier: float = 1.0,
    ) -> dict[str, Any]:
        """Regenerate only affected wiki pages. Falls back to full generate on failure."""

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
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)
        community_markdown = ""
        if self._community_service and getattr(
            self._wiki_cfg, "community_context_enabled", True,
        ):
            try:
                cr = await self._community_service.get_cached(repository)
                community_markdown = format_communities_markdown(cr)
            except Exception:  # noqa: BLE001 — optional context: never fail wiki generation
                log.warning("community_context_failed", repository=repository, exc_info=True)
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
            page = await composer.compose_page(
                page_data,
                node.page_type,
                config,
                parent_context=parent_ctx,
            )
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
        await self._persist_pages_to_graph(repository, pages, language=language)
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

        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        yield {"complete": bundle}

    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
    ) -> dict[str, Any]:
        """Generate cross-repo business-level wiki.

        1. List all indexed repositories
        2. Collect all modules from each repo
        3. Classify modules into business domains (CrossRepoBusinessDomainPlanner)
        4. Create WikiSpace + WikiSection tree
        5. Generate domain overview pages (DomainOverviewComposer)
        6. Generate cross-references (WikiReferenceGenerator)
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
            }

        all_modules: dict[str, list[GraphNode]] = {}
        for r in repos:
            repo_name = r["repository"]
            modules = await self._graph.list_repository_modules(repo_name)
            if modules:
                all_modules[repo_name] = modules

        from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

        llm_port = self._resolve_llm_port(llm_provider)
        planner = CrossRepoBusinessDomainPlanner(
            llm_port,
            infrastructure_label=app_cfg.business_domain_infrastructure_label,
            batch_threshold=app_cfg.business_wiki_batch_threshold,
        )
        domain_mapping = await planner.classify(business_id, all_modules)

        tree_builder = WikiTreeBuilder()
        space_uid = tree_builder.generate_space_uid(business_id)
        await self._wiki_store.upsert_wiki_space(
            business_id=business_id,
            title=f"{business_id} Knowledge Base",
            description=f"Business-level wiki for {business_id}",
        )

        domain_names: list[str] = []
        all_pages: list[WikiPage] = []
        sort_idx = 0

        for domain_name, repo_module_pairs in domain_mapping.items():
            section_uid = tree_builder.generate_domain_section_uid(business_id, domain_name)
            await self._wiki_store.upsert_wiki_section(
                uid=section_uid,
                title=domain_name,
                description=f"Business domain: {domain_name}",
                section_type="business_domain",
                sort_order=sort_idx,
                auto_generated=True,
            )
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

            from wiki.domain_overview_composer import DomainOverviewComposer

            overview_composer = DomainOverviewComposer(llm_port)
            domain_modules = [
                (repo, mod_name, node)
                for repo, mod_name in repo_module_pairs
                for node in [self._find_module_node(all_modules, repo, mod_name)]
                if node is not None
            ]
            overview_page = await overview_composer.compose(
                domain_name, domain_modules, language=language,
            )
            all_pages.append(overview_page)

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

        # Persist business domain overview pages (namespace: business_id)
        if all_pages:
            await self._persist_pages_to_graph(business_id, all_pages, language=language)

        # Generate per-repo wiki pages (creates WikiPages + SOURCE_ENTITY edges)
        partial_errors: list[dict[str, str]] = []
        for repo_name in all_modules:
            try:
                await self.generate(
                    repo_name,
                    "repo",
                    "structure",
                    "json",
                    language,
                    llm_provider,
                )
            except Exception as exc:
                log.warning("business_wiki_repo_failed", repository=repo_name, exc_info=True)
                partial_errors.append({"repository": repo_name, "error": str(exc)})

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
        }

    def _find_module_node(
        self,
        all_modules: dict[str, list[GraphNode]],
        repo: str,
        module_name: str,
    ) -> GraphNode | None:
        for m in all_modules.get(repo, []):
            name = m.properties.get("name")
            if isinstance(name, str) and name == module_name:
                return m
        return None

    def _budget_for_tier(self, tier: ImportanceTier | None, *, multiplier: float = 1.0) -> int:
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

    async def _enrich_pages_after_compose(
        self,
        pages: list[WikiPage],
        page_tier_map: dict[str, ImportanceTier],
        config: WikiConfig,
        llm_provider: str | None = None,
    ) -> None:
        app_cfg = self._wiki_cfg
        if not app_cfg.enrichment_enabled:
            return
        llm_port = self._resolve_llm_port(llm_provider)
        if llm_port is None:
            return
        from wiki.async_enrichment import AsyncEnrichmentPipeline

        pipeline = AsyncEnrichmentPipeline(
            llm_port,
            round1_enabled=app_cfg.enrichment_round1_enabled,
            round2_enabled=app_cfg.enrichment_round2_enabled,
        )
        if not page_tier_map:
            log.info(
                "enrichment_skipped_no_tiers",
                reason="ImportanceScorer did not run; enrichment requires tier data",
            )
            return
        for page in pages:
            if page.page_type == PageType.REPO_OVERVIEW:
                continue
            tier = page_tier_map.get(page.path, ImportanceTier.STANDARD)
            await pipeline.enrich_page(
                page,
                entity_name=page.title,
                entity_label=page.page_type.value,
                tier=tier,
                language=config.language,
            )

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
    ) -> tuple[list[WikiPage], bool]:
        pages: list[WikiPage] = []
        degraded = False
        tiers = importance_tiers or {}
        page_tier_map: dict[str, ImportanceTier] = {}

        async def walk(node: WikiStructureNode, parent_ctx: str = "") -> None:
            nonlocal degraded
            if node.page_type == PageType.REPO_OVERVIEW:
                page = self._make_repo_overview_page(
                    repository, structure, config, community_markdown=community_markdown,
                )
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                pages.append(page)
            else:
                graph_node = await self._resolve_structure_node(repository, node)
                tier = tiers.get(graph_node.uid)
                code_budget = self._budget_for_tier(
                    tier, multiplier=token_budget_multiplier,
                )
                page_data = await self._collector.collect(repository, graph_node, code_budget=code_budget)
                if tier is not None:
                    page_data.importance_tier = tier
                page = await composer.compose_page(
                    page_data,
                    node.page_type,
                    config,
                    parent_context=parent_ctx,
                )
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                pages.append(page)
                page._source_entity_uid = graph_node.uid  # type: ignore[attr-defined]
                if tier is not None:
                    page_tier_map[page.path] = tier
                if config.mode == "full" and page.metadata.fallback_tier == 3:
                    degraded = True
            for ch in node.children:
                await walk(ch, parent_ctx)

        await walk(structure.root)
        await self._enrich_pages_after_compose(pages, page_tier_map, config, llm_provider)
        return pages, degraded

    async def _resolve_structure_node(self, repository: str, node: WikiStructureNode) -> GraphNode:
        if node.page_type == PageType.MODULE_OVERVIEW:
            g = await self._graph.find_node_by_path(repository, node.path)
        else:
            g = await self._graph.find_node_by_fqn(repository, node.path)
            if g is None:
                g = await self._graph.find_node_by_path(repository, node.path)
        if g is None:
            raise WikiScopeError(f"No graph node for wiki path {node.path!r} in repository {repository!r}")
        return g

    def _make_repo_overview_page(
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

    async def _persist_pages_to_graph(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str = "en",
    ) -> None:
        if self._store is None or not hasattr(self._store, "persist_wiki_pages"):
            return
        old_contents: dict[str, str] = {}
        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
        ):
            for p in pages:
                wuid = f"WikiPage:{repository}:{p.path}"
                r = await self._store.execute_query(
                    "MATCH (w:WikiPage {uid: $uid}) RETURN coalesce(w.content, '') AS c LIMIT 1",
                    {"uid": wuid},
                )
                rows = getattr(r, "data", None) or []
                if rows:
                    r0 = rows[0]
                    if isinstance(r0, dict):
                        old_contents[p.path] = str(r0.get("c", "") or "")
                    else:
                        old_contents[p.path] = ""
                else:
                    old_contents[p.path] = ""
        ts = datetime.now(timezone.utc).isoformat()
        page_dicts = [
            {
                "path": p.path,
                "title": p.title,
                "content": p.content,
                "page_type": p.page_type.value,
                "generated_at": ts,
                "importance_tier": getattr(p.metadata, "importance_tier", None),
                "enrichment_level": getattr(p.metadata, "enrichment_level", None),
                "entity_uid": getattr(p, "_source_entity_uid", None),
            }
            for p in pages
        ]
        try:
            await self._store.persist_wiki_pages(repository, page_dicts)
        except Exception as exc:
            log.warning("wiki_page_persist_failed", repository=repository, error=str(exc))
            return

        pairs: list[dict[str, str]] = [
            {
                "wiki_uid": f"WikiPage:{repository}:{pd['path']}",
                "entity_uid": pd["entity_uid"],
            }
            for pd in page_dicts
            if pd.get("entity_uid")
        ]
        if pairs:
            # One batched UNWIND+MERGE for all SOURCE_ENTITY edges. If this query fails, we log a
            # single batch error only — we do not fall back to per-pair MERGEs (per-edge failures
            # are not reported separately) to keep persistence fast under large page batches.
            batch_q = (
                "UNWIND $pairs AS pair "
                "MATCH (wp:WikiPage {uid: pair.wiki_uid}) "
                "MATCH (e {uid: pair.entity_uid}) "
                "MERGE (wp)-[:SOURCE_ENTITY]->(e)"
            )
            try:
                await self._store.execute_query(batch_q, {"pairs": pairs})
            except Exception as exc:
                log.warning("source_entity_batch_failed", repository=repository, error=str(exc))

        if self._confidence_scoring_enabled() and self._store is not None:
            try:
                scorer = confidence_scorer_from_wiki_app_config(self._wiki_cfg)
                scores: list[tuple[str, float]] = []
                for pd in page_dicts:
                    uid = f"WikiPage:{repository}:{pd['path']}"
                    gen_at = str(pd.get("generated_at", "") or ts)
                    inputs = await gather_confidence_inputs(
                        self._store,
                        uid,
                        repository,
                        gen_at,
                    )
                    scores.append((pd["path"], scorer.compute(inputs)))
                await set_wiki_page_confidence_scores(
                    self._store, scores, repository=repository,
                )
            except Exception as exc:
                log.warning("wiki_confidence_persist_failed", repository=repository, error=str(exc))

        try:
            emb_gen = EmbeddingGenerator.shared(config=self._embedding_cfg)
            items = [
                doc_dict_for_embedding(
                    {"title": d["title"], "content": d["content"][:3000]},
                )
                for d in page_dicts
            ]
            embeddings = await emb_gen.generate_for_docs(items)
            emb_items: list[tuple[str, NodeLabel, list[float]]] = [
                (
                    f"WikiPage:{repository}:{page_dict['path']}",
                    NodeLabel.WIKI_PAGE,
                    embedding,
                )
                for page_dict, embedding in zip(page_dicts, embeddings, strict=True)
            ]
            _batch = getattr(self._store, "batch_set_node_embeddings", None)
            _f = getattr(_batch, "__func__", _batch) if _batch is not None else None
            if _f is not None and inspect.iscoroutinefunction(_f):
                await self._store.batch_set_node_embeddings(emb_items)
            else:
                for page_dict, embedding in zip(page_dicts, embeddings, strict=True):
                    uid = f"WikiPage:{repository}:{page_dict['path']}"
                    await self._store.set_node_embedding(uid, NodeLabel.WIKI_PAGE, embedding)
        except Exception as exc:
            log.warning("wiki_page_embedding_failed", repository=repository, error=str(exc))

        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
        ):
            import time as _time

            from wiki.claim_extractor import extract_claims
            from wiki.claim_tracker import ClaimTracker

            now_ts = int(_time.time())
            for p in pages:
                try:
                    old_c = old_contents.get(p.path, "")
                    wiki_uid = f"WikiPage:{repository}:{p.path}"
                    old_claims = await extract_claims(self._llm, old_c, language) if old_c.strip() else []
                    new_claims = await extract_claims(self._llm, p.content, language)
                    pairs = ClaimTracker.find_supersedions(old_claims, new_claims)
                    next_v = await self._wiki_store.next_claim_version(wiki_uid)
                    by_text: dict[str, str] = {}
                    for cl in new_claims:
                        proposed = f"WikiClaimHistory:{wiki_uid}:{next_v}"
                        cuid = await self._wiki_store.find_or_create_wiki_claim(
                            wiki_uid,
                            cl.claim_text,
                            next_v,
                            new_claim_uid=proposed,
                            created_at=now_ts,
                        )
                        if cuid == proposed:
                            next_v += 1
                        by_text[cl.claim_text.strip()] = cuid
                    for pr in pairs:
                        old_u = await self._wiki_store.find_wiki_claim_by_text(
                            wiki_uid, pr.old_claim_text,
                        )
                        nu = by_text.get(pr.new_claim_text.strip())
                        if old_u and nu:
                            await self._wiki_store.set_wiki_claim_superseded(
                                old_u, nu, now_ts,
                            )
                    sup_list = [p.new_claim_text for p in pairs]
                    if sup_list:
                        import json as _json

                        await self._wiki_store.set_wiki_page_supersedes(
                            wiki_uid,
                            _json.dumps(sup_list, ensure_ascii=False),
                        )
                except Exception as exc:
                    log.warning(
                        "wiki_claim_tracking_failed",
                        repository=repository,
                        path=p.path,
                        error=str(exc),
                    )

    async def get_enrichment_status(self, repository: str) -> dict[str, Any]:
        """Return enrichment level distribution for wiki pages."""
        await self._ensure_repo(repository)
        if self._store is None or not hasattr(self._store, "execute_query"):
            return {
                "repository": repository,
                "total_pages": 0,
                "base": 0,
                "enriched": 0,
                "encyclopedia": 0,
            }
        q = (
            "MATCH (p:WikiPage {repository: $repo}) "
            "RETURN p.enrichment_level AS level, count(p) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        counts: dict[str, int] = {"base": 0, "enriched": 0, "encyclopedia": 0}
        total = 0
        for row in getattr(result, "raw", []) or []:
            raw_level = row[0]
            if raw_level is None or raw_level == "":
                level = "base"
            else:
                level = str(raw_level)
            cnt = int(row[1])
            counts[level] = counts.get(level, 0) + cnt
            total += cnt
        return {"repository": repository, "total_pages": total, **counts}

    async def trigger_enrichment(self, repository: str) -> dict[str, Any]:
        """Dry-run: count wiki pages persisted at BASE that would be eligible for enrichment.

        Does not enqueue or run enrichment; that happens during wiki generation when
        importance tiers are available.
        """
        await self._ensure_repo(repository)
        llm_port = self._resolve_llm_port(None)
        if self._store is None or llm_port is None:
            return {
                "eligible_pages": 0,
                "repository": repository,
                "reason": "LLM or store not available",
            }
        q = (
            "MATCH (p:WikiPage {repository: $repo}) "
            "WHERE p.enrichment_level IS NULL OR p.enrichment_level = 'base' "
            "OR p.enrichment_level = '' "
            "RETURN count(p) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows = getattr(result, "raw", []) or []
        eligible_pages = int(rows[0][0]) if rows else 0
        return {
            "eligible_pages": eligible_pages,
            "repository": repository,
            "note": (
                "Enrichment runs automatically during wiki generation. "
                "This endpoint reports pages eligible for enrichment."
            ),
        }
