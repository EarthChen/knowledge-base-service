"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from config import AppWikiFlags as WikiAppConfig, EmbeddingConfig
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from llm.base_provider import LLMPortBridge
from llm.provider_factory import LLMProviderFactory
from store.schema import EdgeType, GraphNode, NodeLabel
from wiki.backlink_builder import BacklinkBuilder
from wiki.composer import WikiComposer
from wiki.confidence_inputs import gather_confidence_inputs, set_wiki_page_confidence_scores
from wiki.community_context import format_communities_markdown
from wiki.confidence_scorer import confidence_scorer_from_wiki_app_config
from wiki.dependency_graph import DomainNode
from wiki.deferred_enrichment import DeferredEnrichmentService
from wiki.context import WikiContextBuilder
from wiki.data_collector import DataCollectorPort, WikiDataCollector
from wiki.delegation import evaluate_delegation, group_children_by_graph
from wiki.exporter import WikiExporter
from wiki.incremental_diff import compute_wiki_diff
from wiki.memory_loop import MemoryLoop
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
from wiki.structure_planner import WikiScopeError, WikiStructurePlanner
from wiki.tree_builder import WikiTreeBuilder
from wiki.wikilink_cache import WikiLinkCache

from log import get_logger
from store.wiki_store import WikiStore

if TYPE_CHECKING:
    from indexer.business_flow_inferencer import BusinessFlowInferencer
    from wiki.change_detector import AffectedPageSet

log = get_logger(__name__)


def _populate_navigation_context(
    root: WikiStructureNode,
    pages: dict[str, WikiPage],
) -> None:
    """Walk structure tree and populate NavigationContext for each page."""
    from wiki.models import NavigationContext

    def _walk(
        node: WikiStructureNode,
        parent: WikiStructureNode | None,
        breadcrumbs: list[tuple[str, str]],
    ) -> None:
        current_crumbs = breadcrumbs + [(node.title, node.path)]
        if node.path in pages:
            page = pages[node.path]
            nav = NavigationContext(
                parent_path=parent.path if parent else None,
                parent_title=parent.title if parent else None,
                sibling_paths=[
                    ch.path for ch in (parent.children if parent else []) if ch.path != node.path
                ],
                child_paths=[ch.path for ch in node.children],
                breadcrumbs=current_crumbs,
            )
            page.navigation = nav
        for child in node.children:
            _walk(child, node, current_crumbs)

    _walk(root, None, [])


def _expected_wiki_page_paths_dfs(node: WikiStructureNode) -> list[str]:
    """Depth-first structure paths matching ``_compose_all_pages`` walk order."""
    if node.page_type == PageType.REPO_OVERVIEW:
        order = [node.path]
        for ch in node.children:
            order.extend(_expected_wiki_page_paths_dfs(ch))
        return order
    order = [node.path]
    for ch in node.children:
        order.extend(_expected_wiki_page_paths_dfs(ch))
    return order


def _extract_summary(page: WikiPage, entity_uid: str = "") -> WikiPageSummary:
    """Extract a short summary from a composed WikiPage for parent aggregation."""
    content = page.content or ""
    overview_start = content.find("## Overview")
    if overview_start >= 0:
        after_heading = content[overview_start + len("## Overview") :].strip()
        next_heading = after_heading.find("\n## ")
        if next_heading > 0:
            summary_text = after_heading[:next_heading].strip()[:200]
        else:
            summary_text = after_heading[:200]
    else:
        lines = content.split("\n")
        non_heading = [ln for ln in lines if ln.strip() and not ln.startswith("#")]
        summary_text = " ".join(non_heading)[:200]
    summary_text = summary_text.replace("\n", " ").strip()
    return WikiPageSummary(
        entity_uid=entity_uid,
        title=page.title,
        path=page.path,
        summary=summary_text,
        importance_tier=getattr(page, "_importance_tier", None),
        page_type=page.page_type,
    )


