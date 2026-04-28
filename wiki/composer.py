"""Compose wiki pages from graph-backed page data with LLM / structural fallback tiers."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from log import get_logger
from store.schema import EdgeType, GraphNode, NodeLabel
from store.wiki_store import WikiStore
from wiki.context import LLMPort, WikiContextBuilder
from wiki.doc_wiki_fusion import create_source_doc_edges, find_related_docs, format_related_docs_for_prompt
from wiki.data_collector import PageData
from wiki.diagram_gen import generate_call_flowchart, generate_class_diagram, generate_dependency_graph
from wiki.memory_loop import MemoryLoop
from wiki.models import (
    ImportanceTier,
    PageType,
    SkeletonStrategy,
    SourceLocation,
    WikiConfig,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
    WikiPageSummary,
)
from wiki.wikilink_resolver import resolve_wikilinks

if TYPE_CHECKING:
    from wiki.wikilink_cache import WikiLinkCache

log = get_logger(__name__)

_PARENT_SYSTEM_PROMPT = (
    "You are a senior engineer writing a module overview. "
    "Synthesize the provided child component summaries into a cohesive description. "
    "Focus on how components work together, the module's overall purpose, and key design patterns. "
    "Use clear section headings (##). Output Markdown."
)


def _effective_wiki_language(language: str) -> str:
    """Normalize wiki language; unknown codes fall back to English templates."""
    return language if language in ("en", "zh") else "en"


_NAV_SIBLING_LIMIT = 10
_NAV_CHILD_LIMIT = 15


def render_navigation_section(page: WikiPage) -> str:
    """Render breadcrumbs and navigation links as Markdown."""
    if not page.navigation:
        return ""
    nav = page.navigation
    sections: list[str] = []
    if nav.breadcrumbs:
        crumb_links = " > ".join(f"[[{title}]]" for title, _path in nav.breadcrumbs)
        sections.append(f"> {crumb_links}")
    if nav.child_paths:
        shown = nav.child_paths[:_NAV_CHILD_LIMIT]
        remaining = len(nav.child_paths) - len(shown)
        sections.append("\n### Sub-components\n")
        for path in shown:
            sections.append(f"- [{path}]({path})")
        if remaining > 0:
            sections.append(f"\n*… and {remaining} more sub-components*")
    if nav.sibling_paths:
        shown = nav.sibling_paths[:_NAV_SIBLING_LIMIT]
        remaining = len(nav.sibling_paths) - len(shown)
        sections.append("\n### Related (same parent)\n")
        for path in shown:
            sections.append(f"- [{path}]({path})")
        if remaining > 0:
            sections.append(f"\n*… and {remaining} more siblings*")
    return "\n".join(sections)


def _display_name(uid: str) -> str:
    parts = uid.rsplit(":", 2)
    if len(parts) >= 3:
        return str(parts[-2])
    return uid


def _entity_names_for_doc_lookup(node: GraphNode) -> list[str]:
    names: list[str] = []
    raw = node.properties.get("name")
    if isinstance(raw, str) and raw.strip():
        names.append(raw.strip())
    fqn = node.properties.get("fqn")
    if isinstance(fqn, str) and fqn.strip():
        names.append(fqn.strip())
    return names


def _primary_name(node: GraphNode) -> str:
    raw = node.properties.get("name")
    if isinstance(raw, str) and raw:
        return raw
    raw_path = node.properties.get("path")
    if isinstance(raw_path, str) and raw_path:
        return raw_path.strip("/").split("/")[-1] or raw_path
    return _display_name(node.uid)


def _wiki_path(node: GraphNode, page_type: PageType) -> str:
    if page_type == PageType.MODULE_OVERVIEW or node.label == NodeLabel.MODULE:
        path = str(node.properties.get("path") or node.properties.get("name") or "module")
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "_", path.strip("/"))
        return f"modules/{slug}.md"
    name = str(node.properties.get("name") or _display_name(node.uid))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name)
    return f"classes/{safe}.md"


def _sorted_method_names(methods: list[GraphNode]) -> list[str]:
    names: list[str] = []
    for m in methods:
        n = m.properties.get("name")
        names.append(str(n) if isinstance(n, str) else _display_name(m.uid))
    return sorted(names)


class WikiComposer:
    """Turns ``PageData`` into a ``WikiPage`` using tiered description fallback."""

    def __init__(
        self,
        llm: LLMPort | None,
        context_builder: WikiContextBuilder,
        store: Any | None = None,
        wiki_store: WikiStore | None = None,
        memory_loop: MemoryLoop | None = None,
        wikilink_cache: "WikiLinkCache | None" = None,
    ) -> None:
        self._llm = llm
        self._ctx = context_builder
        self._store = store
        self._wiki_store = wiki_store or (WikiStore(store) if store is not None else None)
        self._memory_loop = memory_loop
        self._wikilink_cache = wikilink_cache

    async def compose_page(
        self,
        page_data: PageData,
        page_type: PageType,
        config: WikiConfig,
        parent_context: str = "",
        glossary: dict[str, str] | None = None,
        *,
        importance_tier: ImportanceTier | None = None,
        skeleton_strategy: SkeletonStrategy | None = None,
        skeleton_light_model: str | None = None,
    ) -> WikiPage | None:
        glossary = glossary or {}

        # Tier-aware dispatch for SKELETON entities
        if importance_tier == ImportanceTier.SKELETON and skeleton_strategy is not None:
            if skeleton_strategy == SkeletonStrategy.SKIP:
                return None
            if skeleton_strategy == SkeletonStrategy.TEMPLATE:
                node = page_data.node
                title = _primary_name(node)
                path = _wiki_path(node, page_type)
                eff_lang = _effective_wiki_language(config.language)
                description = self._tier3_structural(page_data, page_type, eff_lang)
                content = self._markdown_body(title, page_data, page_type, description)
                if self._wikilink_cache is not None:
                    entity_index = self._wikilink_cache.get_index()
                else:
                    entity_index = await self._wikilink_entity_index(config.repository)
                content = resolve_wikilinks(content, entity_index)
                diagrams = self._build_diagrams(page_data, page_type)
                meta = WikiPageMetadata(
                    node_count=self._estimate_node_count(page_data),
                    edge_count=len(page_data.edges),
                    generation_mode=config.mode,
                    fallback_tier=3,
                )
                return WikiPage(
                    path=path,
                    title=title,
                    page_type=page_type,
                    content=content,
                    diagrams=diagrams,
                    source_locations=[page_data.source_location],
                    metadata=meta,
                    method_locations=list(page_data.method_locations),
                )
            if skeleton_strategy == SkeletonStrategy.LIGHT_MODEL:
                return await self._compose_skeleton_light(
                    page_data,
                    page_type,
                    config,
                    skeleton_light_model=skeleton_light_model,
                )

        node = page_data.node
        title = _primary_name(node)
        path = _wiki_path(node, page_type)

        tier: int
        eff_lang = _effective_wiki_language(config.language)
        related_docs_block = ""
        doc_rows: list[dict[str, str]] = []
        if self._wiki_store is not None:
            doc_entities = _entity_names_for_doc_lookup(page_data.node)
            if doc_entities:
                doc_rows = await find_related_docs(self._wiki_store, doc_entities, limit=5)
                related_docs_block = format_related_docs_for_prompt(doc_rows, max_chars_per_doc=3000)
        memory_block = ""
        if self._memory_loop is not None:
            try:
                memory_block = await self._memory_loop.inject_into_generation(title, config.repository)
            except Exception as exc:  # noqa: BLE001 — optional enrichment
                log.warning("wiki_memory_inject_failed", error=str(exc))
        if page_data.business_summary and page_data.business_summary.strip():
            tier = 1
            description = page_data.business_summary.strip()
        elif config.mode == "structure":
            tier = 3
            description = self._tier3_structural(page_data, page_type, eff_lang)
        elif self._llm is not None:
            tier = 2
            description = await self._tier2_llm(
                page_data,
                page_type,
                parent_context,
                glossary,
                config,
                related_docs_block=related_docs_block,
                memory_block=memory_block,
            )
            if self._wiki_store is not None and not (
                page_data.business_summary and page_data.business_summary.strip()
            ):
                short_summary = description[:100].split("\n")[0].strip()
                if short_summary and page_data.node.uid:
                    try:
                        await self._wiki_store.update_node_property(
                            page_data.node.label,
                            page_data.node.uid,
                            "business_summary",
                            short_summary,
                        )
                    except Exception as exc:
                        log.warning(
                            "tier2_backfill_failed",
                            uid=page_data.node.uid,
                            error=str(exc),
                        )
        else:
            tier = 3
            description = self._tier3_structural(page_data, page_type, eff_lang)

        content = self._markdown_body(title, page_data, page_type, description)
        if self._wikilink_cache is not None:
            entity_index = self._wikilink_cache.get_index()
        else:
            entity_index = await self._wikilink_entity_index(config.repository)
        content = resolve_wikilinks(content, entity_index)
        diagrams = self._build_diagrams(page_data, page_type)
        meta = WikiPageMetadata(
            node_count=self._estimate_node_count(page_data),
            edge_count=len(page_data.edges),
            generation_mode=config.mode,
            fallback_tier=tier,
        )
        page = WikiPage(
            path=path,
            title=title,
            page_type=page_type,
            content=content,
            diagrams=diagrams,
            source_locations=[page_data.source_location],
            metadata=meta,
            method_locations=list(page_data.method_locations),
        )
        if self._wiki_store is not None and doc_rows:
            try:
                await create_source_doc_edges(
                    self._wiki_store,
                    repository=config.repository,
                    wiki_page_path=path,
                    docs=doc_rows,
                )
            except Exception as exc:
                log.warning(
                    "wiki_source_doc_edges_failed",
                    repository=config.repository,
                    path=path,
                    error=str(exc),
                )
        return page

    async def compose_parent_page(
        self,
        page_data: PageData,
        page_type: PageType,
        config: WikiConfig,
        child_summaries: list[WikiPageSummary],
    ) -> WikiPage:
        """Compose a parent module page using child summaries instead of raw code."""
        title = _primary_name(page_data.node)
        path = _wiki_path(page_data.node, page_type)
        eff_lang = _effective_wiki_language(config.language)

        if not self._llm or not child_summaries:
            description = self._tier3_structural(page_data, page_type, eff_lang)
            tier = 3
        else:
            children_context = "\n".join(
                f"- **{s.title}** ({s.importance_tier.value if s.importance_tier else 'unknown'}): {s.summary}"
                for s in child_summaries
            )
            lang_directive = "Generate documentation in English." if eff_lang == "en" else "请用中文生成文档。"
            prompt = (
                f"## Module: {title}\n\n"
                f"### Child Components ({len(child_summaries)} total):\n{children_context}\n\n"
                f"## Task\n{lang_directive}\n\n"
                "Write a module overview that:\n"
                "1. Describes the module's overall purpose and responsibility\n"
                "2. Explains how the child components work together\n"
                "3. Identifies key design patterns and architectural decisions\n"
                "4. Notes important entry points and external interfaces\n"
            )
            description = (await self._llm.generate(prompt, system=_PARENT_SYSTEM_PROMPT)).strip()
            tier = 2

        content = self._markdown_body(title, page_data, page_type, description)
        if self._wikilink_cache is not None:
            entity_index = self._wikilink_cache.get_index()
        else:
            entity_index = await self._wikilink_entity_index(config.repository)
        content = resolve_wikilinks(content, entity_index)
        diagrams = self._build_diagrams(page_data, page_type)
        meta = WikiPageMetadata(
            node_count=self._estimate_node_count(page_data),
            edge_count=len(page_data.edges),
            generation_mode=config.mode,
            fallback_tier=tier,
        )
        return WikiPage(
            path=path,
            title=title,
            page_type=page_type,
            content=content,
            diagrams=diagrams,
            source_locations=[page_data.source_location],
            metadata=meta,
            method_locations=list(page_data.method_locations),
        )

    async def compose_incremental_navigation_pages(
        self,
        repository: str,
        affected_pages: list[str],
        neighbor_pages: list[str],
        graph_version: int,
        config: WikiConfig,
    ) -> tuple[WikiPage, WikiPage]:
        """Build ``index.md`` and ``overview.md`` for incremental wiki refresh (P3)."""
        index_lines = [
            f"# {repository} wiki",
            "",
            "## Regenerated pages",
            "",
        ]
        affected_set = set(affected_pages)
        for p in affected_pages:
            index_lines.append(f"- [{p}]({p})")
        deduped_neighbors = [p for p in neighbor_pages if p not in affected_set]
        if deduped_neighbors:
            index_lines.extend(["", "## Context-only neighbors", ""])
            for p in deduped_neighbors:
                index_lines.append(f"- [{p}]({p})")
        index_body = "\n".join(index_lines).rstrip() + "\n"

        repo_ctx = await self._ctx.build_repository_context([])
        overview_lines = [
            f"# {repository} overview",
            "",
            f"_Graph version **{graph_version}** after the latest incremental wiki update._",
            "",
            repo_ctx.strip(),
        ]
        overview_body = "\n".join(overview_lines).strip() + "\n"

        meta_idx = WikiPageMetadata(
            node_count=len(affected_pages),
            edge_count=0,
            generation_mode=config.mode,
            fallback_tier=3,
        )
        meta_ov = WikiPageMetadata(
            node_count=0,
            edge_count=0,
            generation_mode=config.mode,
            fallback_tier=3,
        )
        loc_idx = SourceLocation(".", 0, 0, f"{repository}.wiki.index", repository)
        loc_ov = SourceLocation(".", 0, 0, f"{repository}.wiki.overview", repository)

        index_page = WikiPage(
            path="index.md",
            title=f"{repository} index",
            page_type=PageType.REPO_OVERVIEW,
            content=index_body,
            diagrams=[],
            source_locations=[loc_idx],
            metadata=meta_idx,
        )
        overview_page = WikiPage(
            path="overview.md",
            title=f"{repository} overview",
            page_type=PageType.REPO_OVERVIEW,
            content=overview_body,
            diagrams=[],
            source_locations=[loc_ov],
            metadata=meta_ov,
        )
        return index_page, overview_page

    async def _compose_skeleton_light(
        self,
        page_data: PageData,
        page_type: PageType,
        config: WikiConfig,
        *,
        skeleton_light_model: str | None = None,
    ) -> WikiPage:
        """Compose SKELETON entity using a lighter/cheaper LLM model."""
        node = page_data.node
        title = _primary_name(node)
        path = _wiki_path(node, page_type)
        eff_lang = _effective_wiki_language(config.language)

        if not self._llm:
            description = self._tier3_structural(page_data, page_type, eff_lang)
            tier = 3
        else:
            prompt = self._build_skeleton_light_prompt(page_data, page_type, eff_lang)
            light_model = (skeleton_light_model or "").strip() or None
            description = (
                await self._llm.generate(
                    prompt,
                    system="You are writing concise documentation. Be brief but accurate.",
                    model=light_model,
                )
            ).strip()
            tier = 2

        content = self._markdown_body(title, page_data, page_type, description)
        if self._wikilink_cache is not None:
            entity_index = self._wikilink_cache.get_index()
        else:
            entity_index = await self._wikilink_entity_index(config.repository)
        content = resolve_wikilinks(content, entity_index)
        diagrams = self._build_diagrams(page_data, page_type)
        meta = WikiPageMetadata(
            node_count=self._estimate_node_count(page_data),
            edge_count=len(page_data.edges),
            generation_mode=config.mode,
            fallback_tier=tier,
        )
        return WikiPage(
            path=path,
            title=title,
            page_type=page_type,
            content=content,
            diagrams=diagrams,
            source_locations=[page_data.source_location],
            metadata=meta,
            method_locations=list(page_data.method_locations),
        )

    def _build_skeleton_light_prompt(
        self,
        page_data: PageData,
        page_type: PageType,
        lang: str,
    ) -> str:
        """Build a shorter prompt for SKELETON entities."""
        name = _primary_name(page_data.node)
        code_snippet = ""
        if page_data.code_snippets:
            snippet = page_data.code_snippets[0]
            if hasattr(snippet, "source"):
                code_snippet = snippet.source[:500]
            elif isinstance(snippet, str):
                code_snippet = snippet[:500]
        lang_hint = "Generate in English." if lang == "en" else "请用中文生成。"
        return (
            f"Write a brief documentation summary for `{name}` ({page_type.value}).\n"
            f"Code preview:\n```\n{code_snippet}\n```\n"
            f"Include: one-line purpose, parameter list (if any), return type.\n"
            f"{lang_hint}\nKeep it under 150 words."
        )

    async def _wikilink_entity_index(self, repository: str) -> dict[str, str]:
        """Map WikiPage title -> in-app wiki URL for [[wikilink]] resolution."""
        if self._wiki_store is None:
            return {}
        result = await self._wiki_store.list_wiki_pages_all(repository)
        rows = getattr(result, "data", None) or []
        index: dict[str, str] = {}
        for row in rows:
            title = row.get("title")
            path = row.get("path")
            if not title or not path:
                continue
            t = str(title).strip()
            if not t:
                continue
            index[t] = f"/wiki?path={quote(str(path), safe='')}"
        return index

    def _estimate_node_count(self, page_data: PageData) -> int:
        return 1 + len(page_data.children) + len(page_data.methods)

    async def _tier2_llm(
        self,
        page_data: PageData,
        page_type: PageType,
        parent_context: str,
        glossary: dict[str, str],
        config: WikiConfig,
        *,
        related_docs_block: str = "",
        memory_block: str = "",
    ) -> str:
        assert self._llm is not None
        lang = _effective_wiki_language(config.language)
        style = self._ctx.build_style_sheet(config.language)
        ctx_block = self._ctx.build_page_context(
            parent_context,
            glossary,
            style,
            language=config.language,
        )
        entity = self._entity_digest(page_data, page_type)
        lang_directive = (
            "Generate documentation in English."
            if lang == "en"
            else "请用中文生成文档。"
        )
        doc_section = f"\n\n{related_docs_block}\n" if related_docs_block.strip() else ""
        memory_section = f"\n\n{memory_block}\n" if memory_block.strip() else ""
        prompt = (
            f"{ctx_block}\n\n"
            "## Task\n"
            f"{lang_directive}\n\n"
            f"Write a detailed documentation page for this {page_type.value.replace('_', ' ')}.\n"
            "Include:\n"
            "1. A concise overview of this entity's purpose and responsibility\n"
            "2. How its key methods/components work together (describe the workflow/process)\n"
            "3. Its relationships with other modules (who calls it, what it depends on)\n"
            "4. Any important design patterns or business logic\n\n"
            f"{entity}\n"
            f"{doc_section}"
            f"{memory_section}"
        )
        system = (
            "You are a senior engineer writing internal technical documentation. "
            "Focus on business logic and workflow understanding. "
            "Use clear section headings (##). Output Markdown."
        )
        return (await self._llm.generate(prompt, system=system)).strip()

    def _entity_digest(self, page_data: PageData, page_type: PageType) -> str:
        n = page_data.node
        lines = [
            f"- Label: {n.label.value}",
            f"- UID: {n.uid}",
        ]
        name = n.properties.get("name")
        if isinstance(name, str):
            lines.append(f"- Name: {name}")
        path = n.properties.get("path")
        if isinstance(path, str):
            lines.append(f"- Path: {path}")
        fqn = n.properties.get("fqn")
        if isinstance(fqn, str):
            lines.append(f"- FQN: {fqn}")
        sig = n.properties.get("signature")
        if isinstance(sig, str) and sig:
            lines.append(f"- Signature: {sig}")
        doc = n.properties.get("docstring")
        if isinstance(doc, str) and doc:
            lines.append(f"- Docstring: {doc[:500]}")
        bs = n.properties.get("business_summary")
        if isinstance(bs, str) and bs:
            lines.append(f"- Business summary: {bs}")

        for prop_name, label in [
            ("annotations", "Annotations"),
            ("semantic_roles", "Semantic roles"),
            ("base_classes", "Base classes"),
            ("interfaces", "Implements"),
        ]:
            val = n.properties.get(prop_name)
            if val:
                display = ", ".join(val) if isinstance(val, list) else str(val)
                lines.append(f"- {label}: {display}")

        lines.append(f"- Related edges: {len(page_data.edges)}")

        if page_type == PageType.MODULE_OVERVIEW:
            lines.append(f"- Child classes/modules: {len(page_data.children)}")
            for ch in page_data.children[:20]:
                ch_name = ch.properties.get("name", ch.uid)
                ch_sig = ch.properties.get("signature", "")
                ch_bs = ch.properties.get("business_summary", "")
                detail = f"  - [{ch.label.value}] {ch_name}"
                if ch_sig:
                    detail += f" | sig: {str(ch_sig)[:120]}"
                if ch_bs:
                    detail += f" | summary: {str(ch_bs)[:100]}"
                ch_annotations = ch.properties.get("annotations", "")
                if ch_annotations:
                    ann_str = ", ".join(ch_annotations) if isinstance(ch_annotations, list) else str(ch_annotations)
                    detail += f" | annotations: {ann_str[:80]}"
                lines.append(detail)
        else:
            lines.append(f"- Methods: {len(page_data.methods)}")
            for m in page_data.methods[:30]:
                m_name = m.properties.get("name", m.uid)
                m_sig = m.properties.get("signature", "")
                m_doc = m.properties.get("docstring", "")
                m_bs = m.properties.get("business_summary", "")
                detail = f"  - {m_name}"
                if m_sig:
                    detail += f" | sig: {str(m_sig)[:150]}"
                if m_bs:
                    detail += f" | summary: {str(m_bs)[:100]}"
                elif m_doc:
                    detail += f" | doc: {str(m_doc)[:100]}"
                m_params = m.properties.get("parameters", "")
                m_ret = m.properties.get("return_type", "")
                if m_params:
                    detail += f" | params: {str(m_params)[:100]}"
                if m_ret:
                    detail += f" | returns: {str(m_ret)[:60]}"
                lines.append(detail)

        calls_out = [e for e in page_data.edges if e.edge_type == EdgeType.CALLS and e.source_uid == n.uid]
        calls_in = [e for e in page_data.edges if e.edge_type == EdgeType.CALLS and e.target_uid == n.uid]
        inherits = [e for e in page_data.edges if e.edge_type == EdgeType.INHERITS]
        if calls_out:
            targets = [_display_name(e.target_uid) for e in calls_out[:10]]
            lines.append(f"- Calls out to: {', '.join(targets)}")
        if calls_in:
            sources = [_display_name(e.source_uid) for e in calls_in[:10]]
            lines.append(f"- Called by: {', '.join(sources)}")
        if inherits:
            parents = [_display_name(e.target_uid) for e in inherits[:5]]
            lines.append(f"- Inherits from: {', '.join(parents)}")

        if page_data.code_snippets:
            lines.append(f"\n### Source Code ({page_data.code_snippets[0].origin})")
            for snippet in page_data.code_snippets:
                lines.append(f"```\n{snippet.source}\n```")
                lines.append(f"- File: {snippet.file_path}:{snippet.start_line}-{snippet.end_line}")

        if page_data.related_chunks:
            lines.append(f"\n### Related Code (semantic, {len(page_data.related_chunks)} chunks)")
            for chunk in page_data.related_chunks[:5]:
                lines.append(f"From `{chunk.parent_name}` ({chunk.file_path}:{chunk.start_line}-{chunk.end_line}, score={chunk.score:.2f}):")
                lines.append(f"```\n{chunk.text}\n```")

        return "\n".join(lines)

    def _tier3_structural(self, page_data: PageData, page_type: PageType, language: str) -> str:
        node = page_data.node
        eff = _effective_wiki_language(language)
        # Template registry key: (page_type tier-3 branch, effective language)
        if node.label == NodeLabel.MODULE or page_type == PageType.MODULE_OVERVIEW:
            return self._tier3_templates[(PageType.MODULE_OVERVIEW, eff)](self, node, page_data)
        return self._tier3_templates[(PageType.CLASS_DETAIL, eff)](self, node, page_data)

    def _tier3_module_paragraph_en(self, node: GraphNode, page_data: PageData) -> str:
        mod_name = _primary_name(node)
        path = str(node.properties.get("path") or "")
        children = page_data.children
        class_labels = [_primary_name(c) for c in children if c.label == NodeLabel.CLASS]
        others = len(children) - len(class_labels)

        pieces: list[str] = [
            f"The `{mod_name}` module{f' (`{path}`)' if path else ''} organizes part of the codebase.",
        ]
        if class_labels:
            preview = ", ".join(class_labels[:8])
            extra = ""
            if len(class_labels) > 8:
                extra = f" (+{len(class_labels) - 8} more)"
            pieces.append(f"It contains {len(class_labels)} classes including {preview}{extra}.")
        elif others > 0:
            pieces.append(f"It contains {others} nested units.")
        imp_targets = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.IMPORTS and e.source_uid == node.uid
        ]
        if imp_targets:
            uniq = list(dict.fromkeys(imp_targets))[:6]
            pieces.append(f"It imports {', '.join(uniq)} among other dependencies.")
        return " ".join(pieces)

    def _tier3_module_paragraph_zh(self, node: GraphNode, page_data: PageData) -> str:
        mod_name = _primary_name(node)
        path = str(node.properties.get("path") or "")
        children = page_data.children
        class_labels = [_primary_name(c) for c in children if c.label == NodeLabel.CLASS]
        class_count = len(class_labels)
        fn_count = sum(1 for c in children if c.label == NodeLabel.FUNCTION)
        others = len(children) - len(class_labels)

        header = f"**{mod_name}** 模块包含 {class_count} 个类和 {fn_count} 个函数。"
        pieces: list[str] = [
            header,
            f"`{mod_name}` 模块{f'（路径 `{path}`）' if path else ''}组织代码库的一部分。",
        ]
        if class_labels:
            preview = "、".join(class_labels[:8])
            extra = ""
            if len(class_labels) > 8:
                extra = f"（另有 {len(class_labels) - 8} 个）"
            pieces.append(f"其中包括：{preview}{extra}。")
        elif others > 0:
            pieces.append(f"此外包含 {others} 个嵌套单元。")
        imp_targets = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.IMPORTS and e.source_uid == node.uid
        ]
        if imp_targets:
            uniq = list(dict.fromkeys(imp_targets))[:6]
            pieces.append(f"模块导入了 {', '.join(uniq)} 等依赖。")
        return " ".join(pieces)

    def _tier3_class_paragraph_en(self, node: GraphNode, page_data: PageData) -> str:
        cls_name = _primary_name(node)
        methods = _sorted_method_names(page_data.methods)
        inherit_parents = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.INHERITS and e.source_uid == node.uid
        ]
        impl_targets = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.IMPLEMENTS and e.source_uid == node.uid
        ]
        callers = [
            _display_name(e.source_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.CALLS and e.target_uid == node.uid
        ]
        callees = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.CALLS and e.source_uid == node.uid
        ]

        parts: list[str] = [f"{cls_name} is a focal class in the codebase."]

        if inherit_parents:
            extra = ""
            if len(inherit_parents) > 1:
                extra = f" (and {len(inherit_parents) - 1} other type(s))"
            parts.append(f"It inherits from `{inherit_parents[0]}`{extra}.")
        elif impl_targets:
            impl_txt = ", ".join(f"`{t}`" for t in impl_targets[:3])
            extra = f" (+{len(impl_targets) - 3} more)" if len(impl_targets) > 3 else ""
            parts.append(f"It implements {impl_txt}{extra}.")

        if methods:
            shown = ", ".join(f"`{m}()`" for m in methods[:5])
            tail = f" (+{len(methods) - 5} more)" if len(methods) > 5 else ""
            parts.append(f"It exposes {len(methods)} public methods including {shown}{tail}.")

        if callers:
            uniq_callers = list(dict.fromkeys(callers))[:4]
            parts.append("It is called by " + ", ".join(f"`{c}`" for c in uniq_callers) + ".")
        if callees:
            uniq_callees = list(dict.fromkeys(callees))[:4]
            parts.append("It calls " + ", ".join(f"`{c}`" for c in uniq_callees) + ".")

        return " ".join(parts)

    def _tier3_class_paragraph_zh(self, node: GraphNode, page_data: PageData) -> str:
        cls_name = _primary_name(node)
        methods = _sorted_method_names(page_data.methods)
        method_count = len(methods)
        inherit_parents = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.INHERITS and e.source_uid == node.uid
        ]
        impl_targets = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.IMPLEMENTS and e.source_uid == node.uid
        ]
        callers = [
            _display_name(e.source_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.CALLS and e.target_uid == node.uid
        ]
        callees = [
            _display_name(e.target_uid)
            for e in page_data.edges
            if e.edge_type == EdgeType.CALLS and e.source_uid == node.uid
        ]

        inheritance_info = "具有继承关系"
        if inherit_parents:
            inheritance_info = f"继承自 `{inherit_parents[0]}`"
        elif impl_targets:
            inheritance_info = "实现接口"

        parts: list[str] = [
            f"**{cls_name}** 是一个{inheritance_info}的类，定义了 {method_count} 个方法。",
            f"`{cls_name}` 是代码库中的一个核心类。",
        ]

        if inherit_parents:
            extra = ""
            if len(inherit_parents) > 1:
                extra = f"（另有 {len(inherit_parents) - 1} 个父类型）"
            parts.append(f"它继承自 `{inherit_parents[0]}`{extra}。")
        elif impl_targets:
            impl_txt = "、".join(f"`{t}`" for t in impl_targets[:3])
            extra = f"（另有 {len(impl_targets) - 3} 个）" if len(impl_targets) > 3 else ""
            parts.append(f"它实现：{impl_txt}{extra}。")

        if methods:
            shown = "、".join(f"`{m}()`" for m in methods[:5])
            tail = f"（另有 {len(methods) - 5} 个）" if len(methods) > 5 else ""
            parts.append(f"公开方法包括 {shown}{tail}。")

        if callers:
            uniq_callers = list(dict.fromkeys(callers))[:4]
            parts.append("调用方包括 " + "、".join(f"`{c}`" for c in uniq_callers) + "。")
        if callees:
            uniq_callees = list(dict.fromkeys(callees))[:4]
            parts.append("它会调用 " + "、".join(f"`{c}`" for c in uniq_callees) + "。")

        return " ".join(parts)

    def _markdown_body(self, title: str, page_data: PageData, page_type: PageType, overview: str) -> str:
        lines: list[str] = [
            f"# {title}",
            "",
            "## Overview",
            "",
            overview,
            "",
            "## Key components and methods",
            "",
        ]
        node = page_data.node
        if node.label == NodeLabel.MODULE or page_type == PageType.MODULE_OVERVIEW:
            if page_data.children:
                lines.append("Notable nested types:")
                for ch in sorted(page_data.children, key=lambda c: _primary_name(c)):
                    lines.append(f"- `{_primary_name(ch)}` ({ch.label.value})")
            else:
                lines.append("_No nested graph children were collected for this module._")
        else:
            if page_data.methods:
                lines.append("Methods:")
                for m in page_data.methods:
                    mn = m.properties.get("name")
                    label = str(mn) if isinstance(mn, str) else _display_name(m.uid)
                    lines.append(f"- `{label}()`")
            else:
                lines.append("_No methods were attached to this class in the graph._")

        lines.extend(["", "## Relationships", ""])
        lines.append(self._relationships_section(page_data))
        return "\n".join(lines)

    def _relationships_section(self, page_data: PageData) -> str:
        uid = page_data.node.uid
        bullets: list[str] = []

        for e in page_data.edges:
            if e.edge_type == EdgeType.INHERITS and e.source_uid == uid:
                bullets.append(f"- Inherits from `{_display_name(e.target_uid)}`.")
            elif e.edge_type == EdgeType.IMPLEMENTS and e.source_uid == uid:
                bullets.append(f"- Implements `{_display_name(e.target_uid)}`.")
            elif e.edge_type == EdgeType.CALLS and e.source_uid == uid:
                bullets.append(f"- Calls `{_display_name(e.target_uid)}`.")
            elif e.edge_type == EdgeType.CALLS and e.target_uid == uid:
                bullets.append(f"- Called by `{_display_name(e.source_uid)}`.")
            elif e.edge_type == EdgeType.IMPORTS and e.source_uid == uid:
                bullets.append(f"- Imports `{_display_name(e.target_uid)}`.")

        if not bullets:
            return "_No graph relationships were summarized for this page._"
        return "\n".join(sorted(set(bullets)))

    def _build_diagrams(self, page_data: PageData, page_type: PageType) -> list[WikiDiagram]:
        node = page_data.node
        edges = page_data.edges
        out: list[WikiDiagram] = []

        if page_type == PageType.MODULE_OVERVIEW or node.label == NodeLabel.MODULE:
            dg = generate_dependency_graph(node, edges)
            dg = WikiDiagram(diagram_type=dg.diagram_type, content=dg.content, title="Dependency graph")
            out.append(dg)
            return out

        cd = generate_class_diagram(node, edges)
        cd = WikiDiagram(diagram_type=cd.diagram_type, content=cd.content, title="Class diagram")
        out.append(cd)

        calls = [e for e in edges if e.edge_type == EdgeType.CALLS]
        if calls:
            fc = generate_call_flowchart(node, edges)
            out.append(
                WikiDiagram(diagram_type=fc.diagram_type, content=fc.content, title="Call flow"),
            )
        return out


# Template registry keyed by ``(page_type, language)``; unknown ``language`` becomes ``en`` before lookup.
WikiComposer._tier3_templates = {
    (PageType.MODULE_OVERVIEW, "en"): WikiComposer._tier3_module_paragraph_en,
    (PageType.MODULE_OVERVIEW, "zh"): WikiComposer._tier3_module_paragraph_zh,
    (PageType.CLASS_DETAIL, "en"): WikiComposer._tier3_class_paragraph_en,
    (PageType.CLASS_DETAIL, "zh"): WikiComposer._tier3_class_paragraph_zh,
}
