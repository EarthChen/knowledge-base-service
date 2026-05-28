"""Wiki tree linking: domain tree construction, page-to-section linking."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from core.config import get_settings
from core.log import get_logger
from store.wiki_store import WikiStore
from wiki.content_guards import strip_h1_title
from wiki.dependency_graph import DomainNode
from wiki.models import WikiPage
from wiki.nodes.finalize import _sanitize_published_content
from wiki.tree_builder import WikiTreeBuilder

log = get_logger(__name__)

_TREE_LINKER_MIN_OVERVIEW_CHARS = 200


_TREE_LINKER_CN_RATIO_MIN = 0.15


def _warn_duplicate_titles_before_persist(pages: list[WikiPage], *, repository: str) -> None:
    """Log a warning when duplicate page titles are about to be persisted (non-blocking)."""
    title_to_paths: dict[str, list[str]] = {}
    for page in pages:
        title = (page.title or "").strip()
        if not title:
            continue
        title_to_paths.setdefault(title, []).append(page.path)

    for title, paths in title_to_paths.items():
        if len(paths) > 1:
            log.warning(
                "duplicate_wiki_page_titles_before_persist",
                repository=repository,
                title=title,
                paths=paths,
                count=len(paths),
            )


def _filter_overview_pages_for_persist(
    overview_pages: list[WikiPage],
    *,
    language: str = "zh",
) -> list[WikiPage]:
    """Run overview pages through the finalize sanitize pipeline and drop shell pages.

    Thresholds:
    - _TREE_LINKER_MIN_OVERVIEW_CHARS (200): tree_linker-specific floor (finalize uses 500)
    - _TREE_LINKER_CN_RATIO_MIN (0.15): aligned with finalize hard-reject (Chinese only)
    """
    from wiki.content_guards import compute_cn_ratio

    is_chinese = language.startswith("zh")
    filtered_overview_pages: list[WikiPage] = []
    for page in overview_pages:
        content = page.content
        content = strip_h1_title(content)
        content = _sanitize_published_content(content, page_type="domain_overview")
        stripped = content.strip()
        if len(stripped) < _TREE_LINKER_MIN_OVERVIEW_CHARS:
            log.info("tree_linker_shell_filtered", slug=page.path, chars=len(stripped))
            continue
        if is_chinese:
            cn_ratio = compute_cn_ratio(stripped)
            if cn_ratio < _TREE_LINKER_CN_RATIO_MIN:
                log.info("tree_linker_cn_ratio_filtered", slug=page.path, cn_ratio=f"{cn_ratio:.3f}")
                continue
        filtered_overview_pages.append(replace(page, content=stripped))
    return filtered_overview_pages


def _attach_architecture_layers(
    nodes: list[dict[str, Any]],
    layers: dict[str, dict[str, int]],
) -> None:
    """Recursively attach architecture_layers to matching domain tree nodes."""
    for node in nodes:
        name = node.get("name", "")
        if name and name in layers:
            node["architecture_layers"] = layers[name]
        children = node.get("children", [])
        if children:
            _attach_architecture_layers(children, layers)
            # Aggregate child layers to parent
            if "architecture_layers" not in node:
                agg: dict[str, int] = {}
                for child in children:
                    for layer, count in child.get("architecture_layers", {}).items():
                        agg[layer] = agg.get(layer, 0) + count
                if agg:
                    node["architecture_layers"] = agg


def _safe_truncate(text: str, max_len: int = 150) -> str:
    """Truncate text at a Markdown-safe boundary."""
    if len(text) <= max_len:
        return text
    cut = text[:max_len]
    if cut.count("`") % 2 != 0:
        last_tick = cut.rfind("`")
        if last_tick > 0:
            cut = cut[:last_tick]
    for sep in ("。", ". ", "，", ", ", " "):
        pos = cut.rfind(sep)
        if pos > max_len // 2:
            return cut[: pos + len(sep)].rstrip()
    return cut.rstrip()


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
        result = await ws.get_pipeline_domain_tree_snapshot(business_id)

        try:
            arch_layers = await ws.get_domain_architecture_layers(business_id)
            if arch_layers:
                _attach_architecture_layers(result.get("tree", []), arch_layers)
        except Exception:
            log.warning("domain_tree_arch_layers_enrichment_failed", business_id=business_id, exc_info=True)

        return result

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

        already_linked_uids: set[str] = set()
        for plist in pages_by_repo.values():
            for p in plist:
                u = p.get("uid", "")
                if u:
                    already_linked_uids.add(str(u))

        biz_q = (
            "MATCH (wp:WikiPage {repository: $biz}) "
            "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(e) "
            "RETURN wp.uid AS uid, wp.title AS title, wp.path AS path, "
            "wp.page_type AS page_type, wp.repository AS repository, "
            "coalesce(e.uid, '') AS entity_uid "
            "ORDER BY wp.path"
        )
        biz_result = await self._wiki_store.execute_query(biz_q, {"biz": business_id})
        biz_rows = getattr(biz_result, "data", None) or []
        biz_only_pages: list[dict[str, Any]] = []
        for r in biz_rows:
            uid = str(r.get("uid") or "")
            if not uid or uid in already_linked_uids:
                continue
            biz_only_pages.append(
                {
                    "uid": uid,
                    "title": str(r.get("title") or ""),
                    "path": str(r.get("path") or ""),
                    "page_type": str(r.get("page_type") or ""),
                    "repository": str(r.get("repository") or ""),
                    "entity_uid": str(r.get("entity_uid") or ""),
                },
            )

        repo_name_set = set(repo_names)

        def _resolve_repo_and_domain(page: dict[str, Any]) -> tuple[str | None, str]:
            mod_name = page.get("title", "")
            entity_uid = str(page.get("entity_uid", "") or "")
            domain_name: str | None = None
            resolved_repo: str | None = None
            if entity_uid:
                for (r, m), d in module_to_domain.items():
                    if r in repo_name_set and entity_uid.endswith(m):
                        domain_name = d
                        resolved_repo = r
                        break
            if not domain_name:
                for r in repo_names:
                    d = module_to_domain.get((r, mod_name))
                    if d:
                        domain_name = d
                        resolved_repo = r
                        break
            if not domain_name:
                domain_name = self._wiki_cfg.business_domain_infrastructure_label
            return resolved_repo, domain_name

        linked_code = 0
        linked_domain = 0
        domain_page_counters: dict[str, int] = {}
        extra_sort_by_repo: dict[str, int] = {
            r: len(pages_by_repo.get(r, [])) for r in repo_names
        }

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

        for page in biz_only_pages:
            page_uid = page.get("uid", "")
            if not page_uid:
                continue
            resolved_repo, domain_name = _resolve_repo_and_domain(page)

            if resolved_repo:
                idx = extra_sort_by_repo.get(resolved_repo, 0)
                extra_sort_by_repo[resolved_repo] = idx + 1
                try:
                    repo_section_uid = tree_builder.generate_repo_section_uid(
                        business_id, resolved_repo,
                    )
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

        total_pages = sum(len(pages) for pages in pages_by_repo.values()) + len(biz_only_pages)
        log.info(
            "wiki_tree_pages_linked",
            business_id=business_id,
            linked_code_structure=linked_code,
            linked_business_domain=linked_domain,
            total_pages=total_pages,
        )

    @staticmethod
    def build_canonical_key_maps(
        domain_tree: list[DomainNode],
        pages_by_entity_uid: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
        """Map canonical_key → owning domain name and → representative page row.

        Built from domain tree module membership so topic pages can resolve by
        exact ``canonical_key`` instead of fuzzy path matching. Leaf domains
        (no children) override parent assignments so topics land in the most
        specific domain.
        """
        canonical_key_to_domain: dict[str, str] = {}
        canonical_key_to_page: dict[str, dict[str, Any]] = {}

        def visit(domain: DomainNode) -> None:
            is_leaf = not domain.children
            for mod_name in domain.modules:
                page = pages_by_entity_uid.get(mod_name)
                if not page or not isinstance(page, dict):
                    continue
                ck = str(page.get("canonical_key") or "").strip()
                if not ck:
                    continue
                if ck not in canonical_key_to_domain or is_leaf:
                    canonical_key_to_domain[ck] = domain.name
                    canonical_key_to_page[ck] = page
            for child in domain.children:
                visit(child)

        for root in domain_tree:
            visit(root)
        return canonical_key_to_domain, canonical_key_to_page

    async def link_pages_to_nested_tree(
        self,
        business_id: str,
        domain_tree: list[DomainNode],
        pages_by_entity_uid: dict[str, dict[str, Any]],
        tree_builder: WikiTreeBuilder,
        *,
        language: str = "zh",
        reassembly_succeeded: bool = False,
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

        # Pre-check: which domains already have Agent-generated overview pages
        agent_overview_paths: set[str] = set()
        try:
            agent_q = (
                "MATCH (wp:WikiPage) "
                "WHERE wp.repository = $biz "
                "AND wp.path STARTS WITH '/__domains__/' "
                "AND wp.path ENDS WITH '/_overview' "
                "AND wp.page_type = 'domain_overview' "
                "RETURN wp.path AS path"
            )
            agent_result = await self._wiki_store.execute_query(agent_q, {"biz": business_id})
            agent_rows = getattr(agent_result, "data", None) or []
            for row in agent_rows:
                p = str(row.get("path", ""))
                if p:
                    agent_overview_paths.add(p)
            if agent_overview_paths:
                log.info(
                    "nested_tree_agent_overviews_found",
                    business_id=business_id,
                    count=len(agent_overview_paths),
                )
        except Exception:
            log.warning("nested_tree_agent_check_failed", business_id=business_id, exc_info=True)

        topic_pages_by_domain: dict[str, list[str]] = {}
        canonical_key_to_domain, _canonical_key_to_page = WikiTreeLinker.build_canonical_key_maps(
            domain_tree,
            pages_by_entity_uid,
        )
        try:
            tp_q = (
                "MATCH (wp:WikiPage) "
                "WHERE wp.repository = $biz AND wp.page_type = 'topic' "
                "AND (wp.path STARTS WITH 'wiki/' OR wp.path STARTS WITH '/__domains__/') "
                "RETURN wp.uid AS uid, wp.path AS path, "
                "coalesce(wp.canonical_key, '') AS canonical_key, "
                "coalesce(wp.business_domain, '') AS business_domain "
                "ORDER BY wp.path"
            )
            tp_result = await self._wiki_store.execute_query(tp_q, {"biz": business_id})
            tp_rows = getattr(tp_result, "data", None) or []

            def _flatten_names(nodes: list[DomainNode]) -> set[str]:
                names: set[str] = set()
                for n in nodes:
                    names.add(n.name)
                    names.update(_flatten_names(n.children))
                return names

            domain_names = _flatten_names(domain_tree)
            domain_name_set = set(domain_names)

            def _stem(word: str) -> str:
                for suffix in ("tion", "sion", "ment", "ness", "ing", "ers", "er", "ed", "es", "s"):
                    if len(word) > len(suffix) + 2 and word.endswith(suffix):
                        return word[: -len(suffix)]
                return word

            def _tokenize(name: str) -> set[str]:
                import re as _re
                spaced = _re.sub(r"([a-z])([A-Z])", r"\1 \2", name)
                spaced = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", spaced)
                cleaned = _re.sub(r"[()&/,\-_]", " ", spaced.lower())
                return {_stem(t) for t in cleaned.split() if len(t) > 1}

            domain_tokens: dict[str, set[str]] = {
                dn: _tokenize(dn) for dn in domain_names
            }

            from collections import Counter as _Counter
            _tok_freq = _Counter(t for toks in domain_tokens.values() for t in toks)
            _half = max(len(domain_names) // 2, 1)
            common_tokens = {t for t, c in _tok_freq.items() if c > _half}

            def _has_cjk(text: str) -> bool:
                return any("\u4e00" <= c <= "\u9fff" for c in text)

            def _cjk_char_overlap(a: str, b: str) -> float:
                chars_a = {c for c in a if "\u4e00" <= c <= "\u9fff"}
                chars_b = {c for c in b if "\u4e00" <= c <= "\u9fff"}
                if not chars_a:
                    return 0.0
                return len(chars_a & chars_b) / len(chars_a)

            def _find_best_domain(page_top_level: str) -> str | None:
                """Legacy fallback: fuzzy / token overlap between path segment and domain names.

                Prefer exact ``canonical_key`` resolution via ``canonical_key_to_domain``.
                Used only when the topic has no ``canonical_key`` (legacy pages).
                """
                if page_top_level in domain_names:
                    return page_top_level
                tl_lower = page_top_level.lower()
                for dn in domain_names:
                    dn_lower = dn.lower()
                    if dn_lower == tl_lower:
                        return dn
                    if tl_lower.startswith(dn_lower) or dn_lower.startswith(tl_lower):
                        return dn
                    if _has_cjk(dn) and (dn in page_top_level or page_top_level in dn):
                        return dn

                if _has_cjk(page_top_level) and any(_has_cjk(dn) for dn in domain_names):
                    best_dn, best_score = None, 0.0
                    for dn in domain_names:
                        if not _has_cjk(dn):
                            continue
                        score = _cjk_char_overlap(dn, page_top_level)
                        if score > best_score:
                            best_score = score
                            best_dn = dn
                    if best_score >= 0.5:
                        return best_dn
                    return None

                tl_tokens = _tokenize(page_top_level)
                if not tl_tokens:
                    return None
                best_dn, best_score, best_pos = None, 0.0, len(tl_lower) + 1
                for dn, dn_toks in domain_tokens.items():
                    if not dn_toks:
                        continue
                    distinctive = dn_toks - common_tokens
                    if distinctive:
                        overlap = len(tl_tokens & distinctive)
                        score = overlap / len(distinctive)
                    else:
                        overlap = len(tl_tokens & dn_toks)
                        score = overlap / len(dn_toks)
                    if score > best_score or (score == best_score and score > 0):
                        dn_stem = _stem(dn.lower().replace("handler", "").replace("service", "").strip())
                        pos = tl_lower.find(dn_stem) if dn_stem else len(tl_lower) + 1
                        if score > best_score or (pos >= 0 and pos < best_pos):
                            best_score = score
                            best_dn = dn
                            best_pos = pos if pos >= 0 else len(tl_lower) + 1
                if best_score >= 0.5:
                    return best_dn
                return None

            for row in tp_rows:
                uid = str(row.get("uid", ""))
                path = str(row.get("path", ""))
                if not uid or not path:
                    continue
                if path.startswith("/__domains__/"):
                    after_wiki = path[len("/__domains__/") :]
                elif path.startswith("wiki/"):
                    after_wiki = path[len("wiki/") :]
                else:
                    continue
                slash_idx = after_wiki.find("/")
                top_level = after_wiki[:slash_idx] if slash_idx > 0 else after_wiki

                ck = str(row.get("canonical_key") or "").strip()
                bd = str(row.get("business_domain") or "").strip()

                matched_domain = None

                # Priority 1: business_domain exact match
                if bd and bd in domain_name_set:
                    matched_domain = bd

                # Priority 2: canonical_key in module mapping
                if not matched_domain and ck:
                    matched_domain = canonical_key_to_domain.get(ck)

                # Priority 3: canonical_key is itself a domain slug
                if not matched_domain and ck and ck in domain_name_set:
                    matched_domain = ck

                # Priority 4: path fuzzy fallback (only when all above fail)
                if not matched_domain:
                    matched_domain = _find_best_domain(top_level)
                    if matched_domain:
                        log.info(
                            "nested_tree_topic_domain_fuzzy_fallback",
                            business_id=business_id,
                            path=path,
                            matched_domain=matched_domain,
                        )

                if not matched_domain:
                    log.warning(
                        "nested_tree_topic_unresolvable",
                        business_id=business_id,
                        path=path,
                        canonical_key=ck,
                        business_domain=bd,
                    )

                if matched_domain:
                    topic_pages_by_domain.setdefault(matched_domain, []).append(uid)

            if tp_rows:
                log.info(
                    "nested_tree_topic_pages_indexed",
                    business_id=business_id,
                    total_topic_pages=len(tp_rows),
                    matched_domains=len(topic_pages_by_domain),
                )
        except Exception:
            log.warning("nested_tree_topic_index_failed", business_id=business_id, exc_info=True)

        overview_pages: list[WikiPage] = []

        def _build_domain_overview_content(domain: DomainNode, depth: int = 0) -> str:
            """Build a rich structural overview document for a nested domain."""
            from wiki.overview_synthesizer import synthesize_overview_from_children

            # Try content-based synthesis when child pages exist
            child_pages = []
            for mod_name in domain.modules:
                page = pages_by_entity_uid.get(mod_name)
                if page and isinstance(page, dict) and page.get("content"):
                    child_pages.append(
                        {
                            "title": mod_name,
                            "content": page.get("content", ""),
                        }
                    )
            for child in domain.children:
                if child.description:
                    child_pages.append(
                        {
                            "title": child.name,
                            "content": child.description,
                        }
                    )

            if child_pages:
                return synthesize_overview_from_children(domain.name, child_pages)

            # Fallback to static template when no child content is available
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
                            for overview_heading in ("## Overview", "## 概述", "## 业务概述"):
                                overview_start = content.find(overview_heading)
                                if overview_start >= 0:
                                    after = content[overview_start + len(overview_heading) :].strip()
                                    break
                            else:
                                after = ""
                            if after:
                                next_h = after.find("\n## ")
                                snippet = after[:next_h].strip() if next_h > 0 else after[:200].strip()
                                non_heading = [
                                    line for line in snippet.split("\n")
                                    if line.strip() and not line.strip().startswith("#")
                                ]
                                summary = _safe_truncate(" ".join(non_heading))
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

        # Phase 1: Create sections and collect overview pages
        seen_overview_slugs: set[str] = set()
        pending_overview_links: list[tuple[str, str]] = []  # (section_uid, overview_uid)
        # Track domain path → section_uid to handle parent-child name collisions
        domain_path_to_section_uid: dict[str, str] = {}

        async def _create_sections(parent_uid: str, domain: DomainNode, sort_idx: int, path_prefix: str = "") -> None:
            domain_path = f"{path_prefix}/{domain.name}" if path_prefix else domain.name
            section_uid = tree_builder.generate_domain_section_uid(business_id, domain_path)
            domain_path_to_section_uid[domain_path] = section_uid
            section_title = domain.display_name or domain.name
            try:
                await self._wiki_store.upsert_wiki_section(
                    uid=section_uid,
                    title=section_title,
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

            if domain.modules or domain.children:
                from wiki.path_conventions import domain_overview_path as _dop
                from wiki.path_conventions import normalize_slug

                domain_slug = domain.slug or domain.name
                normalized_slug = normalize_slug(domain_slug)
                overview_path = _dop(domain_slug)

                if normalized_slug in seen_overview_slugs:
                    log.warning(
                        "duplicate_overview_slug_skipped",
                        slug=normalized_slug,
                        domain=domain.name,
                        path_prefix=path_prefix,
                    )
                else:
                    if overview_path not in agent_overview_paths:
                        seen_overview_slugs.add(normalized_slug)
                        domain_page_uid = f"WikiPage:{business_id}:{overview_path}"
                        existing_page = (
                            pages_by_entity_uid.get(domain_page_uid)
                            or pages_by_entity_uid.get(domain.name)
                        )
                        existing_content = ""
                        if isinstance(existing_page, dict):
                            existing_content = existing_page.get("content", "")
                        elif existing_page is not None and hasattr(existing_page, "content"):
                            existing_content = getattr(existing_page, "content", "") or ""

                        _min_rich_content_length = 500
                        if len(existing_content) > _min_rich_content_length:
                            overview_content = existing_content
                        else:
                            overview_content = _build_domain_overview_content(domain)
                        from wiki.models import EnrichmentLevel, PageType, WikiPageMetadata

                        overview_page = WikiPage(
                            path=overview_path,
                            title=section_title if language.startswith("zh") else f"{section_title} Overview",
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
                    else:
                        seen_overview_slugs.add(normalized_slug)
                        log.info("nested_tree_using_agent_overview", domain=domain.name)

                    overview_uid = f"WikiPage:{business_id}:{overview_path}"
                    pending_overview_links.append((section_uid, overview_uid))

            for i, child in enumerate(domain.children):
                await _create_sections(section_uid, child, i, path_prefix=domain_path)

        for i, domain in enumerate(domain_tree):
            await _create_sections(root_uid, domain, i)

        # Phase 2: Persist overview pages so WikiPage nodes exist in graph
        overview_pages = _filter_overview_pages_for_persist(overview_pages, language=language)
        if overview_pages:
            _warn_duplicate_titles_before_persist(overview_pages, repository=business_id)
            await self._persistence.persist_pages_to_graph(
                business_id, overview_pages, language=language,
            )
            log.info(
                "nested_tree_overview_pages_generated",
                business_id=business_id,
                count=len(overview_pages),
            )

        # Phase 3: Link overview pages, module pages, and topic pages to sections
        overview_link_set = set(pending_overview_links)

        async def _link_domain_pages(parent_uid: str, domain: DomainNode, path_prefix: str = "") -> None:
            domain_path = f"{path_prefix}/{domain.name}" if path_prefix else domain.name
            section_uid = domain_path_to_section_uid.get(domain_path)
            if not section_uid:
                section_uid = tree_builder.generate_domain_section_uid(business_id, domain_path)
            child_sort = 0

            from wiki.path_conventions import domain_overview_path as _dop

            domain_slug = domain.slug or domain.name
            overview_uid = f"WikiPage:{business_id}:{_dop(domain_slug)}"
            if (section_uid, overview_uid) in overview_link_set:
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

            linked_uids: set[str] = set()
            for i, module_name in enumerate(domain.modules):
                page = pages_by_entity_uid.get(module_name)
                if page:
                    page_uid = (
                        page.get("uid", "") if isinstance(page, dict) else getattr(page, "uid", "")
                    )
                    if page_uid and page_uid not in linked_uids:
                        try:
                            await self._wiki_store.add_has_child_edge(
                                parent_uid=section_uid,
                                parent_label="WikiSection",
                                child_uid=page_uid,
                                child_label="WikiPage",
                                view_type="business_domain",
                                sort_order=child_sort + i,
                            )
                            linked_uids.add(page_uid)
                        except Exception:
                            log.warning(
                                "nested_tree_page_link_failed", page_uid=page_uid,
                                exc_info=True,
                            )

            topic_idx = child_sort + len(domain.modules)
            for t_uid in topic_pages_by_domain.get(domain.name, []):
                if t_uid not in linked_uids:
                    try:
                        await self._wiki_store.add_has_child_edge(
                            parent_uid=section_uid,
                            parent_label="WikiSection",
                            child_uid=t_uid,
                            child_label="WikiPage",
                            view_type="business_domain",
                            sort_order=topic_idx,
                        )
                        linked_uids.add(t_uid)
                        topic_idx += 1
                    except Exception:
                        log.warning("nested_tree_topic_link_failed", page_uid=t_uid, exc_info=True)

            for child in domain.children:
                await _link_domain_pages(section_uid, child, path_prefix=domain_path)

        for domain in domain_tree:
            await _link_domain_pages(root_uid, domain)

        # Phase 4: Adopt orphan domain overview pages
        await self._adopt_orphan_domain_pages(
            business_id,
            domain_tree,
            domain_path_to_section_uid,
            tree_builder,
            reassembly_succeeded=reassembly_succeeded,
        )

    async def _adopt_orphan_domain_pages(
        self,
        business_id: str,
        domain_tree: list[DomainNode],
        domain_path_to_section_uid: dict[str, str],
        tree_builder: WikiTreeBuilder,
        threshold: float = 0.5,
        *,
        reassembly_succeeded: bool = False,
    ) -> None:
        """Phase 4: discover unlinked domain overview pages and match to nearest domain node."""
        # Skip only when reassembly was enabled and actually succeeded
        try:
            settings = get_settings().wiki
            if settings.domain_reassembly_enabled and reassembly_succeeded:
                log.info("adopt_orphan_skipped", reason="reassembly_handled_orphans_successfully")
                return
        except Exception:
            log.debug("adopt_orphan_skipped_check_failed", exc_info=True)

        if not self._wiki_store or not domain_tree:
            return

        all_q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $biz "
            "AND wp.path STARTS WITH '/__domains__/' "
            "AND wp.path ENDS WITH '/_overview' "
            "OPTIONAL MATCH (wp)-[:SOURCE_ENTITY]->(m:Module) "
            "RETURN wp.uid AS uid, wp.title AS title, collect(DISTINCT m.name) AS module_names"
        )
        all_result = await self._wiki_store.execute_query(all_q, {"biz": business_id})
        all_rows = getattr(all_result, "data", None) or []
        if not all_rows:
            return

        linked_q = (
            "MATCH ()-[:HAS_CHILD]->(wp:WikiPage) "
            "WHERE wp.repository = $biz "
            "AND wp.path STARTS WITH '/__domains__/' "
            "AND wp.path ENDS WITH '/_overview' "
            "RETURN wp.uid AS uid"
        )
        linked_result = await self._wiki_store.execute_query(linked_q, {"biz": business_id})
        linked_rows = getattr(linked_result, "data", None) or []
        linked_uids = {str(r.get("uid", "")) for r in linked_rows if r.get("uid")}

        orphans = [
            r for r in all_rows
            if str(r.get("uid", "")) and str(r.get("uid", "")) not in linked_uids
        ]
        if not orphans:
            log.info("orphan_adoption_none_found", business_id=business_id)
            return

        flat_domains: list[tuple[str, DomainNode]] = []

        def _flatten(node: DomainNode, path_prefix: str = "") -> None:
            path = f"{path_prefix}/{node.name}" if path_prefix else node.name
            flat_domains.append((path, node))
            for child in node.children:
                _flatten(child, path)

        for d in domain_tree:
            _flatten(d)

        if not flat_domains:
            return

        def _cjk_chars(text: str) -> set[str]:
            return {c for c in text if "\u4e00" <= c <= "\u9fff"}

        def _cjk_similarity(a: str, b: str) -> float:
            ca, cb = _cjk_chars(a), _cjk_chars(b)
            if not ca and not cb:
                return 0.0
            fwd = len(ca & cb) / len(ca) if ca else 0.0
            bwd = len(ca & cb) / len(cb) if cb else 0.0
            return (fwd + bwd) / 2.0

        adopted = 0
        sort_order = 10000
        unmatched_orphans: list[dict] = []

        for orphan in orphans:
            orphan_uid = str(orphan.get("uid", ""))
            orphan_title = str(orphan.get("title", ""))
            orphan_modules = set(orphan.get("module_names") or [])

            best_path: str | None = None
            best_score = 0.0

            for domain_path, domain in flat_domains:
                domain_modules = set(domain.modules)

                entity_score = 0.0
                if orphan_modules and domain_modules:
                    overlap = len(orphan_modules & domain_modules)
                    entity_score = overlap / max(len(orphan_modules), 1)

                display = domain.display_name or domain.name
                title_score = _cjk_similarity(orphan_title, display)

                score = max(entity_score, title_score)
                if score > best_score:
                    best_score = score
                    best_path = domain_path

            if best_score >= threshold and best_path:
                section_uid = domain_path_to_section_uid.get(best_path)
                if section_uid:
                    try:
                        await self._wiki_store.add_has_child_edge(
                            parent_uid=section_uid,
                            parent_label="WikiSection",
                            child_uid=orphan_uid,
                            child_label="WikiPage",
                            view_type="business_domain",
                            sort_order=sort_order,
                        )
                        adopted += 1
                        sort_order += 1
                        log.info(
                            "orphan_adopted",
                            orphan_uid=orphan_uid,
                            orphan_title=orphan_title,
                            target_domain=best_path,
                            score=round(best_score, 3),
                        )
                    except Exception:
                        log.warning("orphan_adoption_failed", orphan_uid=orphan_uid, exc_info=True)
            else:
                unmatched_orphans.append(orphan)
                log.info(
                    "orphan_unmatched",
                    orphan_uid=orphan_uid,
                    orphan_title=orphan_title,
                    best_score=round(best_score, 3),
                    best_domain=best_path or "none",
                    module_count=len(orphan_modules),
                )

        if unmatched_orphans:
            unassigned_uid = tree_builder.generate_domain_section_uid(business_id, "__unassigned__")
            root_uid = tree_builder.generate_domain_section_uid(business_id, "__root__")
            try:
                await self._wiki_store.upsert_wiki_section(
                    uid=unassigned_uid,
                    title="待分配页面",
                    description="未能自动匹配到任何域的孤儿页面，请手动移动到合适的域下",
                    section_type="business_domain",
                    sort_order=9999,
                    auto_generated=True,
                )
                await self._wiki_store.add_has_child_edge(
                    parent_uid=root_uid,
                    parent_label="WikiSection",
                    child_uid=unassigned_uid,
                    child_label="WikiSection",
                    view_type="business_domain",
                    sort_order=9999,
                )
                for idx, orphan in enumerate(unmatched_orphans):
                    orphan_uid = str(orphan.get("uid", ""))
                    await self._wiki_store.add_has_child_edge(
                        parent_uid=unassigned_uid,
                        parent_label="WikiSection",
                        child_uid=orphan_uid,
                        child_label="WikiPage",
                        view_type="business_domain",
                        sort_order=sort_order + idx,
                    )
                log.info(
                    "orphan_unassigned_section_created",
                    business_id=business_id,
                    count=len(unmatched_orphans),
                )
            except Exception:
                log.warning("orphan_unassigned_section_failed", business_id=business_id, exc_info=True)

        log.info(
            "orphan_adoption_complete",
            business_id=business_id,
            total_orphans=len(orphans),
            adopted=adopted,
            unmatched=len(unmatched_orphans),
        )

    def _find_domain_by_canonical_key(
        self, canonical_key: str, domain_pages: list,
    ) -> Any | None:
        """Find a domain page by exact canonical_key match."""
        for page in domain_pages:
            if getattr(page, "canonical_key", "") == canonical_key:
                return page
        return None

    @staticmethod
    def count_domain_modules(domain: DomainNode) -> int:
        """Recursively count modules in a domain and all its children."""
        count = len(domain.modules)
        for child in domain.children:
            count += WikiTreeLinker.count_domain_modules(child)
        return count