def _collect_nodes_by_depth(
    root: WikiStructureNode,
) -> tuple[list[WikiStructureNode], list[tuple[int, WikiStructureNode]]]:
    """Partition tree into (leaves, [(depth, parent_node)]) with parents sorted deepest-first."""
    leaves: list[WikiStructureNode] = []
    parents: list[tuple[int, WikiStructureNode]] = []

    def _visit(node: WikiStructureNode, depth: int) -> None:
        if node.page_type == PageType.REPO_OVERVIEW:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)
            return
        if not node.children:
            leaves.append(node)
        else:
            parents.append((depth, node))
            for child in node.children:
                _visit(child, depth + 1)

    _visit(root, 0)
    parents.sort(key=lambda x: -x[0])
    return leaves, parents


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
        redis_conn: Any | None = None,
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
        self._redis = redis_conn

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
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
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

        if format == "markdown" and len(pages) == 1:
            return {
                "content": self._exporter.export_markdown_single(pages[0]),
                "format": "markdown",
                "degraded": degraded,
            }

        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        return bundle

    async def _bulk_set_wiki_code_hashes(self, repository: str) -> None:
        """After full generation, mark all entities as wiki-synced."""
        query_port = self._store if self._store is not None else self._graph
        if query_port is None or not hasattr(query_port, "execute_query"):
            return
        await query_port.execute_query(
            "MATCH (n {repository: $repo}) "
            "WHERE n.code_hash IS NOT NULL "
            "SET n.wiki_code_hash = n.code_hash",
            {"repo": repository},
        )
        log.info("bulk_wiki_code_hashes_set", repository=repository)

    async def inject_wikilinks(self, repository: str, pages: list[WikiPage]) -> None:
        """Append ``## Related Pages`` using outgoing ``WIKI_REFERENCES`` from the graph."""
        if self._wiki_store is None or not pages:
            return
        from wiki.reference_generator import WikiReferenceGenerator

        ref_gen = WikiReferenceGenerator(self._wiki_store)
        for page in pages:
            uid = f"WikiPage:{repository}:{page.path}"
            try:
                out = await self._wiki_store.get_wiki_page_references(uid)
            except Exception:
                log.debug("wiki_page_references_lookup_failed", page_uid=uid, exc_info=True)
                continue
            rows = getattr(out, "data", None) or []
            paths: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                p = str(row.get("path", "") or "").strip()
                if p:
                    paths.append(p)
            page.content = ref_gen.inject_wikilinks(page.content or "", paths)

    async def _sync_graph_references_into_page_content(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str,
        skip_claim_tracking: bool,
    ) -> None:
        """Build ``WIKI_REFERENCES`` from the code graph, inject related links into page bodies, re-persist."""
        if self._wiki_store is None or not pages:
            return
        try:
            from wiki.reference_generator import WikiReferenceGenerator

            ref_gen = WikiReferenceGenerator(self._wiki_store)
            n = await ref_gen.generate(repository)
            log.info("wiki_reference_edges_generated", repository=repository, count=n)
            await self.inject_wikilinks(repository, pages)
            await self._persist_pages_to_graph(
                repository,
                pages,
                language=language,
                skip_claim_tracking=skip_claim_tracking,
            )
        except Exception:
            log.warning("wiki_sync_references_inject_failed", repository=repository, exc_info=True)

    async def _update_wiki_code_hashes(self, repository: str, uids: list[str]) -> None:
        """After successful wiki page generation, set wiki_code_hash = code_hash."""
        if not uids:
            return
        query_port = self._store if self._store is not None else self._graph
        if query_port is None or not hasattr(query_port, "execute_query"):
            return
        await query_port.execute_query(
            "MATCH (n {repository: $repo}) "
            "WHERE n.uid IN $uids AND n.code_hash IS NOT NULL "
            "SET n.wiki_code_hash = n.code_hash",
            {"repo": repository, "uids": uids},
        )
        log.info("wiki_code_hashes_updated", repository=repository, count=len(uids))

    @staticmethod
    def _sort_by_depth(
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

    def _resume_source_content_hash(self, graph_node: GraphNode, source_content: str) -> str:
        """Prefer graph ``code_hash`` (matches incremental ``wiki_code_hash``); fallback to hashed sources."""
        props = graph_node.properties or {}
        ch = props.get("code_hash")
        if isinstance(ch, str) and ch.strip():
            return ch.strip()
        return hashlib.sha256(source_content.encode()).hexdigest()

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

        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        yield {"complete": bundle}

    async def generate_business_wiki(
        self,
        business_id: str,
        language: str = "en",
        llm_provider: str | None = None,
        *,
        token_budget_multiplier: float = 1.0,
        incremental: bool = True,
        mode: str = "structure",
        progress_callback: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
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

        total_repos = len(all_modules)
        if progress_callback:
            await progress_callback({
                "completed_repos": 0,
                "total_repos": total_repos,
                "current_repo": "",
                "phase": "classifying_domains",
            })

        from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner

        llm_port = self._resolve_llm_port(llm_provider)
        planner = CrossRepoBusinessDomainPlanner(
            llm_port,
            infrastructure_label=app_cfg.business_domain_infrastructure_label,
            batch_threshold=app_cfg.business_wiki_batch_threshold,
            sub_batch_size=app_cfg.business_domain_sub_batch_size,
            max_concurrency=app_cfg.business_domain_max_concurrency,
        )
        try:
            _sbs = max(1, app_cfg.business_domain_sub_batch_size)
            _mc = max(1, app_cfg.business_domain_max_concurrency)
            per_repo_waves = sum(
                max(1, -(-(-(-len(mods) // _sbs)) // _mc))
                for mods in all_modules.values()
                if mods
            )
            per_batch_timeout = app_cfg.business_domain_classify_timeout
            classify_budget = per_batch_timeout * (per_repo_waves + 1) + 300
            domain_mapping, domain_tree = await asyncio.wait_for(
                planner.classify_hierarchical(business_id, all_modules, self._store),
                timeout=classify_budget,
            )
        except TimeoutError:
            log.warning("domain_classification_timeout", business_id=business_id)
            domain_tree = None
            domain_mapping = {
                app_cfg.business_domain_infrastructure_label: [
                    (repo, mod.properties.get("name", ""))
                    for repo, mods in all_modules.items()
                    for mod in mods
                    if isinstance(mod.properties.get("name"), str)
                ],
            }

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
            domain_subtree = None
            domain_entry_points: list[str] = []
            if domain_tree:
                domain_subtree = [d for d in domain_tree if d.name == domain_name]
            overview_page = await overview_composer.compose(
                domain_name, domain_modules, language=language,
                domain_tree=domain_subtree,
                entry_points=domain_entry_points,
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

        log.info(
            "domain_overviews_composed",
            business_id=business_id,
            overview_pages=len(all_pages),
            domains=len(domain_names),
        )

        if all_pages:
            await self._persist_pages_to_graph(business_id, all_pages, language=language)

        log.info("per_repo_generation_starting", business_id=business_id, repo_count=len(all_modules))

        partial_errors: list[dict[str, str]] = []
        total_repos = len(all_modules)
        completed_repos = 0
        if progress_callback:
            await progress_callback({
                "completed_repos": 0,
                "total_repos": total_repos,
                "current_repo": "",
                "phase": "generating_pages",
            })
        for repo_name in all_modules:
            if repo_name not in changed_repos:
                completed_repos += 1
                if progress_callback:
                    await progress_callback({
                        "completed_repos": completed_repos,
                        "total_repos": total_repos,
                        "current_repo": repo_name,
                        "phase": "generating_pages",
                        "skipped": True,
                    })
                continue
            try:
                log.info(
                    "repo_wiki_generate_start",
                    repository=repo_name,
                    index=completed_repos + 1,
                    total=total_repos,
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
                )
                log.info("repo_wiki_generate_done", repository=repo_name)
            except Exception as exc:
                log.warning("business_wiki_repo_failed", repository=repo_name, error=str(exc)[:200], exc_info=True)
                partial_errors.append({"repository": repo_name, "error": str(exc)})
            completed_repos += 1
            if progress_callback:
                await progress_callback({
                    "completed_repos": completed_repos,
                    "total_repos": total_repos,
                    "current_repo": repo_name,
                    "phase": "generating_pages",
                    "skipped": False,
                })

        await self._link_pages_to_tree(
            business_id, domain_mapping, list(all_modules.keys()), tree_builder,
        )

        if domain_tree:
            try:
                pages_result = await self._wiki_store.get_wiki_pages_for_business(business_id)
                pages_by_entity: dict[str, dict[str, Any]] = {}
                for page in pages_result:
                    entity_uid = page.get("entity_uid", "")
                    title = page.get("title", "")
                    if entity_uid:
                        pages_by_entity[str(entity_uid)] = page
                    if title:
                        pages_by_entity[str(title)] = page
                await self._link_pages_to_nested_tree(
                    business_id, domain_tree, pages_by_entity, tree_builder,
                )
            except Exception:
                log.warning(
                    "link_nested_tree_failed",
                    business_id=business_id,
                    exc_info=True,
                )

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

    async def _link_pages_to_tree(
        self,
        business_id: str,
        domain_mapping: dict[str, list[tuple[str, str]]],
        repo_names: list[str],
        tree_builder: WikiTreeBuilder,
    ) -> None:
        """Create HAS_CHILD edges from WikiSection to WikiPage for both view types.

        - code_structure: WikiSection:repo → WikiPage (all pages of that repo)
        - business_domain: WikiSection:domain → WikiPage (pages mixed across repos)
        """
        if self._wiki_store is None:
            return

        module_to_domain: dict[tuple[str, str], str] = {}
        for domain_name, pairs in domain_mapping.items():
            for repo, mod_name in pairs:
                module_to_domain[(repo, mod_name)] = domain_name

        pages_result = await self._wiki_store.get_wiki_pages_for_business(business_id)

        pages_by_repo: dict[str, list[dict[str, Any]]] = {}
        for page in pages_result:
            repo = page.get("repository", "")
            if repo:
                pages_by_repo.setdefault(repo, []).append(page)

        linked_code = 0
        linked_domain = 0
        domain_page_counters: dict[str, int] = {}

        for repo_name in repo_names:
            repo_pages = pages_by_repo.get(repo_name, [])
            if not repo_pages:
                continue

            repo_section_uid = tree_builder.generate_repo_section_uid(business_id, repo_name)

            for idx, page in enumerate(repo_pages):
                page_uid = page.get("uid", "")
                if not page_uid:
                    continue

                try:
                    await self._wiki_store.add_has_child_edge(
                        parent_uid=repo_section_uid,
                        parent_label="WikiSection",
                        child_uid=page_uid,
                        child_label="WikiPage",
                        view_type="code_structure",
                        sort_order=idx,
                    )
                    linked_code += 1
                except Exception:
                    log.warning("link_page_code_structure_failed", page_uid=page_uid, exc_info=True)

                mod_name = page.get("title", "")
                entity_uid = str(page.get("entity_uid", "") or "")

                domain_name = None
                if entity_uid:
                    for (r, m), d in module_to_domain.items():
                        if r == repo_name and entity_uid.endswith(m):
                            domain_name = d
                            break
                if not domain_name:
                    domain_name = module_to_domain.get((repo_name, mod_name))
                if not domain_name:
                    for (r, m), d in module_to_domain.items():
                        if r == repo_name:
                            domain_name = d
                            break
                if not domain_name:
                    domain_name = self._wiki_cfg.business_domain_infrastructure_label

                domain_section_uid = tree_builder.generate_domain_section_uid(
                    business_id, domain_name,
                )
                sort_idx = domain_page_counters.get(domain_name, 0)
                domain_page_counters[domain_name] = sort_idx + 1

                try:
                    await self._wiki_store.add_has_child_edge(
                        parent_uid=domain_section_uid,
                        parent_label="WikiSection",
                        child_uid=page_uid,
                        child_label="WikiPage",
                        view_type="business_domain",
                        sort_order=sort_idx,
                    )
                    linked_domain += 1
                except Exception:
                    log.warning("link_page_business_domain_failed", page_uid=page_uid, exc_info=True)

        log.info(
            "wiki_tree_pages_linked",
            business_id=business_id,
            linked_code_structure=linked_code,
            linked_business_domain=linked_domain,
            total_pages=len(pages_result),
        )

    async def _link_pages_to_nested_tree(
        self,
        business_id: str,
        domain_tree: list[DomainNode],
        pages_by_entity_uid: dict[str, dict[str, Any]],
        tree_builder: WikiTreeBuilder,
    ) -> None:
        """Create nested HAS_CHILD edges for WikiSection hierarchy (business_domain view).

        Builds a subtree under an internal ``__root__`` section (linked from WikiSpace).
        Modules are matched to persisted pages via ``pages_by_entity_uid`` (keys are
        module identifiers as emitted in :class:`DomainNode`.modules — typically
        simple module names consumed by callers).
        """
        if self._wiki_store is None:
            return

        root_uid = tree_builder.generate_domain_section_uid(business_id, "__root__")
        space_uid = tree_builder.generate_space_uid(business_id)

        async def _ensure_root() -> None:
            try:
                await self._wiki_store.upsert_wiki_section(
                    uid=root_uid,
                    title="__root__",
                    description="Nested domain tree root",
                    section_type="business_domain",
                    sort_order=-1,
                    auto_generated=True,
                )
                await self._wiki_store.add_has_child_edge(
                    parent_uid=space_uid,
                    parent_label="WikiSpace",
                    child_uid=root_uid,
                    child_label="WikiSection",
                    view_type="business_domain",
                    sort_order=0,
                )
            except Exception:
                log.warning("nested_tree_root_failed", business_id=business_id, exc_info=True)

        await _ensure_root()

        async def _link_domain(parent_uid: str, domain: DomainNode, sort_idx: int) -> None:
            section_uid = tree_builder.generate_domain_section_uid(business_id, domain.name)
            try:
                await self._wiki_store.upsert_wiki_section(
                    uid=section_uid,
                    title=domain.name,
                    description=domain.description or "",
                    section_type="business_domain",
                    sort_order=sort_idx,
                    auto_generated=True,
                )
                await self._wiki_store.add_has_child_edge(
                    parent_uid=parent_uid,
                    parent_label="WikiSection",
                    child_uid=section_uid,
                    child_label="WikiSection",
                    view_type="business_domain",
                    sort_order=sort_idx,
                )
            except Exception:
                log.warning("nested_tree_section_failed", domain=domain.name, exc_info=True)
                return

            for i, module_name in enumerate(domain.modules):
                page = pages_by_entity_uid.get(module_name)
                if page:
                    page_uid = (
                        page.get("uid", "") if isinstance(page, dict) else getattr(page, "uid", "")
                    )
                    if page_uid:
                        try:
                            await self._wiki_store.add_has_child_edge(
                                parent_uid=section_uid,
                                parent_label="WikiSection",
                                child_uid=page_uid,
                                child_label="WikiPage",
                                view_type="business_domain",
                                sort_order=i,
                            )
                        except Exception:
                            log.warning(
                                "nested_tree_page_link_failed", page_uid=page_uid,
                                exc_info=True,
                            )

            for i, child in enumerate(domain.children):
                await _link_domain(section_uid, child, i)

        for i, domain in enumerate(domain_tree):
            await _link_domain(root_uid, domain, i)

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
        if config.mode == "structure":
            log.info(
                "enrichment_skipped_structure_mode",
                repository=config.repository,
                page_count=len(pages),
            )
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
        enrich_limit = max(1, int(getattr(self._wiki_cfg, "compose_concurrency", 3)))
        enrich_sem = asyncio.Semaphore(enrich_limit)

        async def _enrich_one(page: WikiPage, tier: ImportanceTier) -> None:
            async with enrich_sem:
                await pipeline.enrich_page(
                    page,
                    entity_name=page.title,
                    entity_label=page.page_type.value,
                    tier=tier,
                    language=config.language,
                )

        targets = [
            (page, page_tier_map.get(page.path, ImportanceTier.STANDARD))
            for page in pages
            if page.page_type != PageType.REPO_OVERVIEW
        ]
        await asyncio.gather(*(_enrich_one(p, t) for p, t in targets))

    def _resolve_skeleton_strategy(self, tier: ImportanceTier | None) -> SkeletonStrategy | None:
        if tier != ImportanceTier.SKELETON:
            return None
        raw = getattr(self._wiki_cfg, "skeleton_strategy", "template")
        try:
            return SkeletonStrategy(raw)
        except ValueError:
            return SkeletonStrategy.TEMPLATE

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
        import time as _time

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

        async def compose_leaf(node: WikiStructureNode) -> WikiPage | None:
            nonlocal degraded
            async with sem:
                try:
                    graph_node = await asyncio.wait_for(
                        self._resolve_structure_node(repository, node),
                        timeout=30,
                    )
                except TimeoutError:
                    log.warning("resolve_leaf_timeout", path=node.path)
                    return None
                except Exception:
                    log.warning("resolve_leaf_error", path=node.path, exc_info=True)
                    return None
                tier = tiers.get(graph_node.uid)
                code_budget = self._budget_for_tier(
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
                skeleton_strat = self._resolve_skeleton_strategy(tier)

                src_concat = "".join(cs.source for cs in page_data.code_snippets)
                page_res: WikiPage | None = None
                if resume_enabled and existing_page_hashes and composer._wiki_store is not None:
                    ex_h = existing_page_hashes.get(node.path)
                    cur_h = self._resume_source_content_hash(graph_node, src_concat)
                    if ex_h and cur_h and ex_h == cur_h:
                        log.debug("resume_skip_unchanged", path=node.path)
                        page_res = await self._load_wikipage_for_resume_entity(
                            repository,
                            graph_node,
                            structure_path=node.path,
                            structure_title=node.title,
                            structure_page_type=node.page_type,
                            config=config,
                        )
                page: WikiPage | None = page_res
                if page is None:
                    try:
                        page = await asyncio.wait_for(
                            composer.compose_page(
                                page_data,
                                node.page_type,
                                config,
                                importance_tier=tier,
                                skeleton_strategy=skeleton_strat,
                                skeleton_light_model=skeleton_light_model,
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
                    await self._persist_pages_to_graph(
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
                    await self._persist_pages_to_graph(
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
                    page = self._make_repo_overview_page(
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
                        self._resolve_structure_node(repository, parent_node),
                        timeout=30,
                    )
                except TimeoutError:
                    log.warning("resolve_parent_timeout", path=parent_node.path)
                    continue
                except Exception:
                    log.warning("resolve_parent_error", path=parent_node.path, exc_info=True)
                    continue
                tier = tiers.get(graph_node.uid)
                code_budget = self._budget_for_tier(
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
                    rcur = self._resume_source_content_hash(graph_node, resume_src_concat)
                    if rex and rcur and rex == rcur:
                        log.debug("resume_skip_unchanged", path=parent_node.path)
                        page_early = await self._load_wikipage_for_resume_entity(
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
                    skeleton_strat = self._resolve_skeleton_strategy(tier)
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
                            skeleton_strat = self._resolve_skeleton_strategy(tier)
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
                await self._persist_pages_to_graph(
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

                community_svc = getattr(self, "_community_service", None)
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
        skip_claim_tracking: bool = False,
    ) -> None:
        import time as _time

        if self._store is None or not hasattr(self._store, "persist_wiki_pages"):
            return
        _t0 = _time.monotonic()
        log.info("persist_pages_start", repository=repository, page_count=len(pages))

        old_contents: dict[str, str] = {}
        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
        ):
            for i, p in enumerate(pages):
                wuid = f"WikiPage:{repository}:{p.path}"
                try:
                    r = await asyncio.wait_for(
                        self._store.execute_query(
                            "MATCH (w:WikiPage {uid: $uid}) RETURN coalesce(w.content, '') AS c LIMIT 1",
                            {"uid": wuid},
                        ),
                        timeout=10,
                    )
                except TimeoutError:
                    log.warning("supersession_query_timeout", path=p.path, page_num=i)
                    continue
                rows = getattr(r, "data", None) or []
                if rows:
                    r0 = rows[0]
                    if isinstance(r0, dict):
                        old_contents[p.path] = str(r0.get("c", "") or "")
                    else:
                        old_contents[p.path] = ""
                else:
                    old_contents[p.path] = ""
            log.info("supersession_tracking_done", repository=repository, elapsed_s=round(_time.monotonic() - _t0, 1))

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
                "navigation_json": (
                    json.dumps(p.navigation.to_api_dict(), ensure_ascii=False)
                    if p.navigation
                    else ""
                ),
            }
            for p in pages
        ]

        _PERSIST_CHUNK = 200
        _t_persist = _time.monotonic()
        total_persisted = 0
        for chunk_start in range(0, len(page_dicts), _PERSIST_CHUNK):
            chunk = page_dicts[chunk_start : chunk_start + _PERSIST_CHUNK]
            try:
                await asyncio.wait_for(
                    self._store.persist_wiki_pages(repository, chunk),
                    timeout=120,
                )
                total_persisted += len(chunk)
                if chunk_start > 0:
                    log.info(
                        "persist_pages_chunk",
                        repository=repository,
                        persisted=total_persisted,
                        total=len(page_dicts),
                    )
            except TimeoutError:
                log.warning(
                    "persist_pages_chunk_timeout",
                    repository=repository,
                    chunk_start=chunk_start,
                    chunk_size=len(chunk),
                )
            except Exception as exc:
                log.warning("wiki_page_persist_failed", repository=repository, chunk_start=chunk_start, error=str(exc)[:200])

        log.info(
            "persist_pages_write_done",
            repository=repository,
            persisted=total_persisted,
            elapsed_s=round(_time.monotonic() - _t_persist, 1),
        )

        pairs: list[dict[str, str]] = [
            {
                "wiki_uid": f"WikiPage:{repository}:{pd['path']}",
                "entity_uid": pd["entity_uid"],
            }
            for pd in page_dicts
            if pd.get("entity_uid")
        ]
        if pairs:
            _EDGE_CHUNK = 200
            for edge_start in range(0, len(pairs), _EDGE_CHUNK):
                edge_chunk = pairs[edge_start : edge_start + _EDGE_CHUNK]
                batch_q = (
                    "UNWIND $pairs AS pair "
                    "MATCH (wp:WikiPage {uid: pair.wiki_uid}) "
                    "MATCH (e {uid: pair.entity_uid}) "
                    "MERGE (wp)-[:SOURCE_ENTITY]->(e)"
                )
                try:
                    await asyncio.wait_for(
                        self._store.execute_query(batch_q, {"pairs": edge_chunk}),
                        timeout=120,
                    )
                except TimeoutError:
                    log.warning("source_entity_chunk_timeout", repository=repository, edge_start=edge_start)
                except Exception as exc:
                    log.warning("source_entity_batch_failed", repository=repository, error=str(exc)[:200])

        log.info("persist_pages_complete", repository=repository, total_time_s=round(_time.monotonic() - _t0, 1))

        if self._confidence_scoring_enabled() and self._store is not None:
            _cs_t0 = _time.monotonic()
            log.info("confidence_scoring_start", repository=repository, page_count=len(page_dicts))
            try:
                scorer = confidence_scorer_from_wiki_app_config(self._wiki_cfg)
                scores: list[tuple[str, float]] = []
                for i, pd in enumerate(page_dicts):
                    uid = f"WikiPage:{repository}:{pd['path']}"
                    gen_at = str(pd.get("generated_at", "") or ts)
                    try:
                        inputs = await asyncio.wait_for(
                            gather_confidence_inputs(
                                self._store, uid, repository, gen_at,
                            ),
                            timeout=10,
                        )
                        scores.append((pd["path"], scorer.compute(inputs)))
                    except TimeoutError:
                        log.warning("confidence_input_timeout", path=pd["path"], page_num=i)
                        continue
                    if (i + 1) % 200 == 0:
                        log.info("confidence_scoring_progress", repository=repository, scored=i + 1, total=len(page_dicts))
                await set_wiki_page_confidence_scores(
                    self._store, scores, repository=repository,
                )
                log.info("confidence_scoring_done", repository=repository, scored=len(scores), elapsed_s=round(_time.monotonic() - _cs_t0, 1))
            except Exception as exc:
                log.warning("wiki_confidence_persist_failed", repository=repository, error=str(exc))

        if total_persisted > 0:
            _emb_t0 = _time.monotonic()
            log.info("wiki_page_embedding_start", repository=repository, page_count=len(page_dicts))
            try:
                emb_gen = EmbeddingGenerator.shared(config=self._embedding_cfg)
                items = [
                    doc_dict_for_embedding(
                        {"title": d["title"], "content": d["content"][:3000]},
                    )
                    for d in page_dicts
                ]
                embeddings = await emb_gen.generate_for_docs(items)
                log.info("wiki_page_embedding_vectors_done", repository=repository, count=len(embeddings), elapsed_s=round(_time.monotonic() - _emb_t0, 1))
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
                log.info("wiki_page_embedding_done", repository=repository, elapsed_s=round(_time.monotonic() - _emb_t0, 1))
            except Exception as exc:
                log.warning("wiki_page_embedding_failed", repository=repository, error=str(exc))
        else:
            log.info("wiki_page_embedding_skipped", repository=repository, reason="no_pages_persisted")

        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
            and not skip_claim_tracking
        ):
            log.info("claim_tracking_start", repository=repository, page_count=len(pages))
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
