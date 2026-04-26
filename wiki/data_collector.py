"""Collects graph-backed data for a single wiki page (nodes, edges, locations)."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.models import ChunkSnippet, CodeSnippet, ImportanceTier, SourceLocation
from wiki.structure_planner import GraphQueryPort


def _edge_frequency(edge: GraphEdge) -> int:
    v = edge.properties.get("frequency")
    if isinstance(v, bool):
        return 1
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return int(v)
    return 1


def _other_uid(edge: GraphEdge, center_uid: str) -> str | None:
    if edge.source_uid == center_uid:
        return edge.target_uid
    if edge.target_uid == center_uid:
        return edge.source_uid
    return None


def _unique_neighbor_uids(center_uid: str, edges: list[GraphEdge]) -> list[str]:
    scores: dict[str, float] = defaultdict(float)
    for edge in edges:
        other = _other_uid(edge, center_uid)
        if other is None or other == center_uid:
            continue
        scores[other] += float(_edge_frequency(edge))
    return sorted(scores.keys(), key=lambda u: (-scores[u], u))


def _neighbor_tier_map(center_uid: str, edges: list[GraphEdge]) -> dict[str, str]:
    ranked = _unique_neighbor_uids(center_uid, edges)
    if len(ranked) <= 15:
        return {}
    top_full = set(ranked[:5])
    return {n: ("full" if n in top_full else "summary") for n in ranked}


def _annotate_neighbor_tiers(
    center_uid: str,
    raw_edges: list[GraphEdge],
    edges: list[GraphEdge],
) -> list[GraphEdge]:
    tier_map = _neighbor_tier_map(center_uid, raw_edges)
    if not tier_map:
        return edges

    out: list[GraphEdge] = []
    for edge in edges:
        if edge.properties.get("summarized") is True:
            out.append(edge)
            continue
        other = _other_uid(edge, center_uid)
        tier = tier_map.get(other or "", "full")
        merged = dict(edge.properties)
        merged["neighbor_tier"] = tier
        out.append(
            GraphEdge(
                edge_type=edge.edge_type,
                source_uid=edge.source_uid,
                target_uid=edge.target_uid,
                properties=merged,
            )
        )
    return out


def _rollup_edges(edge_type: EdgeType, center_uid: str, edges: list[GraphEdge]) -> GraphEdge:
    targets: list[str] = []
    for edge in edges:
        other = _other_uid(edge, center_uid)
        if other:
            targets.append(other)
    return GraphEdge(
        edge_type=edge_type,
        source_uid=center_uid,
        target_uid="__summarized__",
        properties={
            "summarized": True,
            "count": len(edges),
            "targets": targets,
        },
    )


def _prioritize_edges(center_uid: str, edges: list[GraphEdge]) -> list[GraphEdge]:
    buckets: dict[EdgeType, list[GraphEdge]] = defaultdict(list)
    for edge in edges:
        buckets[edge.edge_type].append(edge)

    result: list[GraphEdge] = []

    inherits = sorted(buckets.get(EdgeType.INHERITS, []), key=lambda e: e.target_uid)
    result.extend(inherits)

    calls = buckets.get(EdgeType.CALLS, [])
    calls_sorted = sorted(calls, key=lambda e: (-_edge_frequency(e), e.target_uid))
    top_calls = calls_sorted[:10]
    rest_calls = calls_sorted[10:]
    result.extend(top_calls)

    imports = buckets.get(EdgeType.IMPORTS, [])
    imports_sorted = sorted(imports, key=lambda e: (-_edge_frequency(e), e.target_uid))
    top_imports = imports_sorted[:10]
    rest_imports = imports_sorted[10:]
    result.extend(top_imports)

    processed = {EdgeType.INHERITS, EdgeType.CALLS, EdgeType.IMPORTS}
    for edge_type in sorted(
        (et for et in buckets if et not in processed),
        key=lambda et: et.value,
    ):
        bucket = buckets.get(edge_type, [])
        if bucket:
            result.append(_rollup_edges(edge_type, center_uid, bucket))

    if rest_calls:
        result.append(_rollup_edges(EdgeType.CALLS, center_uid, rest_calls))
    if rest_imports:
        result.append(_rollup_edges(EdgeType.IMPORTS, center_uid, rest_imports))

    return result


def _source_location(node: GraphNode, repository: str) -> SourceLocation:
    props = node.properties
    file_path = str(props.get("file") or props.get("path") or "")
    start_line = int(props.get("start_line") or 0)
    end_line = int(props.get("end_line") or start_line)
    fqn = str(props.get("fqn") or props.get("name") or node.uid)
    return SourceLocation(
        file_path=file_path,
        start_line=start_line,
        end_line=end_line,
        fqn=fqn,
        repository=repository,
    )


def _group_methods(methods: list[GraphNode]) -> list[GraphNode]:
    if len(methods) <= 20:
        return sorted(methods, key=lambda m: str(m.properties.get("name") or m.uid))

    def sort_key(node: GraphNode) -> tuple[str, str]:
        cat = node.properties.get("category")
        category = cat if isinstance(cat, str) else "general"
        name = str(node.properties.get("name") or node.uid)
        return (category, name)

    return sorted(methods, key=sort_key)


@runtime_checkable
class DataCollectorPort(GraphQueryPort, Protocol):
    """Graph queries needed for wiki page data collection."""

    async def find_edges(self, repository: str, node_uid: str) -> list[GraphEdge]: ...

    async def find_node_by_uid(self, repository: str, uid: str) -> GraphNode | None: ...


@dataclass
class PageData:
    node: GraphNode
    edges: list[GraphEdge]
    children: list[GraphNode]
    source_location: SourceLocation
    method_locations: list[SourceLocation]
    business_summary: str | None
    methods: list[GraphNode]
    code_snippets: list[CodeSnippet] = field(default_factory=list)
    importance_tier: ImportanceTier | None = None
    related_chunks: list[ChunkSnippet] = field(default_factory=list)


class WikiDataCollector:
    """Loads prioritized graph context for one wiki page."""

    def __init__(
        self,
        graph_port: DataCollectorPort,
        wiki_store: Any = None,
        rag_enabled: bool = False,
    ) -> None:
        self._graph = graph_port
        self._wiki_store = wiki_store
        self._rag_enabled = rag_enabled

    async def collect(self, repository: str, node: GraphNode, code_budget: int = 8000) -> PageData:
        raw_edges = await self._graph.find_edges(repository, node.uid)
        prioritized = _prioritize_edges(node.uid, raw_edges)
        edges = _annotate_neighbor_tiers(node.uid, raw_edges, prioritized)

        raw_children = await self._graph.find_children(repository, node.uid)

        children: list[GraphNode] = []
        methods: list[GraphNode] = []

        if node.label == NodeLabel.MODULE:
            children = list(raw_children)
        elif node.label == NodeLabel.CLASS:
            methods = _group_methods([c for c in raw_children if c.label == NodeLabel.FUNCTION])

        method_locations = [_source_location(m, repository) for m in methods]

        summary_raw = node.properties.get("business_summary")
        business_summary = summary_raw if isinstance(summary_raw, str) else None

        code_snippets = []
        if self._wiki_store is not None:
            from wiki.source_code_reader import SourceCodeReader

            reader = SourceCodeReader(self._wiki_store)
            code_snippets = await reader.read(node, budget_tokens=code_budget)

        related_chunks = []
        if self._rag_enabled and self._wiki_store is not None:
            from wiki.chunk_retriever import ChunkRetriever

            retriever = ChunkRetriever(self._wiki_store)
            related_chunks = await retriever.retrieve(node, repository)

        return PageData(
            node=node,
            edges=edges,
            children=children,
            source_location=_source_location(node, repository),
            method_locations=method_locations,
            business_summary=business_summary,
            methods=methods,
            code_snippets=code_snippets,
            related_chunks=related_chunks,
        )
