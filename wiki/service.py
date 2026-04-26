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
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.context import WikiContextBuilder
from wiki.data_collector import DataCollectorPort, WikiDataCollector
from wiki.exporter import WikiExporter
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

log = get_logger(__name__)


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

    def _composer_for(self, llm_provider: str | None) -> WikiComposer:
        llm_port = self._resolve_llm_port(llm_provider)
        return WikiComposer(
            llm_port,
            WikiContextBuilder(llm_port),
            store=self._graph,
            wiki_store=self._wiki_store,
        )

    def _resolve_llm_port(self, llm_provider: str | None) -> Any | None:
        if self._llm_factory is not None:
            provider = self._llm_factory.get_provider(llm_provider)
            return LLMPortBridge(provider)
        return self._llm

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
    ) -> dict[str, Any]:
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)
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
        )
        await self._persist_pages_to_graph(repository, pages)
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

    async def generate_stream_events(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
        llm_provider: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``{"page": page_dict}`` per page, then ``{"complete": export_bundle}``."""
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)
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
                page = self._make_repo_overview_page(repository, structure, config)
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                yield page
                for ch in node.children:
                    async for p in walk_stream(ch, parent_ctx):
                        yield p
                return
            graph_node = await self._resolve_structure_node(repository, node)
            tier = _importance_tiers.get(graph_node.uid)
            code_budget = self._budget_for_tier(tier)
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
            await self._persist_pages_to_graph(business_id, all_pages)

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

    def _budget_for_tier(self, tier: ImportanceTier | None) -> int:
        """Return the token budget for a given importance tier from app config."""
        app_cfg = self._wiki_cfg
        if tier == ImportanceTier.CORE:
            return app_cfg.core_code_budget
        if tier == ImportanceTier.STANDARD:
            return app_cfg.standard_code_budget
        if tier == ImportanceTier.SKELETON:
            return app_cfg.skeleton_code_budget
        return app_cfg.standard_code_budget

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
    ) -> tuple[list[WikiPage], bool]:
        pages: list[WikiPage] = []
        degraded = False
        tiers = importance_tiers or {}
        page_tier_map: dict[str, ImportanceTier] = {}

        async def walk(node: WikiStructureNode, parent_ctx: str = "") -> None:
            nonlocal degraded
            if node.page_type == PageType.REPO_OVERVIEW:
                page = self._make_repo_overview_page(repository, structure, config)
                page.metadata.enrichment_level = EnrichmentLevel.BASE
                pages.append(page)
            else:
                graph_node = await self._resolve_structure_node(repository, node)
                tier = tiers.get(graph_node.uid)
                code_budget = self._budget_for_tier(tier)
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
    ) -> WikiPage:
        lines = [
            f"# {structure.repository}",
            "",
            "Repository overview generated from the knowledge graph.",
            "",
            f"- Planned wiki pages: {structure.total_pages}",
        ]
        return WikiPage(
            path="README.md",
            title=structure.repository,
            page_type=PageType.REPO_OVERVIEW,
            content="\n".join(lines),
            diagrams=[],
            source_locations=[],
            metadata=WikiPageMetadata(
                node_count=0,
                edge_count=0,
                generation_mode=config.mode,
                fallback_tier=None,
            ),
        )

    async def _persist_pages_to_graph(self, repository: str, pages: list[WikiPage]) -> None:
        if self._store is None or not hasattr(self._store, "persist_wiki_pages"):
            return
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
