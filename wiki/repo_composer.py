"""Compose a full wiki for an entire repository (module discovery, ordering, cross-cutting pages)."""

from __future__ import annotations

import asyncio
import re
from collections import defaultdict, deque
from dataclasses import replace
from enum import StrEnum

from store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from wiki.composer import WikiComposer
from wiki.context import WikiContextBuilder
from wiki.data_collector import WikiDataCollector
from wiki.diagram_gen import generate_call_flowchart
from wiki.exporter import WikiExporter
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiConfig,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiStructure,
    WikiStructureNode,
)
from wiki.structure_planner import GraphQueryPort


def _path_key(node: GraphNode) -> str:
    p = node.properties.get("path")
    if isinstance(p, str) and p:
        return p.lower()
    n = node.properties.get("name")
    if isinstance(n, str) and n:
        return n.lower()
    return node.uid.lower()


def _primary_name(node: GraphNode) -> str:
    raw = node.properties.get("name")
    if isinstance(raw, str) and raw:
        return raw
    raw_path = node.properties.get("path")
    if isinstance(raw_path, str) and raw_path:
        return raw_path.strip("/").split("/")[-1] or raw_path
    return node.uid


def _source_for_node(node: GraphNode, repository: str) -> SourceLocation:
    props = node.properties
    fp = str(props.get("file") or props.get("path") or "")
    start = int(props.get("start_line") or 0)
    end = int(props.get("end_line") or start)
    fqn = str(props.get("fqn") or props.get("name") or node.uid)
    return SourceLocation(
        file_path=fp or "unknown",
        start_line=start,
        end_line=end,
        fqn=fqn,
        repository=repository,
    )


