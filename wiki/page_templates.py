"""Template rendering for extended wiki ``PageType`` variants (graph-backed Markdown)."""

from __future__ import annotations

import re
from collections.abc import Mapping

from store.schema import EdgeType, GraphEdge, GraphNode
from wiki.composer import _primary_name
from wiki.diagram_gen import (
    generate_data_flow_diagram,
    generate_layered_architecture_diagram,
    generate_module_dependency_flowchart,
)
from wiki.models import PageType, SourceLocation, WikiConfig, WikiDiagram, WikiPage, WikiPageMetadata
from wiki.repo_composer import ArchitectureLayer, _wiki_architecture_path, _wiki_repo_overview_path

_LAYER_DISPLAY: dict[ArchitectureLayer, str] = {
    ArchitectureLayer.API: "API Layer",
    ArchitectureLayer.SERVICE: "Service Layer",
    ArchitectureLayer.DATA: "Data Layer",
    ArchitectureLayer.INFRASTRUCTURE: "Infrastructure Layer",
}

_KNOWN_FRAMEWORK_KEYWORDS = (
    "fastapi",
    "flask",
    "django",
    "starlette",
    "spring",
    "springboot",
    "hibernate",
    "express",
    "nestjs",
    "ktor",
)


def _source_location(node: GraphNode, repository: str) -> SourceLocation:
    props = node.properties
    file_path = str(props.get("file") or props.get("path") or "")
    start_line = int(props.get("start_line") or 0)
    end_line = int(props.get("end_line") or start_line)
    fqn = str(props.get("fqn") or props.get("name") or node.uid)
    return SourceLocation(
        file_path=file_path or ".",
        start_line=start_line,
        end_line=end_line,
        fqn=fqn,
        repository=repository,
    )


