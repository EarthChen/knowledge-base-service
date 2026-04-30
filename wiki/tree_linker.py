"""Wiki tree linking: domain tree construction, page-to-section linking."""

from __future__ import annotations

from typing import Any

from log import get_logger
from store.wiki_store import WikiStore
from wiki.dependency_graph import DomainNode
from wiki.models import WikiPage
from wiki.tree_builder import WikiTreeBuilder

log = get_logger(__name__)


class WikiTreeLinker:
    """Manages the hierarchical tree structure for wiki spaces and sections."""

    def __init__(
        self,
        store: Any | None,
        wiki_store: Any | None,
        wiki_cfg: Any,
        persistence: Any,  # WikiPagePersistence for nested tree overview page persistence
    ) -> None:
        self._store = store
        self._wiki_store = wiki_store
        self._wiki_cfg = wiki_cfg
        self._persistence = persistence

    async def get_domain_tree(self, business_id: str) -> dict[str, Any]:
        """Hierarchical domain tree and review status from the latest pipeline run (when persisted)."""
        if self._store is None:
            return {"tree": [], "review_status": {}}
        ws = WikiStore(self._store)
        return await ws.get_pipeline_domain_tree_snapshot(business_id)

    async def get_topic_tree(self, business_id: str) -> dict[str, Any]:
        """Topic and domain-overview pages as a nested tree for dashboard wiki navigation."""
        if self._store is None:
            return {"tree": []}
        ws = WikiStore(self._store)
        nested = await ws.get_topic_navigation_tree(business_id)
        return {"tree": nested}

    async def get_domain_edges(self, business_id: str) -> dict[str, Any]:
        """Compute cross-domain CALLS edges for knowledge graph."""
        if self._store is None:
            return {"edges": []}
        ws = WikiStore(self._store)
        return await ws.get_domain_edges(business_id)

    async def link_pages_to_tree(
        self,
        business_id: str,
        domain_mapping: dict[str, list[tuple[str, str]]],
        repo_names: list[str],
        tree_builder: WikiTreeBuilder,
        *,
        skip_business_domain: bool = False,
    ) -> None:
        """Create HAS_CHILD edges from WikiSection to WikiPage for both view types.

        - code_structure: WikiSection:repo → WikiPage (all pages of that repo)
        - business_domain: WikiSection:domain → WikiPage (pages mixed across repos)

        When ``skip_business_domain`` is True, only code_structure edges are created.
        This is used when a nested domain tree (``__root__``) handles the
        business_domain view separately via ``link_pages_to_nested_tree``.

        NOTE: queries WikiPage nodes directly by repository instead of traversing
        HAS_CHILD from WikiSpace, because HAS_CHILD edges do not exist yet at
        this point — this function is responsible for creating them.
        """
        if self._wiki_store is None:
            return

        module_to_domain: dict[tuple[str, str], str] = {}
        for domain_name, pairs in domain_mapping.items():
            for repo, mod_name in pairs:
                module_to_domain[(repo, mod_name)] = domain_name

        pages_by_repo: dict[str, list[dict[str, Any]]] = {}
        for repo_name in repo_names:
            q = (
                "MATCH (wp:WikiPage {repository: $repo}) "
                "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
                "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
                "wp.page_type AS page_type, wp.repository AS repository, "
                "coalesce(e.uid, '') AS entity_uid "
                "ORDER BY wp.path"
            )
            result = await self._wiki_store.execute_query(q, {"repo": repo_name})
            rows = getattr(result, "data", None) or []
            if rows:
                pages_by_repo[repo_name] = [
                    {
                        "uid": str(r.get("uid") or ""),
                        "title": str(r.get("title") or ""),
                        "path": str(r.get("path") or ""),
                        "page_type": str(r.get("page_type") or ""),
                        "repository": str(r.get("repository") or ""),
                        "entity_uid": str(r.get("entity_uid") or ""),
                    }
                    for r in rows
                    if r.get("uid")
                ]

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

                if not skip_business_domain:
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

        total_pages = sum(len(pages) for pages in pages_by_repo.values())
        log.info(
            "wiki_tree_pages_linked",
            business_id=business_id,
            linked_code_structure=linked_code,
            linked_business_domain=linked_domain,
            total_pages=total_pages,
        )

    async def link_pages_to_nested_tree(
        self,
        business_id: str,
        domain_tree: list[DomainNode],
        pages_by_entity_uid: dict[str, dict[str, Any]],
        tree_builder: WikiTreeBuilder,
        *,
        language: str = "zh",
    ) -> None:
        """Create nested HAS_CHILD edges for WikiSection hierarchy (business_domain view).

        Builds a subtree under an internal ``__root__`` section (linked from WikiSpace).
        For each domain node, generates a rich overview WikiPage aggregating its
        modules and sub-domain descriptions, linked as the first child of the section.
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

        overview_pages: list[WikiPage] = []

        def _build_domain_overview_content(domain: DomainNode, depth: int = 0) -> str:
            """Build a rich structural overview document for a nested domain."""
            is_zh = language.startswith("zh")
            lines: list[str] = []
            lines.append(f"# {domain.name}")
            lines.append("")
            if domain.description:
                lines.append(domain.description)
                lines.append("")

            if domain.children:
                heading = "## 子域概览" if is_zh else "## Sub-Domains"
                lines.append(heading)
                lines.append("")
                for child in domain.children:
                    desc = f" — {child.description}" if child.description else ""
                    mod_count = len(child.modules)
                    child_count = len(child.children)
                    meta_parts: list[str] = []
                    if mod_count > 0:
                        meta_parts.append(f"{mod_count} {'个模块' if is_zh else 'modules'}")
                    if child_count > 0:
                        meta_parts.append(f"{child_count} {'个子域' if is_zh else 'sub-domains'}")
                    meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                    lines.append(f"- **{child.name}**{desc}{meta}")
                lines.append("")

            if domain.modules:
                heading = "## 核心模块" if is_zh else "## Key Modules"
                lines.append(heading)
                lines.append("")
                for mod_name in domain.modules:
                    page = pages_by_entity_uid.get(mod_name)
                    summary = ""
                    if page:
                        content = page.get("content", "") if isinstance(page, dict) else ""
                        if content:
                            overview_start = content.find("## Overview")
                            if overview_start >= 0:
                                after = content[overview_start + len("## Overview"):].strip()
                                next_h = after.find("\n## ")
                                snippet = after[:next_h].strip() if next_h > 0 else after[:200].strip()
                                non_heading = [
                                    l for l in snippet.split("\n")
                                    if l.strip() and not l.strip().startswith("#")
                                ]
                                summary = " ".join(non_heading)[:150]
                    if summary:
                        lines.append(f"- **{mod_name}**: {summary}")
                    else:
                        lines.append(f"- **{mod_name}**")
                lines.append("")

            total_modules = WikiTreeLinker.count_domain_modules(domain)
            if total_modules > len(domain.modules):
                if is_zh:
                    lines.append(f"_此域及其子域共包含 {total_modules} 个模块。_")
                else:
                    lines.append(f"_This domain and sub-domains contain {total_modules} modules in total._")
                lines.append("")

            return "\n".join(lines)

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

            child_sort = 0

            if domain.modules or domain.children:
                overview_content = _build_domain_overview_content(domain)
                overview_path = f"/__domains__/{domain.name}/_overview"
                from wiki.models import EnrichmentLevel, PageType, WikiPageMetadata

                overview_page = WikiPage(
                    path=overview_path,
                    title=f"{domain.name}" if language.startswith("zh") else f"{domain.name} Overview",
                    page_type=PageType.DOMAIN_OVERVIEW,
                    content=overview_content,
                    diagrams=[],
                    source_locations=[],
                    metadata=WikiPageMetadata(
                        node_count=WikiTreeLinker.count_domain_modules(domain),
                        edge_count=0,
                        generation_mode="business",
                        enrichment_level=EnrichmentLevel.BASE,
                    ),
                )
                overview_pages.append(overview_page)
                overview_uid = f"WikiPage:{business_id}:{overview_path}"
                await self._persistence.persist_pages_to_graph(
                    business_id, [overview_page], language=language,
                )
                try:
                    await self._wiki_store.add_has_child_edge(
                        parent_uid=section_uid,
                        parent_label="WikiSection",
                        child_uid=overview_uid,
                        child_label="WikiPage",
                        view_type="business_domain",
                        sort_order=child_sort,
                    )
                    child_sort += 1
                except Exception:
                    log.warning("nested_tree_overview_link_failed", domain=domain.name, exc_info=True)

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
                                sort_order=child_sort + i,
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

        if overview_pages:
            await self._persistence.persist_pages_to_graph(
                business_id, overview_pages, language=language,
            )
            log.info(
                "nested_tree_overview_pages_generated",
                business_id=business_id,
                count=len(overview_pages),
            )

    @staticmethod
    def count_domain_modules(domain: DomainNode) -> int:
        """Recursively count modules in a domain and all its children."""
        count = len(domain.modules)
        for child in domain.children:
            count += WikiTreeLinker.count_domain_modules(child)
        return count
