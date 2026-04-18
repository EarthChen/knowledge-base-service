"""Orchestrates wiki generation: scope → structure → collect → compose → export."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from store.schema import GraphNode
from wiki.composer import WikiComposer
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
    ) -> None:
        self._graph = graph
        self._planner = WikiStructurePlanner(graph)
        self._collector = WikiDataCollector(graph)
        self._composer = WikiComposer(llm, WikiContextBuilder(llm))
        self._exporter = WikiExporter()
        self._repository_exists = repository_exists

    async def _ensure_repo(self, repository: str) -> None:
        if not await self._repository_exists(repository):
            raise WikiRepoNotFoundError(repository)

    def _config_for(
        self,
        mode: str,
        format: str,
        repository: str,
        language: str = "en",
    ) -> WikiConfig:
        return WikiConfig(repository=repository, mode=mode, format=format, language=language)

    async def generate(
        self,
        repository: str,
        scope_raw: str,
        mode: str,
        format: str,
        language: str = "en",
    ) -> dict[str, Any]:
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)
        pages, degraded = await self._compose_all_pages(repository, structure, config)

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
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield ``{"page": page_dict}`` per page, then ``{"complete": export_bundle}``."""
        scope = parse_scope(scope_raw)
        config = self._config_for(mode, format, repository, language)
        await self._ensure_repo(repository)
        structure = await self._planner.plan(repository, scope)

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
            page = await self._composer.compose_page(
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

        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        yield {"complete": bundle}

    async def _compose_all_pages(
        self,
        repository: str,
        structure: WikiStructure,
        config: WikiConfig,
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
                page = await self._composer.compose_page(
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