def _slug(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", text.strip()).strip("_") or "page"


def _is_public_function(fn: GraphNode) -> bool:
    raw = fn.properties.get("visibility")
    if raw is None:
        return True
    return str(raw).lower() != "private"


class WikiPageTemplates:
    """Template registry for generating page content by ``PageType``."""

    @staticmethod
    def render_architecture_overview(
        repository: str,
        layers: Mapping[ArchitectureLayer, list[GraphNode]],
        inter_module_edges: list[GraphEdge],
        tech_stack: dict[str, list[str]],
        config: WikiConfig,
    ) -> WikiPage:
        """Generate ``ARCHITECTURE`` overview page with layered and inter-module diagrams."""
        ordered_layers = (
            ArchitectureLayer.API,
            ArchitectureLayer.SERVICE,
            ArchitectureLayer.DATA,
            ArchitectureLayer.INFRASTRUCTURE,
        )
        layer_title_to_modules: dict[str, list[str]] = {}
        uid_to_label: dict[str, str] = {}
        for layer in ordered_layers:
            nodes = list(layers.get(layer, []))
            if not nodes:
                continue
            title = _LAYER_DISPLAY[layer]
            names = [_primary_name(n) for n in sorted(nodes, key=lambda x: _primary_name(x).lower())]
            layer_title_to_modules[title] = names
            for n in nodes:
                uid_to_label[n.uid] = _primary_name(n)

        layer_raw = generate_layered_architecture_diagram(layer_title_to_modules)
        layer_diag = WikiDiagram(
            diagram_type=layer_raw.diagram_type,
            content=layer_raw.content,
            title="System Layers",
        )

        mod_names = sorted({n for names in layer_title_to_modules.values() for n in names})
        dep_pairs: list[tuple[str, str]] = []
        for e in inter_module_edges:
            if e.edge_type != EdgeType.IMPORTS:
                continue
            s = uid_to_label.get(e.source_uid)
            t = uid_to_label.get(e.target_uid)
            if s and t:
                dep_pairs.append((s, t))

        dep_raw = generate_module_dependency_flowchart(mod_names, dep_pairs)
        dep_diag = WikiDiagram(
            diagram_type=dep_raw.diagram_type,
            content=dep_raw.content,
            title="Inter-Module Dependencies",
        )

        detail_lines: list[str] = ["## Layer Details", ""]
        for layer in ordered_layers:
            nodes = list(layers.get(layer, []))
            if not nodes:
                continue
            label = _LAYER_DISPLAY[layer]
            mods = ", ".join(f"`{_primary_name(n)}`" for n in sorted(nodes, key=lambda x: _primary_name(x).lower()))
            resp = ""
            first = nodes[0]
            r = first.properties.get("description")
            if isinstance(r, str) and r.strip():
                resp = f" Typical responsibilities include: {r.strip()}"
            detail_lines.append(f"- **{label}**: {mods}.{resp}")

        lang = ", ".join(f"`{x}`" for x in tech_stack.get("languages", [])) or "_None detected_"
        fw = ", ".join(f"`{x}`" for x in tech_stack.get("frameworks", [])) or "_None detected_"
        tech_block = "\n".join(
            [
                "## Technology Stack",
                "",
                f"- **Languages**: {lang}",
                f"- **Frameworks**: {fw}",
                "",
            ]
        )

        overview = (
            f"This page summarizes the layered architecture of `{repository}` using graph-derived modules "
            "and import relationships."
        )
        body = "\n".join(
            [
                f"# Architecture overview: {repository}",
                "",
                "## Overview",
                "",
                overview,
                "",
                *detail_lines,
                "",
                tech_block,
            ]
        ).rstrip() + "\n"

        node_count = sum(len(v) for v in layers.values())
        meta = WikiPageMetadata(
            node_count=node_count,
            edge_count=len(inter_module_edges),
            generation_mode=config.mode,
            fallback_tier=3,
        )
        loc = SourceLocation(".", 0, 0, f"{repository}.architecture", repository)
        for lv in layers.values():
            if lv:
                loc = _source_location(lv[0], repository)
                break

        return WikiPage(
            path=_wiki_architecture_path(),
            title=f"{repository} architecture",
            page_type=PageType.ARCHITECTURE,
            content=body,
            diagrams=[layer_diag, dep_diag],
            source_locations=[loc],
            metadata=meta,
        )

    @staticmethod
    def render_data_flow(
        flow_name: str,
        entry_point: GraphNode,
        call_chain: list[tuple[GraphNode, GraphEdge | None]],
        config: WikiConfig,
    ) -> WikiPage:
        """Generate a ``DATA_FLOW`` page from an ordered call chain."""
        path = f"flows/{_slug(flow_name)}.md"
        title = f"Flow: {flow_name}"
        entry_loc = _source_location(entry_point, config.repository)

        if not call_chain:
            body = "\n".join(
                [
                    f"# Data flow: `{flow_name}`",
                    "",
                    "## Overview",
                    "",
                    f"Entry `{_primary_name(entry_point)}` has _No call chain segments_ to trace.",
                    "",
                ]
            )
            meta = WikiPageMetadata(
                node_count=1,
                edge_count=0,
                generation_mode=config.mode,
                fallback_tier=3,
            )
            return WikiPage(
                path=path,
                title=title,
                page_type=PageType.DATA_FLOW,
                content=body,
                diagrams=[],
                source_locations=[entry_loc],
                metadata=meta,
            )

        nodes_ordered = [pair[0] for pair in call_chain]
        stage_labels = [_primary_name(n) for n in nodes_ordered]
        df_edges = [(stage_labels[i], stage_labels[i + 1]) for i in range(len(stage_labels) - 1)]

        df_raw = generate_data_flow_diagram(stage_labels, df_edges)
        flow_diag = WikiDiagram(diagram_type=df_raw.diagram_type, content=df_raw.content, title="Flow Diagram")

        overview = (
            f"This flow starts at `{_primary_name(entry_point)}` and follows "
            f"{len(nodes_ordered)} stage(s) along CALLS edges."
        )

        stage_rows = ["| Component | Input | Output | Source |", "| --- | --- | --- | --- |"]
        for i, n in enumerate(nodes_ordered):
            src_link = _source_location(n, config.repository).to_source_link()
            n_in = "-"
            n_out = "-"
            if i > 0:
                n_in = f"`{stage_labels[i - 1]}`"
            if i + 1 < len(stage_labels):
                n_out = f"`{stage_labels[i + 1]}`"
            stage_rows.append(f"| `{_primary_name(n)}` | {n_in} | {n_out} | {src_link} |")

        xf_rows = ["| Step | Transformation | Details |", "| --- | --- | --- |"]
        for i in range(len(nodes_ordered) - 1):
            a, b = nodes_ordered[i], nodes_ordered[i + 1]
            xf_rows.append(
                f"| {i + 1} | `{_primary_name(a)}` → `{_primary_name(b)}` | CALLS edge between stages |"
            )

        body = "\n".join(
            [
                f"# Data flow: `{flow_name}`",
                "",
                "## Overview",
                "",
                overview,
                "",
                "## Stages",
                "",
                *stage_rows,
                "",
                "## Data Transformations",
                "",
                *xf_rows,
                "",
            ]
        )

        edge_count = sum(1 for _, e in call_chain if e is not None)
        meta = WikiPageMetadata(
            node_count=len(nodes_ordered),
            edge_count=edge_count,
            generation_mode=config.mode,
            fallback_tier=3,
        )

        method_locs = [_source_location(n, config.repository) for n in nodes_ordered]
        return WikiPage(
            path=path,
            title=title,
            page_type=PageType.DATA_FLOW,
            content=body,
            diagrams=[flow_diag],
            source_locations=[entry_loc],
            metadata=meta,
            method_locations=method_locs,
        )

    @staticmethod
    def render_api_reference(
        module: GraphNode,
        public_functions: list[GraphNode],
        config: WikiConfig,
    ) -> WikiPage:
        """Generate ``API_REFERENCE`` Markdown for public module functions."""
        mod_name = _primary_name(module)
        slug = _slug(mod_name)
        path = f"api-reference/{slug}.md"

        rows = ["| Name | Signature | Description | Source |", "| --- | --- | --- | --- |"]
        visible = [fn for fn in public_functions if _is_public_function(fn)]
        for fn in sorted(visible, key=lambda f: str(f.properties.get("name") or f.uid)):
            name = str(fn.properties.get("name") or _primary_name(fn))
            sig = str(fn.properties.get("signature") or "")
            desc_raw = fn.properties.get("docstring")
            desc = str(desc_raw).strip() if isinstance(desc_raw, str) else ""
            src = _source_location(fn, config.repository).to_source_link()
            rows.append(f"| `{name}` | `{sig}` | {desc or '_'} | {src} |")

        body = "\n".join(
            [
                f"# API reference: `{mod_name}`",
                "",
                "## Public functions",
                "",
                *rows,
                "",
            ]
        )

        meta = WikiPageMetadata(
            node_count=1 + len(visible),
            edge_count=0,
            generation_mode=config.mode,
            fallback_tier=3,
        )
        mod_loc = _source_location(module, config.repository)
        fn_locs = [_source_location(fn, config.repository) for fn in visible]

        return WikiPage(
            path=path,
            title=f"{mod_name} API",
            page_type=PageType.API_REFERENCE,
            content=body,
            diagrams=[],
            source_locations=[mod_loc],
            metadata=meta,
            method_locations=fn_locs,
        )

    @staticmethod
    def render_repo_overview(
        repository: str,
        modules: list[GraphNode],
        total_pages: int,
        module_stats: dict[str, dict[str, int]],
        config: WikiConfig,
    ) -> WikiPage:
        """Generate enhanced ``REPO_OVERVIEW`` page content."""
        arch_link = _wiki_architecture_path()
        rows = ["| Module | Description | Classes | Functions |", "| --- | --- | --- | --- |"]
        for m in sorted(modules, key=lambda x: _primary_name(x).lower()):
            mn = _primary_name(m)
            desc_raw = m.properties.get("description")
            desc = str(desc_raw).strip() if isinstance(desc_raw, str) else ""
            st = module_stats.get(mn, {})
            cls_n = int(st.get("classes", 0))
            fn_n = int(st.get("functions", 0))
            rows.append(f"| `{mn}` | {desc or '_'} | {cls_n} | {fn_n} |")

        body = "\n".join(
            [
                f"# {repository}",
                "",
                "## Overview",
                "",
                f"This repository contains **{len(modules)}** modules and **{total_pages}** wiki page(s).",
                "",
                "## Architecture",
                "",
                f"See the [Architecture Overview]({arch_link}) for layered structure and dependencies.",
                "",
                "## Module index",
                "",
                *rows,
                "",
                "## Quick links",
                "",
                f"- [Architecture Overview]({arch_link})",
                "",
            ]
        )

        meta = WikiPageMetadata(
            node_count=len(modules),
            edge_count=0,
            generation_mode=config.mode,
            fallback_tier=3,
        )
        loc = SourceLocation(".", 0, 0, f"{repository}.repo", repository)

        return WikiPage(
            path=_wiki_repo_overview_path(repository),
            title=repository,
            page_type=PageType.REPO_OVERVIEW,
            content=body,
            diagrams=[],
            source_locations=[loc],
            metadata=meta,
        )

    @staticmethod
    def detect_tech_stack(modules: list[GraphNode], edges: list[GraphEdge]) -> dict[str, list[str]]:
        """Infer languages from file extensions and frameworks from import-like edges."""
        languages: set[str] = set()

        def ext_lang(path: str) -> None:
            lower = path.lower()
            if lower.endswith(".py"):
                languages.add("python")
            elif lower.endswith(".java"):
                languages.add("java")
            elif lower.endswith(".kt") or lower.endswith(".kts"):
                languages.add("kotlin")
            elif lower.endswith(".go"):
                languages.add("go")
            elif lower.endswith((".ts", ".tsx")):
                languages.add("typescript")
            elif lower.endswith((".js", ".jsx", ".mjs", ".cjs")):
                languages.add("javascript")

        for m in modules:
            fp = str(m.properties.get("file") or "")
            pp = str(m.properties.get("path") or "")
            ext_lang(fp)
            ext_lang(pp)

        frameworks: set[str] = set()
        for m in modules:
            mblob = (
                f"{m.properties.get('name', '')} {m.properties.get('path', '')} {m.properties.get('file', '')}"
            ).lower()
            for kw in _KNOWN_FRAMEWORK_KEYWORDS:
                if kw in mblob:
                    frameworks.add(kw)

        for e in edges:
            if e.edge_type != EdgeType.IMPORTS:
                continue
            blob = f"{e.source_uid} {e.target_uid}".lower()
            for v in e.properties.values():
                blob += " " + str(v).lower()
            for uid in (e.source_uid, e.target_uid):
                segments = uid.split(":")
                if len(segments) >= 3:
                    blob += " " + segments[-2].lower()
            for kw in _KNOWN_FRAMEWORK_KEYWORDS:
                if kw in blob:
                    frameworks.add(kw)

        return {
            "languages": sorted(languages),
            "frameworks": sorted(frameworks),
        }


__all__ = ["WikiPageTemplates"]
