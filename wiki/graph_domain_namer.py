"""LLM-based domain naming for graph communities."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

from core.log import get_logger
from wiki.cypher_queries import METHODS_CY
from wiki.json_robust import parse_json_robust_sync
from wiki.nodes.domain_filters import is_denied_slug
from wiki.path_conventions import normalize_slug, normalize_slug_strict
from wiki.persistence import compute_domain_module_signature
from wiki.prompts import SYSTEM_JSON_ONLY

log = get_logger(__name__)

_NAMING_PROMPT_V2 = (
    "You are naming a group of code modules for a business documentation wiki.\n"
    "These modules were grouped by their semantic similarity (business function).\n"
    "{business_context_block}\n"
    "Module details:\n"
    "{module_details}\n\n"
    "Rules:\n"
    "- Name the BUSINESS capability these modules provide, not code structure\n"
    "- CRITICAL: display_name MUST be concise Chinese (2-6 Chinese characters), "
    "e.g. '好友关系', '家族系统', '用户资料'. NEVER use English for display_name\n"
    "- Prefer terms that appear in the code's own comments or class-level documentation\n"
    "- The slug should be kebab-case ASCII describing the business capability\n"
    "- Do NOT name based on technical patterns (Handler, Service, Dao, etc.)\n"
    "- slug must semantically match display_name (e.g. if display_name is '好友关系', "
    "slug should be 'friend-relation' or 'friendship', NOT unrelated words)\n"
    "- Each domain must contain at least 3 core modules; "
    "do NOT name a domain after a single utility or helper module\n"
    "{used_names_block}\n"
    'Return ONLY valid JSON: {{"slug": "...", "display_name": "...", "description": "..."}}'
)

def _has_chinese(text: str) -> bool:
    return any("\u4e00" <= ch <= "\u9fff" for ch in text)


_TECH_SUFFIXES = frozenset({
    "Handler", "Service", "Manager", "Executor", "Provider",
    "Dao", "Controller", "Impl", "WebService", "Listener",
    "Processor", "Worker", "Helper", "Adapter", "Factory",
})


def _extract_common_prefix(module_names: list[str]) -> str:
    if not module_names:
        return ""
    if len(module_names) == 1:
        return module_names[0]

    prefix = module_names[0]
    for name in module_names[1:]:
        while prefix and not name.startswith(prefix):
            prefix = prefix[:-1]
        if not prefix:
            return module_names[0]
    return prefix


def _sanitize_denied_slug(slug: str, *, display_name: str = "") -> str:
    if is_denied_slug(slug):
        log.warning("graph_domain_namer_denied_slug", slug=slug, display_name=display_name)
        return f"{slug}-domain"
    return slug


def _module_tuples_for_signature(
    module_infos: list[dict[str, str]] | None,
    module_names: list[str] | None,
) -> list[tuple[str, str]]:
    if module_infos:
        return [
            (
                str(info.get("repository", "")),
                str(info.get("name") or info.get("module_name", "")),
            )
            for info in module_infos
        ]
    if module_names:
        return [("", name) for name in module_names]
    return []


def _method_display(func_name: str, signature: str) -> str:
    """Format a concise method label for code-outline context."""
    name = (func_name or "").strip()
    sig = (signature or "").strip()
    if not name:
        return ""
    if not sig:
        return name
    if len(sig) <= 50 and "(" in sig:
        compact = re.sub(r"\s+", "", sig.split("(", 1)[0] + "(" + sig.split("(", 1)[1])
        if compact.startswith(name):
            return compact
        paren = sig.find("(")
        if paren >= 0:
            return name + sig[paren:].replace(" ", "")
    return name


def _methods_budget_for_rank(rank: float | None, *, max_methods: int = 5) -> int:
    """Allocate method slots by PageRank tier (top 30% / mid / low)."""
    if rank is None:
        return max_methods
    if rank >= 0.7:
        return max_methods
    if rank >= 0.35:
        return min(3, max_methods)
    return 1


def format_code_outline(
    module_outlines: dict[str, list[str]],
    *,
    module_names: list[str] | None = None,
    max_methods_per_module: int = 5,
    max_total_lines: int = 30,
    module_ranks: dict[str, float] | None = None,
) -> str:
    """Format module method lists as a concise code-outline block."""
    if not module_outlines:
        return ""

    ordered_names = list(module_names) if module_names else sorted(module_outlines)
    outline_lines: list[str] = []
    for name in ordered_names:
        methods = module_outlines.get(name) or []
        if not methods:
            continue
        budget = _methods_budget_for_rank(
            module_ranks.get(name) if module_ranks else None,
            max_methods=max_methods_per_module,
        )
        shown = methods[:budget]
        if not shown:
            outline_lines.append(f"  {name}")
            continue
        outline_lines.append(f"  {name}: {', '.join(shown)}")

    if not outline_lines:
        return ""

    max_module_lines = max(1, max_total_lines - 1)
    trimmed = outline_lines[:max_module_lines]
    return "Code outline:\n" + "\n".join(trimmed)


async def fetch_module_outlines(
    graph_store: Any,
    module_names: list[str],
    *,
    max_methods_per_module: int = 5,
    module_ranks: dict[str, float] | None = None,
) -> dict[str, list[str]]:
    """Fetch top function signatures grouped by module name."""
    if not module_names or graph_store is None or not hasattr(graph_store, "execute_query"):
        return {}

    unique_names = list(dict.fromkeys(name for name in module_names if name))
    if not unique_names:
        return {}

    try:
        result = await graph_store.execute_query(METHODS_CY, {"names": unique_names})
    except Exception:
        log.warning("namer_methods_query_failed", module_count=len(unique_names), exc_info=True)
        return {}

    rows = getattr(result, "data", None) or []
    grouped: dict[str, list[str]] = {}
    seen: dict[str, set[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        mod_name = str(row.get("module_name", "") or "")
        func_name = str(row.get("func_name", "") or "")
        if not mod_name or not func_name:
            continue
        display = _method_display(func_name, str(row.get("signature", "") or ""))
        if not display:
            continue
        seen.setdefault(mod_name, set())
        if display in seen[mod_name]:
            continue
        seen[mod_name].add(display)
        grouped.setdefault(mod_name, []).append(display)

    for mod_name in grouped:
        grouped[mod_name] = grouped[mod_name][:max_methods_per_module]

    log.debug(
        "namer_module_outlines_fetched",
        modules=len(grouped),
        methods=sum(len(v) for v in grouped.values()),
    )
    return grouped


async def fetch_code_outline_for_namer(
    graph_store: Any,
    module_names: list[str],
    *,
    max_methods_per_module: int = 5,
    max_total_lines: int = 30,
    module_ranks: dict[str, float] | None = None,
) -> str:
    """Fetch top function signatures and format as concise code outline."""
    outlines = await fetch_module_outlines(
        graph_store,
        module_names,
        max_methods_per_module=max_methods_per_module,
        module_ranks=module_ranks,
    )
    return format_code_outline(
        outlines,
        module_names=module_names,
        max_methods_per_module=max_methods_per_module,
        max_total_lines=max_total_lines,
        module_ranks=module_ranks,
    )


def budget_module_details(
    module_infos: list[dict],
    *,
    module_ranks: dict[str, float] | None = None,
    max_lines: int = 40,
    full_ratio: float = 0.3,
    names_ratio: float = 0.3,
) -> list[str]:
    """Aider-style tiered context: full details → names only → omitted.

    Args:
        module_infos: list of module info dicts with name, path, summary
        module_ranks: PageRank scores; if None, all modules treated equally
        max_lines: hard cap on output lines
        full_ratio: top X% get full detail lines
        names_ratio: next X% get name-only lines

    Returns:
        list of formatted detail lines within budget
    """
    if not module_infos:
        return []

    if module_ranks:
        sorted_infos = sorted(
            module_infos,
            key=lambda m: module_ranks.get(m.get("name", ""), 0),
            reverse=True,
        )
    else:
        sorted_infos = list(module_infos)

    n = len(sorted_infos)
    full_count = max(1, int(n * full_ratio))
    names_count = max(0, int(n * names_ratio))

    lines: list[str] = []
    for i, info in enumerate(sorted_infos):
        if len(lines) >= max_lines:
            break
        name = info.get("name", "")
        if i < full_count:
            path = info.get("path", "")
            summary = info.get("summary", "")[:80]
            line = f"- {name}"
            if path:
                line += f" ({path})"
            if summary:
                line += f": {summary}"
            lines.append(line)
        elif i < full_count + names_count:
            lines.append(f"- {name}")

    if n > full_count + names_count:
        lines.append(f"  ... and {n - full_count - names_count} more modules")

    return lines


def _fallback_name(module_names: list[str]) -> dict[str, str]:
    stripped = []
    for name in module_names:
        words = re.findall(r"[A-Z][a-z]+", name)
        while words and words[-1] in _TECH_SUFFIXES:
            words.pop()
        stripped.append("".join(words) if words else name)

    common = _extract_common_prefix(stripped)
    display_name = common or (stripped[0] if stripped else "unnamed")
    slug = _sanitize_denied_slug(normalize_slug(display_name), display_name=display_name)
    return {
        "slug": slug,
        "display_name": display_name,
        "description": f"Modules: {', '.join(module_names)}" if module_names else "",
    }


class GraphDomainNamer:
    """Name graph communities using LLM."""

    def __init__(
        self,
        llm: LLMPort | None,
        *,
        project_docs: list[dict] | None = None,
        naming_cache: dict[str, dict[str, str]] | None = None,
        module_outlines: dict[str, list[str]] | None = None,
        module_ranks: dict[str, float] | None = None,
    ):
        self._llm = llm
        self._project_docs = project_docs or []
        self._naming_cache = naming_cache if naming_cache is not None else {}
        self._module_outlines = module_outlines
        self._module_ranks = module_ranks

    async def name_community(
        self,
        module_names: list[str] | None = None,
        *,
        module_infos: list[dict[str, str]] | None = None,
        used_names: list[str] | None = None,
        business_id: str = "",
        module_ranks: dict[str, float] | None = None,
    ) -> dict[str, str]:
        """Name a community based on module names or detailed infos.

        Returns: {"slug": "family-system", "display_name": "家族系统", "description": "..."}
        Falls back to first module name based slug if LLM fails after retry.
        """
        if module_infos:
            ranks = module_ranks if module_ranks is not None else self._module_ranks
            detail_lines = budget_module_details(
                module_infos,
                module_ranks=ranks,
                max_lines=40,
            )
            names_for_fallback = [info.get("name", "") for info in module_infos]
        elif module_names:
            detail_lines = [f"- {n}" for n in module_names]
            names_for_fallback = list(module_names)
        else:
            return _fallback_name([])

        if not detail_lines:
            return _fallback_name(names_for_fallback)

        module_tuples = _module_tuples_for_signature(module_infos, module_names)
        sig = compute_domain_module_signature(module_tuples)
        if sig in self._naming_cache:
            cached = self._naming_cache[sig]
            log.info("namer_cache_hit", signature=sig[:12], slug=cached.get("slug"))
            return dict(cached)

        if self._llm is None:
            result = _fallback_name(names_for_fallback)
            self._naming_cache[sig] = result
            return result

        used_block = ""
        if used_names:
            used_block = (
                "\nIMPORTANT: These names are already in use, choose a DIFFERENT name:\n"
                + ", ".join(used_names)
                + "\n"
            )

        # Build enhanced business context from F7+F8+F9
        biz_parts: list[str] = []
        if business_id:
            biz_parts.append(f"Business context: {business_id}")

        # F8: File tree context from module paths
        if module_infos:
            file_tree = _build_file_tree_context(module_infos)
            if file_tree:
                biz_parts.append(file_tree)

        # F9: Topology-derived label hint
        if module_infos:
            topo = _topology_label(module_infos)
            if topo.get("slug_hint") and topo.get("confidence", 0) >= 0.6:
                biz_parts.append(
                    f"Topology hint: modules share prefix '{topo['slug_hint']}' "
                    f"(confidence: {topo['confidence']:.0%}). Consider this as domain name basis."
                )

        # F7: Project documentation context
        if self._project_docs:
            from wiki.project_doc_provider import format_for_namer

            proj_ctx = format_for_namer(self._project_docs)
            if proj_ctx:
                biz_parts.append(proj_ctx)

        # G6: Code outline from function signatures
        if self._module_outlines:
            outline_names = names_for_fallback
            outline = format_code_outline(
                self._module_outlines,
                module_names=outline_names,
                module_ranks=self._module_ranks,
            )
            if outline:
                biz_parts.append(outline)

        biz_block = "\n".join(biz_parts) if biz_parts else ""
        if biz_block:
            biz_block = "\n" + biz_block + "\n"

        prompt = _NAMING_PROMPT_V2.format(
            module_details="\n".join(detail_lines),
            used_names_block=used_block,
            business_context_block=biz_block,
        )

        for attempt in range(2):
            try:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                parsed = parse_json_robust_sync(raw)
                if isinstance(parsed, dict):
                    slug = parsed.get("slug")
                    display_name = parsed.get("display_name")
                    description = parsed.get("description")
                    if isinstance(slug, str) and slug and isinstance(display_name, str) and display_name:
                        if not _has_chinese(display_name):
                            log.warning("graph_domain_namer_non_chinese_display", display_name=display_name, slug=slug)
                        validated_slug = normalize_slug_strict(slug)
                        if not validated_slug:
                            validated_slug = normalize_slug_strict(display_name)
                        if not validated_slug:
                            fallback = _fallback_name(names_for_fallback)
                            validated_slug = normalize_slug_strict(fallback["slug"])
                        if not validated_slug:
                            validated_slug = f"domain-{len(names_for_fallback)}"
                        validated_slug = _sanitize_denied_slug(validated_slug, display_name=display_name)
                        result = {
                            "slug": validated_slug,
                            "display_name": display_name,
                            "description": str(description) if description is not None else "",
                        }
                        self._naming_cache[sig] = result
                        return result
            except Exception:
                if attempt == 0:
                    log.warning("graph_domain_namer_retry", module_count=len(names_for_fallback), exc_info=True)
                    continue
                log.warning("graph_domain_namer_llm_failed", module_count=len(names_for_fallback), exc_info=True)

        result = _fallback_name(names_for_fallback)
        self._naming_cache[sig] = result
        return result

    async def name_communities_batch(
        self,
        communities: list[list[str]],
        *,
        used_names: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Name multiple communities. Returns list in same order as input."""
        all_used = list(used_names) if used_names else []
        results = []
        for modules in communities:
            result = await self.name_community(modules, used_names=all_used)
            all_used.append(result["slug"])
            results.append(result)
        return results


