"""Selective wiki regeneration driven by repository diffs (incremental updates)."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Protocol

from store.schema import EdgeType, GraphNode, NodeLabel
from wiki.cache import WikiCache
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import WikiDataCollector
from wiki.models import PageType, WikiConfig, WikiPage

_EXPAND_EDGE_TYPES = [EdgeType.CALLS.value, EdgeType.INHERITS.value, EdgeType.IMPORTS.value]
_MODULE_CHILD_EDGE_TYPES = [EdgeType.CONTAINS.value]


@dataclass
class IncrementalUpdateResult:
    affected_pages: list[str]  # page paths regenerated
    neighbor_pages: list[str]  # pages with context-only update
    glossary_refreshed: bool  # True if full glossary rebuild triggered
    broken_refs_fixed: int  # number of cross-refs repaired
    pages_unchanged: int  # pages confirmed up-to-date
    graph_version: int  # new version after update


class IncrementalUpdatePort(Protocol):
    """Graph operations needed for incremental updates."""

    async def find_nodes_by_file(self, repository: str, file_path: str) -> list[GraphNode]: ...

    async def find_neighbors(self, uid: str, edge_types: list[str]) -> list[GraphNode]: ...

    async def get_graph_version(self, repository: str) -> int: ...

    async def increment_graph_version(self, repository: str) -> int: ...


_MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")


def _display_name(uid: str) -> str:
    parts = uid.rsplit(":", 2)
    if len(parts) >= 3:
        return str(parts[-2])
    return uid


def _wiki_path_for_node(node: GraphNode, page_type: PageType) -> str:
    """Mirror ``WikiComposer`` path rules for deterministic wiki paths."""
    if page_type == PageType.MODULE_OVERVIEW or node.label == NodeLabel.MODULE:
        path = str(node.properties.get("path") or node.properties.get("name") or "module")
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", path.strip("/"))
        return f"modules/{slug}.md"
    name = str(node.properties.get("name") or _display_name(node.uid))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)
    return f"classes/{safe}.md"


def _page_type_for_node(node: GraphNode) -> PageType:
    if node.label == NodeLabel.MODULE:
        return PageType.MODULE_OVERVIEW
    return PageType.CLASS_DETAIL


class WikiIncrementalUpdater:
    """Selective wiki regeneration based on code changes."""

    def __init__(
        self,
        graph: IncrementalUpdatePort,
        composer: WikiComposer,
        collector: WikiDataCollector,
        context_builder: WikiContextBuilder,
        cache: WikiCache,
    ) -> None:
        self._graph = graph
        self._composer = composer
        self._collector = collector
        self._context = context_builder
        self._cache = cache
        self._version_lock = asyncio.Lock()

    async def update_from_index_event(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
    ) -> IncrementalUpdateResult:
        """Hook for IncrementalIndexer: auto-trigger Wiki update after indexing.

        Reuses :meth:`update_from_diff` core logic, adding:

        1. Auto-fetch ``previous_glossary`` from cache (when supported)
        2. Refresh ``index.md`` and ``overview.md`` via composed wiki pages
        3. Append a line to the in-cache incremental update log
        """
        previous_glossary = (
            self._cache.get_glossary(repository) if hasattr(self._cache, "get_glossary") else None
        )
        result = await self.update_from_diff(
            repository,
            changed_files,
            config,
            previous_glossary=previous_glossary,
        )
        if result.affected_pages:
            await self._update_index_and_overview(repository, config, result)
            await self._append_update_log(repository, result)
        return result

    async def _update_index_and_overview(
        self,
        repository: str,
        config: WikiConfig,
        result: IncrementalUpdateResult,
    ) -> None:
        """Regenerate ``index.md`` and ``overview.md`` after an incremental body update."""
        if not hasattr(self._cache, "set_auxiliary_pages"):
            return

        index_page, overview_page = await self._composer.compose_incremental_navigation_pages(
            repository,
            sorted(result.affected_pages),
            sorted(result.neighbor_pages),
            result.graph_version,
            config,
        )
        self._cache.set_auxiliary_pages(repository, [index_page, overview_page])

    async def _append_update_log(self, repository: str, result: IncrementalUpdateResult) -> None:
        """Append incremental update summary to the in-cache wiki update log."""
        if not hasattr(self._cache, "append_wiki_update_log"):
            return
        pages_preview = ",".join(sorted(result.affected_pages)[:12])
        if len(result.affected_pages) > 12:
            pages_preview += ",..."
        line = (
            f"affected={len(result.affected_pages)} neighbors={len(result.neighbor_pages)} "
            f"glossary_refreshed={result.glossary_refreshed} broken_refs_fixed={result.broken_refs_fixed} "
            f"graph_version={result.graph_version} pages=[{pages_preview}]"
        )
        self._cache.append_wiki_update_log(repository, line)

    async def update_from_diff(
        self,
        repository: str,
        changed_files: list[tuple[str, str | None, str | None]],
        config: WikiConfig,
        *,
        previous_glossary: dict[str, str] | None = None,
    ) -> IncrementalUpdateResult:
        """
        Steps:
        1. Diff Extraction → already provided as changed_files
        2. File → Graph Node Mapping via DEFINED_IN edges
        3. Neighbor Expansion (1-hop via CALLS|INHERITS|IMPORTS)
        4. Wiki Page Resolution (node UID → page path)
        5. Selective Regeneration
        6. Consistency Guard (glossary drift, broken refs, stale parent context)
        """
        if not changed_files:
            ver = await self._graph.get_graph_version(repository)
            return IncrementalUpdateResult(
                affected_pages=[],
                neighbor_pages=[],
                glossary_refreshed=False,
                broken_refs_fixed=0,
                pages_unchanged=0,
                graph_version=ver,
            )

        deleted_paths: list[str] = []
        active_paths: list[str] = []
        for status, old_path, new_path in changed_files:
            st = status.upper()
            if st == "D":
                if old_path:
                    deleted_paths.append(old_path)
            else:
                p = new_path or old_path
                if p:
                    active_paths.append(p)

        uid_to_node: dict[str, GraphNode] = {}
        deleted_uids: set[str] = set()
        active_seed_uids: set[str] = set()

        for fp in deleted_paths:
            for n in await self._graph.find_nodes_by_file(repository, fp):
                uid_to_node[n.uid] = n
                deleted_uids.add(n.uid)

        for fp in active_paths:
            for n in await self._graph.find_nodes_by_file(repository, fp):
                uid_to_node[n.uid] = n
                active_seed_uids.add(n.uid)

        seed_uids = active_seed_uids | deleted_uids
        expanded_uids = await self._expand_neighbors(seed_uids, uid_to_node)

        regeneration_uids = (expanded_uids | active_seed_uids) - deleted_uids
        regeneration_uids |= await self._module_pages_over_threshold(repository, regeneration_uids, uid_to_node)

        neighbor_only_uids = regeneration_uids - active_seed_uids - deleted_uids

        old_glossary = dict(previous_glossary or {})
        module_names, entry_points = self._glossary_inputs(uid_to_node, regeneration_uids, deleted_uids)
        new_glossary = await self._context.build_glossary(module_names, entry_points)
        glossary_refreshed = await self._check_glossary_drift(old_glossary, new_glossary)

        neighbor_page_paths = [
            _wiki_path_for_node(uid_to_node[u], _page_type_for_node(uid_to_node[u]))
            for u in sorted(neighbor_only_uids)
            if u in uid_to_node
        ]

        nodes_to_process = [
            uid_to_node[u]
            for u in sorted(regeneration_uids)
            if u not in deleted_uids and u in uid_to_node
        ]

        pages_out: list[WikiPage] = []
        affected_paths: list[str] = []

        for node in nodes_to_process:
            pd = await self._collector.collect(repository, node)
            pt = _page_type_for_node(node)
            parent_ctx = ""
            if node.uid in neighbor_only_uids:
                parent_ctx = await self._context.build_repository_context(module_names)
            page = await self._composer.compose_page(
                pd,
                pt,
                config,
                parent_context=parent_ctx,
                glossary=new_glossary,
            )
            pages_out.append(page)
            affected_paths.append(page.path)

        deleted_page_paths = {
            _wiki_path_for_node(uid_to_node[u], _page_type_for_node(uid_to_node[u]))
            for u in deleted_uids
            if u in uid_to_node
        }
        pages_out, broken_n = self._fix_broken_refs(pages_out, deleted_page_paths)

        self._cache.invalidate(repository)

        if pages_out and hasattr(self._cache, "set_auxiliary_pages"):
            self._cache.set_auxiliary_pages(repository, pages_out)

        new_version = await self._increment_version(repository)

        if hasattr(self._cache, "set_glossary"):
            self._cache.set_glossary(repository, new_glossary)

        return IncrementalUpdateResult(
            affected_pages=sorted(set(affected_paths)),
            neighbor_pages=sorted(set(neighbor_page_paths)),
            glossary_refreshed=glossary_refreshed,
            broken_refs_fixed=broken_n,
            pages_unchanged=0,
            graph_version=new_version,
        )

    def _glossary_inputs(
        self,
        uid_to_node: dict[str, GraphNode],
        regen_uids: set[str],
        deleted_uids: set[str],
    ) -> tuple[list[str], list[str]]:
        modules: set[str] = set()
        entries: list[str] = []
        for uid, node in uid_to_node.items():
            if uid in deleted_uids:
                continue
            if node.label == NodeLabel.MODULE:
                p = str(node.properties.get("path") or node.properties.get("name") or "")
                if p:
                    modules.add(p)
            elif node.label == NodeLabel.CLASS:
                fq = str(node.properties.get("fqn") or node.properties.get("name") or "")
                if fq:
                    entries.append(fq)
                mp = node.properties.get("module_path")
                if isinstance(mp, str) and mp:
                    modules.add(mp)
        for uid in regen_uids:
            n = uid_to_node.get(uid)
            if n is None or n.label != NodeLabel.CLASS:
                continue
            mp = n.properties.get("module_path")
            if isinstance(mp, str) and mp:
                modules.add(mp)
        return sorted(modules), entries[:50]

    async def _module_pages_over_threshold(
        self,
        repository: str,
        regeneration_uids: set[str],
        uid_to_node: dict[str, GraphNode],
    ) -> set[str]:
        """If >30%% of classes in a module are affected, add the module overview page."""
        extra: set[str] = set()
        # group affected classes by module uid
        module_to_affected: dict[str, set[str]] = {}
        for uid in regeneration_uids:
            n = uid_to_node.get(uid)
            if n is None or n.label != NodeLabel.CLASS:
                continue
            mod_uid = n.properties.get("module_uid")
            if not isinstance(mod_uid, str) or not mod_uid:
                continue
            module_to_affected.setdefault(mod_uid, set()).add(uid)

        for mod_uid, aff in module_to_affected.items():
            kids = await self._graph.find_neighbors(mod_uid, _MODULE_CHILD_EDGE_TYPES)
            class_uids = {c.uid for c in kids if c.label == NodeLabel.CLASS}
            if not class_uids:
                continue
            affected_in_mod = len(aff & class_uids)
            ratio = affected_in_mod / len(class_uids)
            if ratio > 0.30:
                mod_node = uid_to_node.get(mod_uid)
                if mod_node is None or mod_node.label != NodeLabel.MODULE:
                    sample = next((uid_to_node[u] for u in aff if u in uid_to_node), None)
                    mp = sample.properties.get("module_path") if sample else None
                    if isinstance(mp, str) and mp:
                        mod_node = GraphNode(
                            label=NodeLabel.MODULE,
                            properties={"path": mp, "name": mp.rsplit("/", 1)[-1]},
                            uid=mod_uid,
                        )
                        uid_to_node[mod_uid] = mod_node
                    else:
                        continue
                extra.add(mod_uid)
                uid_to_node.setdefault(mod_uid, mod_node)
        return extra

    async def _map_files_to_nodes(self, repository: str, file_paths: list[str]) -> set[str]:
        """Map changed file paths to graph node UIDs."""
        out: set[str] = set()
        for fp in file_paths:
            for n in await self._graph.find_nodes_by_file(repository, fp):
                out.add(n.uid)
        return out

    async def _expand_neighbors(self, uids: set[str], uid_to_node: dict[str, GraphNode]) -> set[str]:
        """1-hop neighbor expansion for context propagation."""
        out = set(uids)
        for uid in uids:
            neigh = await self._graph.find_neighbors(uid, _EXPAND_EDGE_TYPES)
            for n in neigh:
                uid_to_node[n.uid] = n
                out.add(n.uid)
        return out

    def _resolve_page_paths(self, nodes: list[GraphNode]) -> dict[str, str]:
        """Map node UIDs to wiki page paths."""
        out: dict[str, str] = {}
        for n in nodes:
            pt = _page_type_for_node(n)
            out[n.uid] = _wiki_path_for_node(n, pt)
        return out

    async def _check_glossary_drift(self, old_glossary: dict[str, str], new_glossary: dict[str, str]) -> bool:
        """Return True if >20%% terms changed, triggering full rebuild."""
        all_keys = old_glossary.keys() | new_glossary.keys()
        total = len(all_keys)
        if total == 0:
            return False
        changed = 0
        for k in all_keys:
            if k not in old_glossary or k not in new_glossary:
                changed += 1
            elif old_glossary[k] != new_glossary[k]:
                changed += 1
        return (changed / total) > 0.20

    def _fix_broken_refs(self, pages: list[WikiPage], deleted_paths: set[str]) -> tuple[list[WikiPage], int]:
        """Remove cross-ref links that point to known-deleted wiki pages."""
        fixed_pages: list[WikiPage] = []
        fixes = 0
        for page in pages:
            content = page.content

            def repl(m: re.Match[str]) -> str:
                nonlocal fixes
                text, path = m.group(1), m.group(2).strip()
                if path.startswith("http://") or path.startswith("https://") or path.startswith("#"):
                    return m.group(0)
                normalized = path.split("#", 1)[0]
                if normalized.endswith(".md") and normalized in deleted_paths:
                    fixes += 1
                    return text
                return m.group(0)

            new_content = _MD_LINK_RE.sub(repl, content)
            if new_content != content:
                fixed_pages.append(
                    WikiPage(
                        path=page.path,
                        title=page.title,
                        page_type=page.page_type,
                        content=new_content,
                        diagrams=page.diagrams,
                        source_locations=page.source_locations,
                        metadata=page.metadata,
                        method_locations=page.method_locations,
                    )
                )
            else:
                fixed_pages.append(page)
        return fixed_pages, fixes

    async def _increment_version(self, repository: str) -> int:
        """Atomically increment graph version using asyncio.Lock."""
        async with self._version_lock:
            return await self._graph.increment_graph_version(repository)
