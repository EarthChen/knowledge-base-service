"""Hybrid query interface — combines graph traversal with semantic search.

Provides compound queries that first find semantically relevant entities,
then expand them via graph relationships to discover related code.

Search uses a **layered hybrid** strategy:
  Layer 1 — exact & fuzzy name match via graph (keyword_search)
  Layer 2 — vector similarity search (semantic_search)
  Layer 3 — fusion & deduplication, then graph expansion
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from log import get_logger

from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from query.graph_query import GraphQueryService
from query.semantic_query import SemanticQueryService

log = get_logger(__name__)

_FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)

_IDENT_RE = re.compile(
    r"\b"
    r"(?:"
    r"[a-z]+(?:[A-Z][a-zA-Z0-9]*)+|"   # camelCase  e.g. loginV2
    r"[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]*)+|"  # PascalCase e.g. MdpMoaWrapperService
    r"[a-z]+(?:_[a-z0-9]+)+|"           # snake_case e.g. get_user_info
    r"[a-zA-Z_][a-zA-Z0-9_]{2,}"        # plain identifier >=3 chars
    r")"
    r"\b"
)


def _extract_identifiers(query: str) -> list[str]:
    """Extract probable code identifiers from a natural-language query."""
    stop_words = {
        "the", "this", "that", "what", "where", "which", "how", "does",
        "function", "class", "method", "module", "file", "code", "find",
        "search", "show", "get", "set", "for", "from", "with", "and",
        "not", "are", "was", "has", "have", "all",
    }
    tokens = _IDENT_RE.findall(query)
    return [t for t in tokens if t.lower() not in stop_words]


async def _empty_list() -> list[dict[str, Any]]:
    return []


@dataclass
class HybridResult:
    semantic_matches: list[dict[str, Any]] = field(default_factory=list)
    graph_context: list[dict[str, Any]] = field(default_factory=list)
    query_text: str = ""
    total: int = 0


class HybridQueryService:
    """Combines semantic search with graph traversal for richer results."""

    def __init__(
        self,
        store: FalkorDBStore,
        semantic_svc: SemanticQueryService,
        graph_svc: GraphQueryService,
    ) -> None:
        self._store = store
        self._semantic = semantic_svc
        self._graph = graph_svc

    async def search_with_context(
        self,
        query_text: str,
        k: int = 5,
        expand_depth: int = 2,
        include_callers: bool = True,
        include_callees: bool = True,
    ) -> HybridResult:
        """Layered hybrid search: keyword match + semantic search + graph expansion.

        Layer 1: exact & fuzzy name match (via FalkorDB keyword_search)
        Layer 2: vector similarity search (via embedding model)
        Layer 3: fusion (keyword hits scored higher), dedup, graph expansion
        """
        fqn_matches = _FQN_RE.findall(query_text)
        if fqn_matches:
            identifiers = [m.split("(")[0].strip() for m in fqn_matches]
        else:
            identifiers = _extract_identifiers(query_text)

        keyword_coro = self._keyword_search_multi(identifiers, k) if identifiers else _empty_list()
        semantic_coro = self._semantic.search_all(query_text, k)

        keyword_hits, semantic_result = await asyncio.gather(keyword_coro, semantic_coro)

        merged = self._fuse_results(keyword_hits, semantic_result.matches, k)

        graph_context = await self._expand_graph(merged, expand_depth, include_callers, include_callees)

        return HybridResult(
            semantic_matches=merged,
            graph_context=graph_context,
            query_text=query_text,
            total=len(merged) + len(graph_context),
        )

    async def _keyword_search_multi(self, identifiers: list[str], k: int) -> list[dict[str, Any]]:
        """Run keyword search for each extracted identifier and merge results."""
        all_hits: list[dict[str, Any]] = []
        seen_uids: set[str] = set()
        for ident in identifiers[:3]:
            hits = await self._store.keyword_search(ident, k=k)
            for hit in hits:
                uid = hit.get("uid", "")
                if uid and uid not in seen_uids:
                    seen_uids.add(uid)
                    all_hits.append(hit)
        return all_hits

    @staticmethod
    def _fuse_results(
        keyword_hits: list[dict[str, Any]],
        semantic_matches: list[dict[str, Any]],
        k: int,
    ) -> list[dict[str, Any]]:
        """Merge keyword and semantic results, dedup by name+file, keyword hits first."""
        merged: list[dict[str, Any]] = []
        seen: set[str] = set()

        for hit in keyword_hits:
            key = f"{hit.get('name', '')}:{hit.get('file', '')}:{hit.get('line', '')}"
            if key not in seen:
                seen.add(key)
                merged.append({
                    "type": hit.get("type", ""),
                    "name": hit.get("name", ""),
                    "file": hit.get("file", ""),
                    "line": hit.get("line", 0),
                    "score": hit.get("score", 1.0),
                    "signature": hit.get("signature", ""),
                    "docstring": hit.get("docstring", ""),
                    "match_source": "keyword",
                })

        for m in semantic_matches:
            key = f"{m.get('name', '')}:{m.get('file', '')}:{m.get('line', '')}"
            if key not in seen:
                seen.add(key)
                entry = dict(m)
                entry["match_source"] = "semantic"
                merged.append(entry)

        merged.sort(key=lambda x: x.get("score", 0), reverse=True)
        return merged[:k]

    async def _expand_graph(
        self,
        matches: list[dict[str, Any]],
        expand_depth: int,
        include_callers: bool,
        include_callees: bool,
    ) -> list[dict[str, Any]]:
        """Expand matched entities through graph relationships."""
        graph_context: list[dict[str, Any]] = []
        seen_names: set[str] = set()

        for match in matches:
            name = match.get("name", "")
            entity_type = match.get("type", "")

            if name in seen_names or not name:
                continue
            seen_names.add(name)

            if entity_type == str(NodeLabel.FUNCTION) or entity_type == "Function":
                if include_callees:
                    callees = await self._graph.find_call_chain(name, depth=expand_depth, direction="downstream")
                    for item in callees.data:
                        item["relationship"] = "called_by"
                        item["source"] = name
                        graph_context.append(item)

                if include_callers:
                    callers = await self._graph.find_call_chain(name, depth=expand_depth, direction="upstream")
                    for item in callers.data:
                        item["relationship"] = "calls"
                        item["source"] = name
                        graph_context.append(item)

            elif entity_type == str(NodeLabel.CLASS) or entity_type == "Class":
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    item["relationship"] = "method_of"
                    item["source"] = name
                    graph_context.append(item)

                children = await self._graph.find_inheritance_tree(name, direction="children")
                for item in children.data:
                    item["relationship"] = "subclass_of"
                    item["source"] = name
                    graph_context.append(item)

        return self._deduplicate(graph_context)

    async def search_keyword_only(self, query_text: str, k: int = 10) -> list[dict[str, Any]]:
        """Convenience method: keyword-only search (no vector)."""
        identifiers = _extract_identifiers(query_text)
        if not identifiers:
            identifiers = [query_text.strip()]
        return await self._keyword_search_multi(identifiers, k)

    async def find_related_to_file(self, file_path: str) -> HybridResult:
        """Find all entities in a file and their graph relationships."""
        entities = await self._graph.find_file_entities(file_path)

        graph_context: list[dict[str, Any]] = []
        for entity in entities.data:
            name = entity.get("name", "")
            entity_type = entity.get("type", "")

            if entity_type == "Function":
                callees = await self._graph.find_call_chain(name, depth=1, direction="downstream")
                for item in callees.data:
                    item["relationship"] = "called_by"
                    item["source"] = name
                    graph_context.append(item)

            elif entity_type == "Class":
                methods = await self._graph.find_class_methods(name)
                for item in methods.data:
                    item["relationship"] = "method_of"
                    item["source"] = name
                    graph_context.append(item)

        return HybridResult(
            semantic_matches=[{"type": e.get("type", ""), "name": e.get("name", "")} for e in entities.data],
            graph_context=self._deduplicate(graph_context),
            query_text=f"file:{file_path}",
            total=len(entities.data) + len(graph_context),
        )

    @staticmethod
    def _deduplicate(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        unique: list[dict[str, Any]] = []
        for item in items:
            key = f"{item.get('name', '')}:{item.get('file', '')}:{item.get('line', '')}"
            if key not in seen:
                seen.add(key)
                unique.append(item)
        return unique