def _build_file_tree_context(modules: list[dict]) -> str:
    """Build a concise directory tree from community module paths (Cline-inspired)."""
    from collections import defaultdict

    dirs: defaultdict[str, list[str]] = defaultdict(list)
    for m in modules:
        path = m.get("path") or ""
        if not path:
            continue
        parts = path.replace("\\", "/").rsplit("/", 1)
        dir_part = parts[0] if len(parts) > 1 else ""
        file_part = parts[-1]
        if dir_part:
            dirs[dir_part].append(file_part)

    if not dirs:
        return ""

    lines = ["Directory structure of this module group:"]
    for dir_path in sorted(dirs.keys()):
        files = sorted(dirs[dir_path])[:8]
        lines.append(f"  {dir_path}/")
        for f in files:
            lines.append(f"    {f}")
        if len(dirs[dir_path]) > 8:
            lines.append(f"    ... (+{len(dirs[dir_path]) - 8} more)")

    return "\n".join(lines)


def _extract_business_prefix_from(name: str, path: str) -> str | None:
    """Extract business prefix from module name or path."""
    import re

    if path:
        segments = path.replace("\\", "/").split("/")
        for seg in segments:
            if seg and seg.lower() not in {"src", "main", "java", "com", "kotlin", "python", "lib", "internal", "pkg"}:
                clean = seg.split(".")[0].lower()
                if clean and len(clean) > 2:
                    return clean
    words = re.findall(r"[A-Z][a-z]+", name)
    skip = {"Abstract", "Base", "Default", "Mock", "Test", "I"}
    for word in words:
        if word not in skip and word.lower() not in {"service", "dao", "handler", "controller", "manager", "impl"}:
            return word.lower()
    return None


def _topology_label(modules: list[dict]) -> dict[str, Any]:
    """Derive a domain label from module name topology (RepoNova-inspired).

    Uses majority-vote on business prefixes extracted from module names.
    Zero LLM tokens — pure string analysis.
    """
    from collections import Counter

    prefixes: list[str] = []
    for m in modules:
        name = m.get("name") or ""
        path = m.get("path") or ""
        prefix = _extract_business_prefix_from(name, path)
        if prefix:
            prefixes.append(prefix)

    if not prefixes:
        return {"slug_hint": "", "confidence": 0.0}

    counter = Counter(prefixes)
    total = len(prefixes)
    top_prefix, top_count = counter.most_common(1)[0]

    confidence = top_count / total
    if confidence < 0.4:
        return {"slug_hint": "", "confidence": confidence}

    return {"slug_hint": top_prefix, "confidence": confidence}