def _wiki_repo_overview_path(repository: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", repository.strip())
    return f"overview/{slug}.md"


def _wiki_architecture_path() -> str:
    return "architecture/overview.md"


def _wiki_data_flow_path(slug: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", slug.strip())
    return f"flows/{safe}.md"


MAX_CONCURRENT_MODULE_COMPOSE = 3


class ArchitectureLayer(StrEnum):
    API = "api"
    SERVICE = "service"
    DATA = "data"
    INFRASTRUCTURE = "infrastructure"


_API_SUBSTR = ("controller/", "handler/", "route/", "/api/", "api/")
_SERVICE_SUBSTR = ("service/", "business/", "usecase/")
_DATA_SUBSTR = ("repository/", "dao/", "/store/", "store/", "/model/", "model/")
_INFRA_SUBSTR = ("config/", "util/", "middleware/", "infra/")


class WikiRepoComposer:
    """Composes a complete wiki for an entire repository."""

    def __init__(
        self,
        graph: GraphQueryPort,
        composer: WikiComposer,
        collector: WikiDataCollector,
        exporter: WikiExporter,
        context_builder: WikiContextBuilder,
    ) -> None:
        self._graph = graph
        self._composer = composer
        self._collector = collector
        self._exporter = exporter
        self._ctx = context_builder

    def classify_layer(self, module: GraphNode, edges: list[GraphEdge]) -> ArchitectureLayer:
        """Classify module layer using path heuristics, then edge hints."""
        path = _path_key(module)

        if any(s in path for s in _API_SUBSTR):
            return ArchitectureLayer.API
        if any(s in path for s in _SERVICE_SUBSTR):
            return ArchitectureLayer.SERVICE
        if any(s in path for s in _DATA_SUBSTR):
            return ArchitectureLayer.DATA
        if any(s in path for s in _INFRA_SUBSTR):
            return ArchitectureLayer.INFRASTRUCTURE

        inbound_calls_other_modules = 0
        dbish_import = False
        import_inbound = 0
        for e in edges:
            if e.edge_type == EdgeType.CALLS and e.target_uid == module.uid:
                inbound_calls_other_modules += 1
            if e.edge_type == EdgeType.IMPORTS:
                tgt = (e.target_uid + e.source_uid).lower()
                if e.target_uid == module.uid:
                    import_inbound += 1
                if any(x in tgt for x in ("sqlalchemy", "jpa", "hibernate", "orm", "jdbc", "database")):
                    dbish_import = True
        if dbish_import:
            return ArchitectureLayer.DATA
        if import_inbound >= 2:
            return ArchitectureLayer.SERVICE
        if inbound_calls_other_modules >= 2:
            return ArchitectureLayer.SERVICE

        return ArchitectureLayer.SERVICE

    def build_dependency_levels(self, modules: list[GraphNode], edges: list[GraphEdge]) -> list[list[GraphNode]]:
        """Kahn layers: each inner list may run concurrently; earlier layers finish before later ones."""
        mod_by_uid: dict[str, GraphNode] = {m.uid: m for m in modules}
        remaining: set[str] = set(mod_by_uid.keys())
        working_edges = [
            e
            for e in edges
            if e.edge_type == EdgeType.IMPORTS and e.source_uid in mod_by_uid and e.target_uid in mod_by_uid
        ]
        levels: list[list[GraphNode]] = []

        while remaining:
            in_deg = {u: 0 for u in remaining}
            for e in working_edges:
                src, tgt = e.source_uid, e.target_uid
                if src not in remaining or tgt not in remaining:
                    continue
                in_deg[src] += 1

            layer_uids = sorted([u for u in remaining if in_deg[u] == 0], key=lambda uid: _path_key(mod_by_uid[uid]))
            if layer_uids:
                levels.append([mod_by_uid[u] for u in layer_uids])
                for uid in layer_uids:
                    remaining.remove(uid)
                continue

            cycle_candidates = [
                e
                for e in working_edges
                if e.source_uid in remaining and e.target_uid in remaining
            ]
            if not cycle_candidates:
                rest = sorted(remaining, key=lambda x: _path_key(mod_by_uid[x]))
                levels.append([mod_by_uid[u] for u in rest])
                break

            def edge_deg(e: GraphEdge) -> int:
                return sum(
                    1
                    for x in working_edges
                    if e.source_uid in (x.source_uid, x.target_uid)
                    or e.target_uid in (x.source_uid, x.target_uid)
                )

            victim = min(cycle_candidates, key=lambda e: (edge_deg(e), e.source_uid, e.target_uid))
            working_edges.remove(victim)

        return levels

    def build_dependency_order(self, modules: list[GraphNode], edges: list[GraphEdge]) -> list[GraphNode]:
        """Topological order: dependencies before dependents (leaf modules first)."""
        return [n for lvl in self.build_dependency_levels(modules, edges) for n in lvl]

    def _detect_entry_points(self, modules: list[GraphNode], edges: list[GraphEdge]) -> list[GraphNode]:
        """Functions with no inbound CALLS from another function in the same module."""
        funcs = [n for n in modules if n.label == NodeLabel.FUNCTION]
        uid_to_mod: dict[str, str] = {}
        for f in funcs:
            mu = f.properties.get("module_uid")
            if isinstance(mu, str):
                uid_to_mod[f.uid] = mu

        inbound_within: set[str] = set()
        for e in edges:
            if e.edge_type != EdgeType.CALLS:
                continue
            sm = uid_to_mod.get(e.source_uid)
            tm = uid_to_mod.get(e.target_uid)
            if sm and tm and sm == tm:
                inbound_within.add(e.target_uid)

        return [f for f in funcs if f.uid not in inbound_within]

    async def _compose_module_pages(
        self,
        repository: str,
        module: GraphNode,
        config: WikiConfig,
        glossary: dict[str, str],
        parent_context: str,
    ) -> tuple[list[WikiPage], WikiStructureNode]:
        """Generate MODULE_OVERVIEW + CLASS_DETAIL + API_REFERENCE for one module."""
        pd = await self._collector.collect(repository, module)
        pages: list[WikiPage] = []

        mo = await self._composer.compose_page(
            pd,
            PageType.MODULE_OVERVIEW,
            config,
            parent_context=parent_context,
            glossary=glossary,
        )
        pages.append(mo)

        wiki_children: list[WikiStructureNode] = []

        for child in sorted(pd.children, key=lambda c: _primary_name(c)):
            if child.label == NodeLabel.CLASS:
                cpd = await self._collector.collect(repository, child)
                cc = await self._composer.compose_page(
                    cpd,
                    PageType.CLASS_DETAIL,
                    config,
                    parent_context=mo.content[:1200],
                    glossary=glossary,
                )
                pages.append(cc)
                wiki_children.append(
                    WikiStructureNode(path=cc.path, title=cc.title, page_type=PageType.CLASS_DETAIL, children=[]),
                )
            elif child.label != NodeLabel.MODULE:
                xpd = await self._collector.collect(repository, child)
                pg = await self._composer.compose_page(
                    xpd,
                    PageType.API_REFERENCE,
                    config,
                    parent_context=mo.content[:1200],
                    glossary=glossary,
                )
                pages.append(pg)
                wiki_children.append(
                    WikiStructureNode(path=pg.path, title=pg.title, page_type=PageType.API_REFERENCE, children=[]),
                )

        mod_struct = WikiStructureNode(
            path=mo.path,
            title=mo.title,
            page_type=PageType.MODULE_OVERVIEW,
            children=sorted(wiki_children, key=lambda n: n.title),
        )
        return pages, mod_struct

    async def _compose_architecture_overview(
        self,
        repository: str,
        layers: dict[ArchitectureLayer, list[GraphNode]],
        all_edges: list[GraphEdge],
        config: WikiConfig,
    ) -> WikiPage:
        """ARCHITECTURE page summarizing heuristic layers."""
        lines = [
            f"# Architecture ({repository})",
            "",
            "## Layers (heuristic)",
            "",
        ]
        for layer in (
            ArchitectureLayer.API,
            ArchitectureLayer.SERVICE,
            ArchitectureLayer.DATA,
            ArchitectureLayer.INFRASTRUCTURE,
        ):
            mods = layers.get(layer, [])
            names = ", ".join(f"`{_primary_name(m)}`" for m in sorted(mods, key=_path_key))
            lines.append(f"- **{layer.value}**: {names or '_none classified_'}")

        layers_body = "\n".join(lines)

        diagram_lines = ["flowchart TB"]
        lid = {
            ArchitectureLayer.API: "L_API",
            ArchitectureLayer.SERVICE: "L_SVC",
            ArchitectureLayer.DATA: "L_DATA",
            ArchitectureLayer.INFRASTRUCTURE: "L_INF",
        }
        for layer, node_id in lid.items():
            label = layer.value.replace("_", " ")
            diagram_lines.append(f'    {node_id}["{label}"]')
        diagram_lines.append("    L_API --> L_SVC --> L_DATA")
        diagram_lines.append("    L_INF -.-> L_SVC")

        diagram = WikiDiagram(
            diagram_type=DiagramType.DEPENDENCY_GRAPH,
            content="\n".join(diagram_lines) + "\n",
            title="Layer diagram",
        )

        meta = WikiPageMetadata(
            node_count=sum(len(v) for v in layers.values()),
            edge_count=len(all_edges),
            generation_mode=config.mode,
            fallback_tier=3,
        )
        src_loc = SourceLocation(".", 0, 0, f"{repository}.architecture", repository)
        for lv in layers.values():
            if lv:
                src_loc = _source_for_node(lv[0], repository)
                break
        return WikiPage(
            path=_wiki_architecture_path(),
            title=f"{repository} architecture",
            page_type=PageType.ARCHITECTURE,
            content=layers_body,
            diagrams=[diagram],
            source_locations=[src_loc],
            metadata=meta,
        )

    async def _compose_data_flow_pages(
        self,
        repository: str,
        modules: list[GraphNode],
        edges: list[GraphEdge],
        config: WikiConfig,
        entry_functions: list[GraphNode],
    ) -> tuple[list[WikiPage], list[WikiStructureNode]]:
        """DATA_FLOW pages from entry-point tracing along CALLS."""
        pages: list[WikiPage] = []
        structs: list[WikiStructureNode] = []
        calls = [e for e in edges if e.edge_type == EdgeType.CALLS]

        if not entry_functions:
            meta = WikiPageMetadata(node_count=0, edge_count=len(calls), generation_mode=config.mode, fallback_tier=3)
            slug = "summary"
            body = "# Data flow\n\n_No entry-point functions detected for intra-module call analysis._\n"
            flow_fqn = f"{repository}.flow"
            loc = SourceLocation(
                file_path=".",
                start_line=0,
                end_line=0,
                fqn=flow_fqn,
                repository=repository,
            )
            wp = WikiPage(
                path=_wiki_data_flow_path(slug),
                title="Data flow",
                page_type=PageType.DATA_FLOW,
                content=body,
                diagrams=[],
                source_locations=[loc],
                metadata=meta,
            )
            pages.append(wp)
            structs.append(WikiStructureNode(path=wp.path, title=wp.title, page_type=PageType.DATA_FLOW, children=[]))
            return pages, structs

        callees_by_caller: dict[str, list[str]] = defaultdict(list)
        for e in calls:
            callees_by_caller[e.source_uid].append(e.target_uid)

        used_slugs: set[str] = set()
        for fn in entry_functions:
            name = _primary_name(fn)
            fqn = str(fn.properties.get("fqn") or fn.properties.get("file") or fn.uid)
            slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", fqn.strip())
            if slug in used_slugs:
                slug = f"{slug}_{fn.uid.replace(':', '_')[-12:]}"
            used_slugs.add(slug)

            visited: set[str] = set()
            queue: deque[str] = deque([fn.uid])
            traced: list[str] = []
            while queue:
                uid = queue.popleft()
                if uid in visited:
                    continue
                visited.add(uid)
                traced.append(uid)
                for tgt in callees_by_caller.get(uid, []):
                    if tgt not in visited:
                        queue.append(tgt)

            focal = fn
            sub_edges = [e for e in calls if e.source_uid in visited and e.target_uid in visited]
            dg = generate_call_flowchart(focal, sub_edges)

            meta = WikiPageMetadata(
                node_count=len(traced),
                edge_count=len(sub_edges),
                generation_mode=config.mode,
                fallback_tier=3,
            )
            body = (
                f"# Data flow: `{name}`\n\n"
                f"Traced {len(traced)} function(s) along CALLS edges starting from this entry point.\n"
            )
            diag = WikiDiagram(
                diagram_type=dg.diagram_type,
                content=dg.content,
                title=dg.title or "Call trace",
            )
            wp = WikiPage(
                path=_wiki_data_flow_path(slug),
                title=f"Flow: {name}",
                page_type=PageType.DATA_FLOW,
                content=body,
                diagrams=[diag],
                source_locations=[_source_for_node(fn, repository)],
                metadata=meta,
            )
            pages.append(wp)
            structs.append(WikiStructureNode(path=wp.path, title=wp.title, page_type=PageType.DATA_FLOW, children=[]))

        return pages, structs

    def _filter_modules(self, raw: list[GraphNode]) -> list[GraphNode]:
        out: list[GraphNode] = []
        for m in raw:
            if m.label != NodeLabel.MODULE:
                continue
            pk = _path_key(m)
            if "test" in pk:
                continue
            if "vendor" in pk:
                continue
            out.append(m)
        return out

    def _apply_cross_links(self, pages: list[WikiPage]) -> list[WikiPage]:
        """Inject Markdown cross-links using exporter heuristics."""
        cmap = WikiExporter.build_entity_page_map(pages)
        updated: list[WikiPage] = []
        for p in pages:
            linked = self._exporter.auto_link_cross_references(p.content, cmap)
            updated.append(replace(p, content=linked))
        return updated

    async def compose_repo_wiki(self, repository: str, config: WikiConfig) -> tuple[list[WikiPage], WikiStructure]:
        """Full repo wiki generation."""
        raw_modules = await self._graph.list_repository_modules(repository)
        modules = self._filter_modules(raw_modules)
        import_edges = await self._graph.find_module_import_edges(repository)
        calls_edges = await self._graph.find_repository_calls_edges(repository)

        layers: dict[ArchitectureLayer, list[GraphNode]] = defaultdict(list)
        for m in modules:
            rel = [e for e in import_edges if e.source_uid == m.uid or e.target_uid == m.uid]
            lay = self.classify_layer(m, rel + calls_edges)
            layers[lay].append(m)

        levels = self.build_dependency_levels(modules, import_edges)

        module_summaries: dict[str, str] = {}
        module_names = [_primary_name(m) for m in modules]
        glossary = await self._ctx.build_glossary(module_names, module_names)
        repo_ctx = await self._ctx.build_repository_context(module_names)

        sem = asyncio.Semaphore(MAX_CONCURRENT_MODULE_COMPOSE)

        async def one_module(mod: GraphNode) -> tuple[list[WikiPage], WikiStructureNode]:
            async with sem:
                chain_ctx = ""
                for e in import_edges:
                    if e.edge_type == EdgeType.IMPORTS and e.source_uid == mod.uid:
                        dep_uid = e.target_uid
                        if dep_uid in module_summaries:
                            chain_ctx += module_summaries[dep_uid][:800] + "\n"
                parent_block = (repo_ctx + "\n\n" + chain_ctx).strip()
                pages_part, struct = await self._compose_module_pages(
                    repository,
                    mod,
                    config,
                    glossary,
                    parent_context=parent_block,
                )
                overview_snippet = next((p.content for p in pages_part if p.page_type == PageType.MODULE_OVERVIEW), "")
                module_summaries[mod.uid] = overview_snippet[:2000]
                return pages_part, struct

        module_pages: list[WikiPage] = []
        module_struct_nodes: list[WikiStructureNode] = []
        for level in levels:
            results = await asyncio.gather(*[one_module(m) for m in level])
            for plist, st in results:
                module_pages.extend(plist)
                module_struct_nodes.append(st)

        arch_page = await self._compose_architecture_overview(repository, layers, import_edges + calls_edges, config)

        mixed_for_entries: list[GraphNode] = list(modules)
        for m in modules:
            kids = await self._graph.find_children(repository, m.uid)
            for c in kids:
                if c.label == NodeLabel.FUNCTION:
                    props = dict(c.properties)
                    props["module_uid"] = m.uid
                    mixed_for_entries.append(GraphNode(label=c.label, properties=props, uid=c.uid))

        entry_fns = self._detect_entry_points(mixed_for_entries, calls_edges)
        flow_pages, flow_structs = await self._compose_data_flow_pages(
            repository,
            modules,
            calls_edges,
            config,
            entry_fns,
        )

        module_names_line = ", ".join(f"`{_primary_name(m)}`" for m in sorted(modules, key=_path_key))
        overview_body = (
            f"# {repository}\n\n"
            f"## Modules\n\n{module_names_line}\n\n"
            f"## Context\n\n{repo_ctx}"
            "\n\n## Glossary\n\n"
            + "\n".join(f"- **{k}**: {v}" for k, v in sorted(glossary.items()))
        )
        repo_meta = WikiPageMetadata(
            node_count=len(modules),
            edge_count=len(import_edges) + len(calls_edges),
            generation_mode=config.mode,
            fallback_tier=3,
        )
        repo_overview = WikiPage(
            path=_wiki_repo_overview_path(repository),
            title=repository,
            page_type=PageType.REPO_OVERVIEW,
            content=overview_body,
            diagrams=[],
            source_locations=[
                SourceLocation(
                    file_path=".",
                    start_line=0,
                    end_line=0,
                    fqn=f"{repository}.repo",
                    repository=repository,
                ),
            ],
            metadata=repo_meta,
        )

        all_pages = [repo_overview, arch_page, *flow_pages, *module_pages]
        all_pages = self._apply_cross_links(all_pages)

        arch_struct = WikiStructureNode(
            path=arch_page.path,
            title=arch_page.title,
            page_type=PageType.ARCHITECTURE,
            children=[],
        )
        root_children = [arch_struct, *flow_structs, *sorted(module_struct_nodes, key=lambda n: n.title)]
        root = WikiStructureNode(
            path="/",
            title=repository,
            page_type=PageType.REPO_OVERVIEW,
            children=root_children,
        )
        structure = WikiStructure(repository=repository, root=root, total_pages=len(all_pages))
        return all_pages, structure
