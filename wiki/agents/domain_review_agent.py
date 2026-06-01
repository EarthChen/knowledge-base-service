"""LLM-agent based domain review with full reorganization power."""
from __future__ import annotations

import copy
from typing import Any

from core.log import get_logger
from wiki.graph_semantic_corrector import (
    GraphSemanticCorrector,
    _shorten_path,
    build_global_review_prompt,
)
from wiki.json_robust import parse_json_robust_sync
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)

_MAX_MOVE_RATIO_DEFAULT = 0.5


class DomainReviewAgent:
    """Agent that reviews domain assignments and proposes moves/merges/renames.

    Designed to replace GraphSemanticCorrector.review_global_consistency()
    with iterative, tool-based reasoning.
    """

    def __init__(
        self,
        llm: Any,
        max_move_ratio: float = _MAX_MOVE_RATIO_DEFAULT,
    ):
        self._llm = llm
        self._max_move_ratio = max_move_ratio
        self._domain_mapping: dict[str, list[tuple[str, str]]] = {}
        self._domain_tree: list[dict] = []
        self._domain_display_names: dict[str, str] = {}
        self._module_summaries: dict[str, str] = {}
        self.pending_moves: list[dict[str, str]] = []
        self.pending_merges: list[dict[str, Any]] = []
        self.pending_renames: list[dict[str, str]] = []
        self.pending_tree_reparents: list[dict[str, str]] = []

    def set_domain_data(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_summaries: dict[str, str],
    ) -> None:
        """Set the domain data for review."""
        self._domain_mapping = {k: list(v) for k, v in domain_mapping.items()}
        self._domain_display_names = dict(domain_display_names)
        self._module_summaries = dict(module_summaries)

    @property
    def _total_modules(self) -> int:
        return sum(len(v) for v in self._domain_mapping.values())

    @property
    def _max_moves(self) -> int:
        return max(int(self._total_modules * self._max_move_ratio), 1)

    def _propose_move(
        self, module: str, from_domain: str, to_domain: str, reason: str
    ) -> dict[str, str]:
        """Propose moving a module between domains."""
        if to_domain not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Target domain '{to_domain}' does not exist"}
        if from_domain not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Source domain '{from_domain}' does not exist"}
        if len(self.pending_moves) >= self._max_moves:
            return {"status": "rejected", "reason": f"Move limit reached ({self._max_moves})"}

        found = None
        for pair in self._domain_mapping[from_domain]:
            if pair[1] == module:
                found = pair
                break
        if found is None:
            return {"status": "rejected", "reason": f"Module '{module}' not found in '{from_domain}'"}

        self.pending_moves.append({
            "module": module,
            "from": from_domain,
            "to": to_domain,
            "reason": reason,
        })
        log.info("domain_review_propose_move", module=module, from_d=from_domain, to_d=to_domain, reason=reason)
        return {"status": "accepted"}

    def _propose_merge(
        self, sources: list[str], target: str, new_display_name: str, reason: str
    ) -> dict[str, str]:
        """Propose merging domains."""
        if target not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Target domain '{target}' does not exist"}
        for src in sources:
            if src not in self._domain_mapping:
                return {"status": "rejected", "reason": f"Source domain '{src}' does not exist"}

        self.pending_merges.append({
            "sources": sources,
            "target": target,
            "new_display_name": new_display_name,
            "reason": reason,
        })
        log.info("domain_review_propose_merge", sources=sources, target=target, reason=reason)
        return {"status": "accepted"}

    def _propose_rename(self, slug: str, new_display_name: str, reason: str) -> dict[str, str]:
        """Propose renaming a domain's display name."""
        if slug not in self._domain_mapping:
            return {"status": "rejected", "reason": f"Domain '{slug}' does not exist"}

        self.pending_renames.append({
            "slug": slug,
            "new_display_name": new_display_name,
            "reason": reason,
        })
        log.info("domain_review_propose_rename", slug=slug, new_name=new_display_name, reason=reason)
        return {"status": "accepted"}

    def apply_decisions(self) -> dict[str, list[tuple[str, str]]]:
        """Apply all pending decisions and return updated domain_mapping."""
        result = {k: list(v) for k, v in self._domain_mapping.items()}

        for merge in self.pending_merges:
            target = merge["target"]
            for src in merge["sources"]:
                if src == target or src not in result:
                    continue
                result[target].extend(result.pop(src))

        for move in self.pending_moves:
            module_name = move["module"]
            from_d = move["from"]
            to_d = move["to"]
            if from_d not in result or to_d not in result:
                continue
            pair = None
            for p in result[from_d]:
                if p[1] == module_name:
                    pair = p
                    break
            if pair:
                result[from_d].remove(pair)
                result[to_d].append(pair)

        result = {k: v for k, v in result.items() if v}
        return result

    def set_tree_data(
        self,
        domain_tree: list[dict],
        domain_display_names: dict[str, str],
        module_summaries: dict[str, str],
    ) -> None:
        """Set the tree structure for tree-level operations."""
        self._domain_tree = copy.deepcopy(domain_tree)
        self._domain_display_names = dict(domain_display_names)
        self._module_summaries = dict(module_summaries)
        self.pending_tree_reparents = []

    def _propose_reparent_domain(
        self, child_slug: str, new_parent_slug: str | None, reason: str
    ) -> dict[str, str]:
        """Propose reparenting a domain node under a different parent.

        child_slug: name of the node to move
        new_parent_slug: name of the target parent (None = promote to L1)
        reason: explanation
        """
        child_node = self._find_node_in_tree(child_slug)
        if child_node is None:
            return {"status": "rejected", "reason": f"Child '{child_slug}' not found in tree"}

        if new_parent_slug is not None:
            parent_node = self._find_node_in_tree(new_parent_slug)
            if parent_node is None:
                return {"status": "rejected", "reason": f"Parent '{new_parent_slug}' not found in tree"}

        self.pending_tree_reparents.append({
            "child": child_slug,
            "new_parent": new_parent_slug or "__L1__",
            "reason": reason,
        })
        return {"status": "accepted", "child": child_slug, "new_parent": new_parent_slug or "L1"}

    def _find_node_in_tree(self, slug: str) -> dict | None:
        """Find a node by name in the tree (BFS)."""
        queue = list(self._domain_tree)
        while queue:
            node = queue.pop(0)
            if node.get("name") == slug:
                return node
            queue.extend(node.get("children") or [])
        return None

    def _remove_node_from_tree(self, slug: str) -> dict | None:
        """Remove and return a node from the tree (recursive, any depth)."""
        for i, node in enumerate(self._domain_tree):
            if node.get("name") == slug:
                return self._domain_tree.pop(i)
            found = self._remove_from_children(node, slug)
            if found is not None:
                return found
        return None

    def _remove_from_children(self, parent: dict, slug: str) -> dict | None:
        """Recursively remove a node from nested children."""
        children = parent.get("children") or []
        for j, child in enumerate(children):
            if child.get("name") == slug:
                return children.pop(j)
            found = self._remove_from_children(child, slug)
            if found is not None:
                return found
        return None

    def apply_tree_decisions(self) -> list[dict]:
        """Apply pending tree reparent operations and return updated tree."""
        for reparent in self.pending_tree_reparents:
            child_slug = reparent["child"]
            new_parent = reparent["new_parent"]

            child_node = self._remove_node_from_tree(child_slug)
            if child_node is None:
                log.warning("reparent_child_not_found", child=child_slug)
                continue

            if new_parent == "__L1__":
                self._domain_tree.append(child_node)
            else:
                parent_node = self._find_node_in_tree(new_parent)
                if parent_node is None:
                    self._domain_tree.append(child_node)
                    log.warning("reparent_parent_not_found", parent=new_parent, child=child_slug)
                    continue
                parent_node.setdefault("children", []).append(child_node)

            log.info("tree_reparent_applied", child=child_slug, new_parent=new_parent)

        self.pending_tree_reparents.clear()
        return self._domain_tree

    async def review(
        self,
        domain_mapping: dict[str, list[tuple[str, str]]],
        domain_display_names: dict[str, str],
        module_paths: dict[str, str],
        module_summaries: dict[str, str],
        *,
        business_id: str = "",
        module_details: dict[str, dict[str, Any]] | None = None,
        language: str = "简体中文",
        anchored_slugs: frozenset[str] = frozenset(),
        package_tree_str: str = "",
        cross_domain_edges_str: str = "",
    ) -> tuple[dict[str, list[tuple[str, str]]], dict[str, str]]:
        """One-shot global review: merge overlapping domains, rename, move modules."""
        if self._llm is None or len(domain_mapping) <= 1:
            return domain_mapping, domain_display_names

        lines: list[str] = []
        for slug, pairs in sorted(domain_mapping.items(), key=lambda x: -len(x[1])):
            display = domain_display_names.get(slug, slug)
            top = sorted(pairs, key=lambda p: -len(module_summaries.get(p[1], "")))[:10]
            lines.append(f"- {slug} ({display}) — {len(pairs)} modules")
            for _repo, mod_name in top:
                path = module_paths.get(mod_name, "")
                summary = module_summaries.get(mod_name, "")
                path_part = f" [path: {_shorten_path(path)}]" if path else ""
                summary_part = f" -- {summary}" if summary else ""
                methods_part = ""
                if module_details:
                    detail = module_details.get(mod_name)
                    if isinstance(detail, dict):
                        km = detail.get("key_methods") or detail.get("methods") or []
                        if km and isinstance(km, list):
                            methods_part = f" [methods: {', '.join(str(m) for m in km[:5])}]"
                lines.append(f"  - {mod_name}{path_part}{summary_part}{methods_part}")
        listing = "\n".join(lines)

        prompt = build_global_review_prompt(
            business_id=business_id,
            domain_listing=listing,
            language=language,
            package_tree_str=package_tree_str,
            cross_domain_edges_str=cross_domain_edges_str,
        )
        if anchored_slugs:
            constraint = (
                "\nCRITICAL: The following domains are protected and MUST NOT be merged or removed: "
                f"{', '.join(sorted(anchored_slugs))}"
            )
            prompt += constraint

        try:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("domain_review_llm_failed", exc_info=True)
            return domain_mapping, domain_display_names

        if not isinstance(parsed, dict):
            return domain_mapping, domain_display_names

        self.pending_moves = []
        self.pending_merges = []
        self.pending_renames = []
        self.set_domain_data(domain_mapping, domain_display_names, module_summaries)

        merges = parsed.get("merges", [])
        if isinstance(merges, list):
            for merge in merges:
                if not isinstance(merge, dict):
                    continue
                sources = merge.get("sources", [])
                target = merge.get("target", "")
                if not isinstance(sources, list) or target not in sources:
                    continue
                if target not in self._domain_mapping:
                    continue
                filtered_sources = [s for s in sources if s not in anchored_slugs or s == target]
                mergeable = [s for s in filtered_sources if s != target and s in self._domain_mapping]
                if not mergeable:
                    continue
                new_name = merge.get("new_display_name", "")
                reason = merge.get("reason", "llm merge")
                self._propose_merge(
                    filtered_sources,
                    target,
                    new_name if isinstance(new_name, str) else "",
                    reason if isinstance(reason, str) else "llm merge",
                )

        renames = parsed.get("renames", [])
        if isinstance(renames, list):
            for rename in renames:
                if not isinstance(rename, dict):
                    continue
                slug = rename.get("slug", "")
                new_name = rename.get("new_display_name", "")
                if slug not in domain_display_names or not isinstance(new_name, str) or not new_name:
                    continue
                if not GraphSemanticCorrector._accept_display_name(new_name, language):
                    log.warning(
                        "domain_review_rename_skipped_invalid_display_name",
                        slug=slug,
                        new_name=new_name,
                        language=language,
                    )
                    continue
                reason = rename.get("reason", "llm rename")
                self._propose_rename(slug, new_name, reason if isinstance(reason, str) else "llm rename")

        moves = parsed.get("moves", [])
        if isinstance(moves, list):
            for move in moves:
                if not isinstance(move, dict):
                    continue
                mod_name = move.get("module", "")
                from_d = move.get("from", "")
                to_d = move.get("to", "")
                if not all([mod_name, from_d, to_d]):
                    continue
                reason = move.get("reason", "llm move")
                result = self._propose_move(
                    mod_name,
                    from_d,
                    to_d,
                    reason if isinstance(reason, str) else "llm move",
                )
                if result.get("status") == "accepted":
                    log.info("domain_review_move", module=mod_name, from_d=from_d, to_d=to_d)

        new_mapping = self.apply_decisions()
        new_display = dict(domain_display_names)

        for merge in self.pending_merges:
            target = merge["target"]
            new_name = merge.get("new_display_name", "")
            if isinstance(new_name, str) and new_name and GraphSemanticCorrector._accept_display_name(new_name, language):
                new_display[target] = new_name
                log.info("domain_review_merge", target=target, new_name=new_name)

        for rename in self.pending_renames:
            slug = rename["slug"]
            new_name = rename["new_display_name"]
            if slug in new_display and isinstance(new_name, str) and new_name:
                if GraphSemanticCorrector._accept_display_name(new_name, language):
                    new_display[slug] = new_name
                    log.info("domain_review_rename", slug=slug, new_name=new_name)

        for slug in list(new_display):
            if slug not in new_mapping:
                new_display.pop(slug)

        return new_mapping, new_display
