"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from config import get_settings
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
    PageType,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
    parse_scope,
)
from wiki.structure_planner import WikiScopeError, WikiStructurePlanner

from log import get_logger

if TYPE_CHECKING:
    from indexer.business_flow_inferencer import BusinessFlowInferencer

log = get_logger(__name__)


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
    ) -> None:
        self._graph = graph
        self._planner = WikiStructurePlanner(graph)
        self._collector = WikiDataCollector(graph)
        self._llm = llm
        self._llm_factory = llm_factory
        self._exporter = WikiExporter()
        self._repository_exists = repository_exists
        self._store = store
        self._deferred_enrichment = deferred_enrichment
        self._flow_inferencer = flow_inferencer

    def _composer_for(self, llm_provider: str | None) -> WikiComposer:
        llm_port = self._resolve_llm_port(llm_provider)
        return WikiComposer(llm_port, WikiContextBuilder(llm_port), store=self._graph)

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
        pages, degraded = await self._compose_all_pages(repository, structure, config, composer)
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

        async def walk(node: WikiStructureNode, parent_ctx: str = "") -> AsyncIterator[WikiPage]:
            if node.page_type == PageType.REPO_OVERVIEW:
                page = self._make_repo_overview_page(repository, structure, config)
                yield page
                for ch in node.children:
                    async for p in walk(ch, parent_ctx):
                        yield p
                return
            graph_node = await self._resolve_structure_node(repository, node)
            page_data = await self._collector.collect(repository, graph_node)
            page = await composer.compose_page(
                page_data,
                node.page_type,
                config,
                parent_context=parent_ctx,
            )
            yield page
            for ch in node.children:
                async for p in walk(ch, parent_ctx):
                    yield p

        degraded = False
        async for page in walk(structure.root):
            pages.append(page)
            if config.mode == "full" and page.metadata.fallback_tier == 3:
                degraded = True
            yield {"page": page.to_dict()}

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

    async def _compose_all_pages(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
        composer: WikiComposer,
    ) -> tuple[list[WikiPage], bool]:
        pages: list[WikiPage] = []
        degraded = False

        async def walk(node: WikiStructureNode, parent_ctx: str = "") -> None:
            nonlocal degraded
            if node.page_type == PageType.REPO_OVERVIEW:
                pages.append(self._make_repo_overview_page(repository, structure, config))
            else:
                graph_node = await self._resolve_structure_node(repository, node)
                page_data = await self._collector.collect(repository, graph_node)
                page = await composer.compose_page(
                    page_data,
                    node.page_type,
                    config,
                    parent_context=parent_ctx,
                )
                pages.append(page)
                if config.mode == "full" and page.metadata.fallback_tier == 3:
                    degraded = True
            for ch in node.children:
                await walk(ch, parent_ctx)

        await walk(structure.root)
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
            }
            for p in pages
        ]
        try:
            await self._store.persist_wiki_pages(repository, page_dicts)
        except Exception as exc:
            log.warning("wiki_page_persist_failed", repository=repository, error=str(exc))
            return

        try:
            emb_gen = EmbeddingGenerator.shared(config=get_settings().embedding)
            items = [
                doc_dict_for_embedding(
                    {"title": d["title"], "content": d["content"][:3000]},
                )
                for d in page_dicts
            ]
            embeddings = await emb_gen.generate_for_docs(items)
            for page_dict, embedding in zip(page_dicts, embeddings, strict=True):
                uid = f"WikiPage:{repository}:{page_dict['path']}"
                await self._store.set_node_embedding(uid, NodeLabel.WIKI_PAGE, embedding)
        except Exception as exc:
            log.warning("wiki_page_embedding_failed", repository=repository, error=str(exc))
