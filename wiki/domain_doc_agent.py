"""Per-domain Agent: skeleton-first, then progressive enrichment.

Wraps WikiPageAgent with iterative quality-driven refinement,
Explore/Write two-phase separation, and document splitting.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import networkx as nx
from pydantic import BaseModel, field_validator

from core.config import ContentLanguage, get_settings
from core.log import get_logger
from wiki.agents.base_agent import RunConfig
from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
from wiki.content_guards import derive_semantic_title, is_compound_module_title
from wiki.output_guardrail import (
    CoverageCheck,
    FormatCheck,
    LanguageConsistencyCheck,
    LengthCheck,
    OutputGuardrailChain,
    SensitiveContentCheck,
)
from wiki.page_agent import WikiPageAgent, WorkingMemory
from wiki.quality_report import evaluate_quality
from wiki.quality_trace import AgentTrace, TraceCollector

log = get_logger(__name__)

_DOMAIN_EXPLORE_LOOP_CONFIG = RunConfig(
    enable_context_trim=True,
    enable_compaction=True,
    compaction_interval=8,
    compaction_keep_recent=4,
    micro_compact_tool_threshold=15_000,
)


class TopicPlanItem(BaseModel):
    """Structured topic plan item with Part N rejection."""

    title: str
    slug: str
    module_names: list[str]
    description: str = ""

    @field_validator("title")
    @classmethod
    def reject_part_n_naming(cls, v: str) -> str:
        """Reject mechanical Part N / 第N部分 naming patterns."""
        if re.search(r"(?i)^(part\s*\d+|第\s*\d+\s*部分)", v.strip()):
            raise ValueError(
                f"Part N naming pattern detected: '{v}'. "
                "Use descriptive topic names instead (e.g., 'Authentication Architecture')."
            )
        return v

    @field_validator("title")
    @classmethod
    def reject_compound_module_title(cls, v: str) -> str:
        """Reject repo/path|ClassName compound keys used as display titles."""
        if is_compound_module_title(v.strip()):
            raise ValueError(
                f"Compound module title detected: '{v}'. "
                "Use a human-readable semantic title instead."
            )
        return v


class TopicPlan(BaseModel):
    """Structured topic plan for domain documentation."""

    domain: str
    items: list[TopicPlanItem] = []


_PART_N_TITLE_PREFIX = re.compile(r"(?i)^(?:part\s*\d+\s*[:：\-]?\s*|第\s*\d+\s*部分\s*[:：\-]?\s*)")
_MECHANICAL_TOPIC_TITLE_RE = re.compile(r"(?i)^(?:part\s*\d+|第\s*\d+\s*部分)$")


def _is_mechanical_topic_name(title: str) -> bool:
    """Return True when title is a bare Part N / 第N部分 label."""
    return bool(_MECHANICAL_TOPIC_TITLE_RE.match(title.strip()))


def _rename_mechanical_topic_title(
    title: str,
    modules: list[str],
    *,
    domain_display_name: str = "",
    summaries: dict[str, dict] | None = None,
) -> str:
    """Replace bare Part N titles with module-based descriptive names."""
    if not _is_mechanical_topic_name(title):
        return title
    if not modules:
        return title
    if len(modules) == 1:
        result = modules[0]
    else:
        result = f"{modules[0]} & {modules[1]}"
    if is_compound_module_title(result):
        result = derive_semantic_title(modules, domain_display_name, summaries or {}, None)
    return result


def _strip_part_n_title(title: str) -> str:
    """Remove mechanical Part N / 第N部分 prefix from a topic title."""
    stripped = _PART_N_TITLE_PREFIX.sub("", title.strip()).strip()
    return stripped or title


def _validate_topic_plan_outline(outline: DomainTopicOutline) -> DomainTopicOutline:
    """Validate topic titles via TopicPlanItem; rename Part N patterns in-place."""
    from pydantic import ValidationError

    if not get_settings().wiki.reject_mechanical_topic_names:
        return outline

    sanitized: list[OutlineTopicItem] = []
    for topic in outline.topics:
        slug = topic.slug or _derive_slug_from_modules(topic.modules)
        try:
            TopicPlanItem(
                title=topic.title,
                slug=slug,
                module_names=topic.modules,
                description=topic.description,
            )
            sanitized.append(topic)
        except ValidationError:
            new_title = _strip_part_n_title(topic.title)
            if _is_mechanical_topic_name(new_title):
                new_title = _rename_mechanical_topic_title(new_title, list(topic.modules))
            elif is_compound_module_title(new_title):
                new_title = derive_semantic_title(list(topic.modules), "", {}, None)
            log.warning(
                "topic_plan_part_n_renamed",
                original=topic.title,
                renamed=new_title,
                modules=topic.modules[:3],
            )
            sanitized.append(
                OutlineTopicItem(
                    title=new_title,
                    modules=list(topic.modules),
                    description=topic.description,
                    slug=topic.slug,
                )
            )
    return DomainTopicOutline(should_split=outline.should_split, topics=sanitized)


@dataclass
class OutlineTopicItem:
    title: str
    modules: list[str]
    description: str = ""
    slug: str = ""


@dataclass
class DomainTopicOutline:
    should_split: bool
    topics: list[OutlineTopicItem]


def domain_has_subdomains(domain: dict[str, Any]) -> bool:
    """Return True when a domain dict has child sub-domains."""
    children = domain.get("children") or domain.get("subdomains") or []
    return bool(children)


def _format_subdomain_baseline(subdomains: list[dict[str, Any]]) -> str:
    """Build baseline subsection listing child sub-domains for container overview prompts."""
    if not subdomains:
        return ""
    lines = ["### 子域列表"]
    for sub in subdomains:
        name = str(sub.get("display_name") or sub.get("name") or "")
        if not name:
            continue
        slug = str(sub.get("name") or name)
        desc = str(sub.get("description") or "").strip()
        mod_count = len(sub.get("modules") or [])
        meta = f"（{mod_count} 个模块）" if mod_count else ""
        lines.append(f"- **{name}** (`{slug}`){meta}" + (f": {desc}" if desc else ""))
    return "\n".join(lines)


def _extract_cjk_bigrams(title: str) -> set[str]:
    """Extract CJK character bigrams for fuzzy matching."""
    chars = [c for c in title if "\u4e00" <= c <= "\u9fff"]
    if len(chars) < 2:
        return set(chars)
    return {chars[i] + chars[i + 1] for i in range(len(chars) - 1)}


def _cap_topic_outline(outline: DomainTopicOutline, max_topics: int) -> DomainTopicOutline:
    """Truncate topic list to configured maximum per domain."""
    if len(outline.topics) <= max_topics:
        return outline
    return DomainTopicOutline(
        should_split=outline.should_split,
        topics=outline.topics[:max_topics],
    )


def _dedup_topic_titles(topics: list[OutlineTopicItem]) -> list[OutlineTopicItem]:
    """Merge topics with duplicate or semantically similar titles."""
    result: list[OutlineTopicItem] = []
    seen_exact: dict[str, int] = {}
    seen_bigrams: list[set[str]] = []

    for t in topics:
        if t.title in seen_exact:
            idx = seen_exact[t.title]
            for m in t.modules:
                if m not in result[idx].modules:
                    result[idx].modules.append(m)
            continue

        bigrams = _extract_cjk_bigrams(t.title)
        merged = False
        if bigrams:
            for i, existing_bg in enumerate(seen_bigrams):
                if not existing_bg:
                    continue
                overlap = len(bigrams & existing_bg) / max(len(bigrams), len(existing_bg), 1)
                if overlap >= 0.6:
                    for m in t.modules:
                        if m not in result[i].modules:
                            result[i].modules.append(m)
                    merged = True
                    break

        if not merged:
            seen_exact[t.title] = len(result)
            seen_bigrams.append(bigrams)
            result.append(OutlineTopicItem(title=t.title, modules=list(t.modules), description=t.description))

    return result


def _edge_endpoint_key(edge: dict[str, Any], side: str) -> str:
    """Resolve a call-edge endpoint to a module key (compound or bare name)."""
    compound = edge.get(f"{side}_key")
    if isinstance(compound, str) and compound:
        return compound
    repo = edge.get(f"{side}_repo", "")
    name = str(edge.get(side, "") or "")
    if repo:
        return f"{repo}|{name}"
    return name


def compute_module_pagerank(
    module_names: list[str],
    call_edges: list[dict[str, Any]] | None = None,
) -> dict[str, float]:
    """Compute PageRank for modules within a domain subgraph.

    Args:
        module_names: modules in this domain
        call_edges: pipeline state module_call_edges (list of dicts with source, target, weight)

    Returns:
        dict mapping module name → PageRank score (0.0-1.0 normalized)
    """
    if not module_names:
        return {}

    module_set = set(module_names)
    graph: nx.DiGraph = nx.DiGraph()
    graph.add_nodes_from(module_names)

    for edge in call_edges or []:
        if not isinstance(edge, dict):
            continue
        src = _edge_endpoint_key(edge, "source")
        tgt = _edge_endpoint_key(edge, "target")
        if src not in module_set or tgt not in module_set:
            continue
        weight_raw = edge.get("weight", 1)
        try:
            weight = float(weight_raw)
        except (TypeError, ValueError):
            weight = 1.0
        if weight <= 0:
            weight = 1.0
        graph.add_edge(src, tgt, weight=weight)

    if graph.number_of_edges() == 0:
        return dict.fromkeys(module_names, 1.0)

    raw = nx.pagerank(graph, weight="weight")
    scores = [float(raw.get(name, 0.0)) for name in module_names]
    min_score = min(scores)
    max_score = max(scores)
    if max_score == min_score:
        return dict.fromkeys(module_names, 1.0)
    span = max_score - min_score
    return {name: (float(raw.get(name, 0.0)) - min_score) / span for name in module_names}


def _common_camel_prefix(names: list[str]) -> str:
    """Extract common CamelCase prefix from module names (>= 2 words required)."""
    import re

    if not names or len(names) < 2:
        return ""

    def _camel_words(name: str) -> list[str]:
        return re.findall(r"[A-Z][a-z]+|[A-Z]+(?=[A-Z][a-z]|\d|\b)", name)

    word_lists = [_camel_words(n) for n in names]
    if not all(word_lists):
        return ""

    min_len = min(len(wl) for wl in word_lists)
    common_count = 0
    for i in range(min_len):
        if all(wl[i] == word_lists[0][i] for wl in word_lists):
            common_count += 1
        else:
            break

    if common_count < 2:
        return ""

    return "".join(word_lists[0][:common_count])


def _extract_chunk_title(
    modules: list[dict],
    display_name: str,
    idx: int,
    *,
    summaries: dict[str, dict] | None = None,
    ranks: dict[str, float] | None = None,
) -> str:
    """Extract a semantic title from a module chunk."""
    module_names = [str(m.get("name") or m.get("display_name") or "") for m in modules]
    module_names = [name for name in module_names if name]

    if len(modules) == 1:
        mod_name = modules[0].get("display_name", modules[0].get("name", ""))
        if mod_name and mod_name != display_name:
            candidate = mod_name
            if is_compound_module_title(candidate):
                candidate = derive_semantic_title(module_names, display_name, summaries or {}, None)
            return candidate
    if ranks:
        best = max(modules, key=lambda m: ranks.get(str(m.get("name", "") or ""), 0))
    else:
        best = max(modules, key=lambda m: len(m.get("display_name", m.get("name", ""))))
    candidate = best.get("display_name", best.get("name", ""))
    if candidate and candidate != display_name:
        if is_compound_module_title(candidate):
            candidate = derive_semantic_title(module_names, display_name, summaries or {}, None)
        return candidate
    return f"{display_name} - Section {idx + 1}"


def _derive_slug_from_modules(modules: list[str]) -> str:
    """Derive a kebab-case slug from module names when LLM doesn't provide one."""
    import re as _re

    from wiki.path_conventions import normalize_slug_strict

    if not modules:
        return ""
    first = modules[0]
    # CamelCase → kebab-case
    slug_raw = _re.sub(r"(?<=[a-z0-9])([A-Z])", r"-\1", first)
    slug_raw = _re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", slug_raw)
    return normalize_slug_strict(slug_raw) or ""


def _resolve_topic_slugs(
    topics: list[OutlineTopicItem],
    domain_slug: str,
    used_slugs: set[str] | None = None,
) -> list[OutlineTopicItem]:
    """Apply V9 slug pipeline (F1-F4) and collision detection (F3) to topic plans."""
    from wiki.path_conventions import resolve_topic_slug

    seen = used_slugs if used_slugs is not None else set()
    resolved: list[OutlineTopicItem] = []
    for index, topic in enumerate(topics):
        raw_slug = topic.slug or _derive_slug_from_modules(list(topic.modules)) or topic.title
        slug = resolve_topic_slug(
            raw_slug,
            topic.title,
            domain_slug=domain_slug,
            used_slugs=seen,
            part_index=index + 1,
            topic_index=index + 1,
        )
        resolved.append(
            OutlineTopicItem(
                title=topic.title,
                modules=list(topic.modules),
                description=topic.description,
                slug=slug,
            )
        )
    return resolved


def _parse_topic_outline(
    raw: str,
    *,
    domain_slug: str = "",
    used_slugs: set[str] | None = None,
) -> DomainTopicOutline | None:
    """Parse LLM output into a DomainTopicOutline. Returns None on failure."""
    from wiki.json_robust import parse_json_robust_sync
    from wiki.path_conventions import normalize_slug_strict

    parsed = parse_json_robust_sync(raw)
    if not isinstance(parsed, dict):
        return None
    should_split = parsed.get("should_split")
    topics_raw = parsed.get("topics")
    if should_split is None or not isinstance(topics_raw, list):
        return None
    topics = []
    for t in topics_raw:
        if not isinstance(t, dict):
            continue
        title = t.get("title", "")
        modules = t.get("modules") or t.get("module_keys") or []
        if not title or not isinstance(modules, list):
            continue
        slug_raw = str(t.get("slug", ""))
        slug = normalize_slug_strict(slug_raw) if slug_raw else ""
        if not slug:
            slug = _derive_slug_from_modules([str(m) for m in modules])
        topics.append(
            OutlineTopicItem(
                title=str(title),
                modules=[str(m) for m in modules],
                description=str(t.get("description", "")),
                slug=slug or "",
            )
        )
    if not topics:
        return None
    topics = _dedup_topic_titles(topics)
    if len(topics) > 6:
        topics = topics[:6]
    if domain_slug:
        topics = _resolve_topic_slugs(topics, domain_slug, used_slugs)
    return DomainTopicOutline(should_split=bool(should_split), topics=topics)


def _format_full_plan_context(outline: DomainTopicOutline, current_topic: OutlineTopicItem) -> str:
    """Format complete topic plan for injection into each topic's writing context."""
    lines = ["--- 域主题规划（全局蓝图）---"]
    for i, t in enumerate(outline.topics, 1):
        marker = " ← 当前撰写" if t.title == current_topic.title else ""
        mods = ", ".join(t.modules[:5])
        desc = t.description or "(无描述)"
        lines.append(f"{i}. **{t.title}**{marker}")
        lines.append(f"   模块: {mods}")
        lines.append(f"   描述: {desc}")

    sibling_titles = [t.title for t in outline.topics if t.title != current_topic.title]
    if sibling_titles:
        lines.append("")
        lines.append("「## 相关主题」节只允许引用以下已确认的同域主题标题，")
        lines.append("并根据上方模块列表如实描述（禁止引用或编造其他不存在的主题）：")
        for title in sibling_titles:
            lines.append(f"- {title}")

    return "\n".join(lines)


MAX_PAGE_TOKENS = 5000

EXPLORE_TIMEOUT_SEC = int(os.environ.get("EXPLORE_TIMEOUT_SEC", "240"))
WRITE_TIMEOUT_SEC = int(os.environ.get("WRITE_TIMEOUT_SEC", "180"))
_DOMAIN_AGENT_INNER_MARGIN_SEC = 30
_DEFAULT_DOMAIN_AGENT_TIMEOUT_SEC = 600


def _domain_agent_total_budget_sec() -> int:
    """Inner elapsed budget — stays below outer asyncio.wait_for timeout."""
    from core.config import get_settings

    outer_timeout = get_settings().wiki.domain_agent_timeout_sec
    if not isinstance(outer_timeout, int):
        outer_timeout = _DEFAULT_DOMAIN_AGENT_TIMEOUT_SEC
    return max(1, outer_timeout - _DOMAIN_AGENT_INNER_MARGIN_SEC)


def _filter_baseline_for_topic(baseline: str, topic_modules: set[str]) -> str:
    """Filter baseline to only include topic-relevant modules and edges."""
    lines = baseline.split("\n")
    result: list[str] = []
    in_module_list = False
    in_topology = False

    for line in lines:
        if line.startswith("### 模块列表"):
            in_module_list = True
            in_topology = False
            result.append(line)
            continue
        if line.startswith("### 模块依赖拓扑"):
            in_module_list = False
            in_topology = True
            result.append(line)
            continue
        if line.startswith("### ") or line.startswith("## "):
            in_module_list = False
            in_topology = False
            result.append(line)
            continue

        if in_module_list:
            if line.startswith("- **"):
                mod_name = line.split("**")[1] if "**" in line else ""
                if mod_name in topic_modules:
                    result.append(line)
            else:
                result.append(line)
        elif in_topology:
            if line.startswith("- ") and "→" in line:
                parts = line[2:].split("→")
                src = parts[0].strip()
                tgt = parts[1].strip() if len(parts) > 1 else ""
                if src in topic_modules or tgt in topic_modules:
                    result.append(line)
            else:
                result.append(line)
        else:
            result.append(line)

    return "\n".join(result)


def _extract_tree_edges(
    nodes: list[dict[str, Any]],
    domain_modules: set[str],
    edges: list[tuple[str, str]],
) -> None:
    """Extract parent→child edges from module_tree (list of root dicts)."""
    for node in nodes:
        parent_key = node.get("canonical_key", "")
        for child in node.get("children", []):
            child_key = child.get("canonical_key", "")
            if parent_key and child_key and (parent_key in domain_modules or child_key in domain_modules):
                edges.append((parent_key, child_key))
            _extract_tree_edges([child], domain_modules, edges)


def _build_baseline(
    domain: dict[str, Any],
    module_summaries: dict[str, Any],
    *,
    module_tree: list[dict[str, Any]] | None = None,
) -> str:
    """Build baseline context: domain description + topology + one-line module roles.

    Provides enough structure for Agent to know the domain shape while forcing
    deep code exploration via tools (avoids Issue #008 lazy behavior).
    """
    display = domain.get("display_name", domain["name"])
    parts = [f"## {display}"]
    if domain.get("description"):
        parts.append(domain["description"])

    modules = domain.get("modules", [])
    if modules:
        parts.append("### 模块列表")
        for mod in modules:
            raw = module_summaries.get(mod, "")
            if isinstance(raw, dict):
                text = str(raw.get("summary_text", "") or "")
            else:
                text = str(raw) if raw else ""
            one_liner = text.split("\n")[0][:80] if text else ""
            parts.append(f"- **{mod}**: {one_liner}" if one_liner else f"- **{mod}**")

    if module_tree:
        domain_modules = set(modules)
        relevant_edges: list[tuple[str, str]] = []
        _extract_tree_edges(module_tree, domain_modules, relevant_edges)
        if relevant_edges:
            parts.append("### 模块依赖拓扑")
            for src, tgt in relevant_edges[:20]:
                parts.append(f"- {src} → {tgt}")

    return "\n\n".join(parts)


def _fence_aware_h2_split(content: str) -> list[str]:
    """Split content on ## headings, but only those outside code fences."""
    lines = content.split("\n")
    in_fence = False
    section_starts: list[int] = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and line.startswith("## "):
            section_starts.append(i)

    if not section_starts:
        return [content]

    sections: list[str] = []
    # Content before first ## heading
    if section_starts[0] > 0:
        sections.append("\n".join(lines[: section_starts[0]]))

    for idx, start in enumerate(section_starts):
        end = section_starts[idx + 1] if idx + 1 < len(section_starts) else len(lines)
        sections.append("\n".join(lines[start:end]))

    return [s for s in sections if s.strip()]


def _maybe_split(
    content: str,
    domain_slug: str,
    domain_display_name: str = "",
    *,
    topic_split_done: bool = False,
    language: ContentLanguage = ContentLanguage.ZH_CN,
) -> list[dict[str, Any]]:
    """Split oversized documents by ## sections into topic sub-pages."""
    display = domain_display_name or domain_slug
    if topic_split_done and len(content) < 30000:
        return [_make_page(content, domain_slug, display)]
    estimated_tokens = len(content) // 4
    if estimated_tokens <= MAX_PAGE_TOKENS:
        return [_make_page(content, domain_slug, display)]

    sections = _fence_aware_h2_split(content)
    if len(sections) <= 1:
        return [_make_page(content, domain_slug, display)]

    from wiki.path_conventions import domain_topic_path

    overview = sections[0] if not sections[0].startswith("## ") else ""
    body_sections = sections[1:] if overview else sections

    # Merge adjacent small sections (combined < 1000 tokens)
    merged: list[str] = []
    buf = ""
    for section in body_sections:
        if buf and (len(buf) + len(section)) // 4 < 1000:
            buf += "\n" + section
        else:
            if buf:
                merged.append(buf)
            buf = section
    if buf:
        merged.append(buf)

    max_split_topics = 8
    while len(merged) > max_split_topics:
        min_idx = min(range(len(merged) - 1), key=lambda i: len(merged[i]) + len(merged[i + 1]))
        merged[min_idx] = merged[min_idx] + "\n" + merged.pop(min_idx + 1)

    child_pages: list[dict[str, Any]] = []
    child_links: list[str] = []

    for section in merged:
        title_match = re.match(r"^## (.+)", section)
        fallback = "未命名" if language.is_chinese else "Untitled"
        section_title = title_match.group(1).strip() if title_match else fallback
        topic_path = domain_topic_path(domain_slug, section_title)
        child_pages.append(
            {
                "page_type": "topic",
                "title": section_title,
                "path": topic_path,
                "content": section,
                "diagrams": [],
                "source_locations": [],
                "metadata": {
                    "node_count": 0,
                    "edge_count": 0,
                    "generation_mode": "agent",
                },
            }
        )
        child_links.append(f"- [[{domain_slug}/{section_title}]]")

    if not overview.strip():
        overview = f"# {display}\n\n"
    nav_heading = "## 章节导航" if language.is_chinese else "## Section Navigation"
    parent_content = overview + f"\n{nav_heading}\n\n" + "\n".join(child_links)
    parent_page = _make_page(parent_content, domain_slug, display)

    return [parent_page, *child_pages]


def _extract_executive_summary(content: str, max_len: int = 300) -> str:
    """Extract the first non-heading paragraph as executive summary."""
    if not content:
        return ""
    for line in content.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        if stripped.startswith("```"):
            continue
        if stripped.startswith("|"):
            continue
        if stripped.startswith("-") or stripped.startswith("*"):
            continue
        return stripped[:max_len]
    return ""


def _inject_executive_summaries(pages: list[dict[str, Any]]) -> None:
    for page in pages:
        if "metadata" not in page:
            page["metadata"] = {}
        if not page["metadata"].get("executive_summary"):
            page["metadata"]["executive_summary"] = _extract_executive_summary(page.get("content", ""))


def _check_language_consistency(content: str, target_language: str) -> float:
    """Score heading language consistency. Returns 0.0-1.0."""
    headings = re.findall(r"^#{1,3}\s+(.+)", content, re.MULTILINE)
    if not headings:
        return 1.0

    if "中文" in target_language:
        cn_headings = sum(1 for h in headings if any("\u4e00" <= c <= "\u9fff" for c in h))
        return cn_headings / len(headings)

    en_headings = sum(1 for h in headings if not any("\u4e00" <= c <= "\u9fff" for c in h))
    return en_headings / len(headings)


def _make_page(content: str, slug: str, display_name: str = "") -> dict[str, Any]:
    from wiki.path_conventions import domain_overview_path

    return {
        "page_type": "domain_overview",
        "title": display_name or slug,
        "path": domain_overview_path(slug),
        "content": content,
        "business_domain": slug,
        "diagrams": [],
        "source_locations": [],
        "metadata": {
            "node_count": 0,
            "edge_count": 0,
            "generation_mode": "agent",
        },
    }


class DomainDocAgent(DocOrchestrator):
    """Per-domain agent: skeleton-first, then progressive enrichment."""

    def __init__(
        self,
        domain_name: str,
        llm: Any,
        graph_store: Any,
        *,
        domain_display_name: str = "",
        max_iterations: int = 20,
        repo_path: str | None = None,
        repo_paths: dict[str, str] | None = None,
        search_service: Any | None = None,
        budget_resolver: Any | None = None,
        explore_max_rounds: int | None = None,
        explore_max_tool_calls: int | None = None,
        content_language: str = "简体中文",
        term_glossary: dict[str, str] | None = None,
        subdomains: list[dict[str, Any]] | None = None,
        module_call_edges: list[dict[str, Any]] | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None:
        from core.config import get_settings
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM, get_write_system_prompt

        wiki_cfg = get_settings().wiki
        explore_rounds = explore_max_rounds or wiki_cfg.domain_agent_explore_max_rounds
        explore_tool_calls = explore_max_tool_calls or wiki_cfg.domain_agent_explore_max_tool_calls

        self._subdomains = list(subdomains or [])
        is_container = bool(self._subdomains)

        page_agent = WikiPageAgent(
            llm,
            graph_store,
            max_rounds=explore_rounds,
            max_tool_calls=explore_tool_calls,
            repo_path=repo_path,
            search_service=search_service,
            content_language=content_language,
        )
        super().__init__(
            agent=page_agent,
            name=domain_name,
            max_iterations=max_iterations,
            explore_system_prompt=AGENT_EXPLORE_SYSTEM.format(max_rounds=explore_rounds),
            write_system_prompt=get_write_system_prompt(content_language, is_container=is_container),
        )
        self.domain_name = domain_name
        self.domain_display_name = domain_display_name or domain_name
        self.content_language = content_language
        self._is_container_domain = is_container
        self._term_glossary = term_glossary or {}
        self._repo_paths = repo_paths or {}
        self._page_agent = page_agent
        self._budget_resolver = budget_resolver
        self._valid_pairs: list[str] | None = None
        self._module_call_edges: list[dict[str, Any]] = list(module_call_edges or [])
        self._topic_split_done: bool = False
        self._heartbeat = heartbeat
        self.iteration_history: list[dict[str, Any]] = []
        self._output_guardrail = OutputGuardrailChain(
            [
                FormatCheck(),
                CoverageCheck(),
                LengthCheck(),
                LanguageConsistencyCheck(),
                SensitiveContentCheck(),
            ]
        )

    def _get_explore_config(self) -> RunConfig:
        if self._heartbeat is None:
            return _DOMAIN_EXPLORE_LOOP_CONFIG
        from dataclasses import replace

        return replace(_DOMAIN_EXPLORE_LOOP_CONFIG, heartbeat=self._heartbeat)

    def _get_write_config(self) -> RunConfig | None:
        if self._heartbeat is None:
            return None
        return RunConfig(heartbeat=self._heartbeat)

    def _build_write_prompt(self, baseline_context: str, memory: Any) -> str:
        base = super()._build_write_prompt(baseline_context, memory)
        if self._subdomains:
            subdomain_section = _format_subdomain_baseline(self._subdomains)
            if subdomain_section:
                base = base + "\n\n" + subdomain_section
        term_glossary = getattr(self, "_term_glossary", None)
        if term_glossary:
            from wiki.agent_prompts import build_term_glossary_prompt

            glossary_section = build_term_glossary_prompt(term_glossary)
            if glossary_section:
                base += "\n" + glossary_section
        return base

    def _maybe_split(
        self,
        content: str,
        domain_slug: str | None = None,
        domain_display_name: str = "",
    ) -> list[dict[str, Any]]:
        slug = domain_slug or self.domain_name
        display = domain_display_name or self.domain_display_name
        lang = ContentLanguage.from_any(self.content_language)
        return _maybe_split(
            content,
            slug,
            display,
            topic_split_done=self._topic_split_done,
            language=lang,
        )

    async def generate(
        self,
        module_names: list[str],
        baseline_context: str,
    ) -> list[dict[str, Any]]:
        """Skip shell domains with no modules before orchestration."""
        if not module_names and not self._subdomains:
            log.info("skip_shell_domain_no_modules", domain=self.domain_name)
            return []
        return await super().generate(module_names, baseline_context)

    # --- Hook 1: pre_fill ---
    async def pre_fill(
        self,
        memory: Any,
        module_names: list[str],
        *,
        valid_pairs: list[str] | None = None,
    ) -> None:
        """Seed code snippets from graph before exploration."""
        graph = self._page_agent._graph
        if not graph or not module_names:
            return
        try:
            from wiki.cypher_queries import CHUNK_SNIPPETS_CY, SNIPPETS_CY

            pairs = list(valid_pairs if valid_pairs is not None else self._valid_pairs or [])
            bare_names = [str(name) for name in module_names if "|" not in str(name)]
            for name in module_names:
                compound = str(name)
                if "|" in compound and compound not in pairs:
                    pairs.append(compound)
            query_params = {"names": bare_names or [str(n) for n in module_names], "valid_pairs": pairs}

            result = await graph.execute_query(SNIPPETS_CY, query_params)
            for row in getattr(result, "data", None) or []:
                func_name = str(row.get("func_name", ""))
                snippet = str(row.get("snippet", "")).strip()
                file_path = str(row.get("file_path", ""))
                if snippet and hasattr(memory, "code_snippets"):
                    memory.code_snippets.append(f"[{func_name} @ {file_path}]\n{snippet}")
            if hasattr(memory, "code_snippets") and not memory.code_snippets:
                result = await graph.execute_query(CHUNK_SNIPPETS_CY, query_params)
                for row in getattr(result, "data", None) or []:
                    entity_name = str(row.get("entity_name", ""))
                    snippet = str(row.get("snippet", "")).strip()
                    if snippet:
                        memory.code_snippets.append(f"[{entity_name}]\n{snippet}")
                        if len(memory.code_snippets) >= 6:
                            break
        except Exception:
            log.warning("pre_fill_snippets_failed", domain=self.domain_name, exc_info=True)

    # --- Hook 2: evaluate ---
    async def evaluate(self, content: str, module_names: list[str]) -> QualityResult:
        """Evaluate generated content quality via coverage + citation metrics."""
        qr = evaluate_quality(content, module_names)
        return QualityResult(
            coverage=qr.coverage,
            citation_density=qr.citation_density,
            context_gap_count=qr.context_gap_count,
            uncovered_modules=qr.uncovered_modules,
            implementation_depth=qr.implementation_depth,
        )

    # --- Hook 3: is_acceptable ---
    def is_acceptable(self, quality: QualityResult, iteration: int) -> bool:
        """Determine if quality is good enough to stop iterating."""
        if quality.coverage >= 0.95 and quality.citation_density >= 0.5 and quality.context_gap_count == 0:
            return True
        if iteration >= 2 and quality.coverage >= 0.9 and quality.citation_density >= 0.3:
            return True
        if iteration >= 3:
            if quality.coverage >= 0.7:
                self._last_accept_was_forced = True
                log.warning(
                    "quality_forced_accept",
                    coverage=quality.coverage,
                    citation=quality.citation_density,
                    iteration=iteration,
                )
                return True
            return False
        return False

    # --- Hook 4: post_process ---
    def post_process(self, content: str, module_names: list[str], memory: Any) -> list[dict[str, Any]]:
        """Structure output into page dicts with optional splitting."""
        if not content:
            content = self._page_agent._generate_skeleton(module_names, self.domain_name)

        pages = self._maybe_split(content)

        if hasattr(memory, "discovered_entity_uids") and memory.discovered_entity_uids:
            entity_uids = list(memory.discovered_entity_uids)
            log.info(
                "entity_uids_from_explore",
                domain=self.domain_name,
                uid_count=len(entity_uids),
            )
            for page in pages:
                page["covered_entity_uids"] = entity_uids
        return pages

    # --- Optional Hooks (DocOrchestrator) ---
    async def plan_topics(self, memory: Any, module_names: list[str]) -> list[Any] | None:
        if not get_settings().wiki.enable_topic_pages:
            return None

        overview_content = getattr(memory, "final_overview", None) or ""
        overview_len = len(overview_content)
        min_overview_for_topics = get_settings().wiki.min_overview_len_for_topics

        min_modules = get_settings().wiki.plan_topics_min_modules
        should_plan = len(module_names) >= min_modules or overview_len >= min_overview_for_topics
        if not should_plan:
            return None

        wiki_cfg = get_settings().wiki
        max_topics = wiki_cfg.max_topics_per_domain

        outline = await self._plan_topics(module_names, memory)
        outline = _cap_topic_outline(outline, max_topics)
        if outline.should_split and len(outline.topics) > 1:
            self._topic_split_done = True
            self._topic_outline = outline
            return outline.topics
        needs_mechanical_split = (
            (not outline.should_split and len(module_names) >= 2)
            or len(module_names) >= wiki_cfg.topic_force_split_threshold
        )
        if needs_mechanical_split:
            if not outline.should_split and len(module_names) >= 2:
                log.info(
                    "topic_force_override",
                    domain=self.domain_name,
                    modules=len(module_names),
                    reason="modules>=2 requires topic split",
                )
            fallback = self._build_mechanical_topic_split(module_names)
            if fallback and len(fallback.topics) > 1:
                fallback = _cap_topic_outline(fallback, max_topics)
                fallback = _validate_topic_plan_outline(fallback)
                log.info(
                    "plan_topics_force_split_fallback",
                    domain=self.domain_name,
                    modules=len(module_names),
                    topics=len(fallback.topics),
                )
                self._topic_split_done = True
                self._topic_outline = fallback
                return fallback.topics
        return None

    def _build_mechanical_topic_split(
        self,
        module_names: list[str],
        module_ranks: dict[str, float] | None = None,
    ) -> DomainTopicOutline | None:
        """Mechanically split modules into topic groups when LLM declines."""
        chunk_size = 3
        ranks = module_ranks
        if ranks is None and self._module_call_edges:
            ranks = compute_module_pagerank(module_names, self._module_call_edges)
        if ranks:
            sorted_modules = sorted(module_names, key=lambda m: ranks.get(m, 0), reverse=True)
        else:
            sorted_modules = sorted(module_names)
        if len(sorted_modules) == 2:
            chunks = [[sorted_modules[0]], [sorted_modules[1]]]
        elif len(sorted_modules) == 3:
            chunks = [sorted_modules[:2], sorted_modules[2:]]
        else:
            chunks = [sorted_modules[i : i + chunk_size] for i in range(0, len(sorted_modules), chunk_size)]
        if len(chunks) <= 1:
            return None
        if len(chunks) > 2 and len(chunks[-1]) < 3:
            chunks[-2].extend(chunks.pop())
        topics = []
        common_prefix = _common_camel_prefix(sorted_modules)
        for i, chunk in enumerate(chunks):
            if ranks:
                anchor = max(chunk, key=lambda m: ranks.get(m, 0))
                slug = _derive_slug_from_modules([anchor])
            else:
                slug = _derive_slug_from_modules(chunk)
            display_names = [m.removeprefix(common_prefix) or m for m in chunk] if common_prefix else chunk
            module_dicts = [{"name": m, "display_name": d} for m, d in zip(chunk, display_names)]
            title = _extract_chunk_title(
                module_dicts,
                self.domain_display_name,
                i,
                ranks=ranks,
            )
            topics.append(OutlineTopicItem(title=title, modules=chunk, description="", slug=slug))
        topics = _resolve_topic_slugs(
            topics,
            self.domain_name,
            getattr(self, "_global_topic_slugs", None),
        )
        return DomainTopicOutline(should_split=True, topics=topics)

    async def _write_topics(
        self,
        topic_plan: list[Any] | None,
        baseline_context: str,
        memory: Any,
        module_names: list[str],
    ) -> list[dict[str, Any]] | None:
        if not get_settings().wiki.enable_topic_pages:
            return None
        outline = getattr(self, "_topic_outline", None)
        if outline is None or not outline.should_split or len(outline.topics) <= 1:
            return None
        pages = await self._write_with_outline(outline, baseline_context, memory, module_names)
        _inject_executive_summaries(pages)

        wiki_cfg = get_settings().wiki
        if wiki_cfg.topic_split_quality_check:
            low_quality_count = 0
            for page in pages:
                content = page.get("content", "")
                page_modules = page.get("metadata", {}).get("covered_modules", module_names)
                quality = evaluate_quality(content, page_modules)
                if quality.coverage < wiki_cfg.domain_agent_early_exit_quality:
                    low_quality_count += 1
                    log.warning(
                        "topic_page_low_quality",
                        domain=self.domain_name,
                        topic=page.get("title", ""),
                        coverage=quality.coverage,
                    )
            if low_quality_count == len(pages):
                log.warning(
                    "all_topic_pages_low_quality_fallback",
                    domain=self.domain_name,
                    page_count=len(pages),
                )
                return None

        for page in pages:
            content = page.get("content", "")
            if content:
                page_modules = page.get("metadata", {}).get("covered_modules", module_names)
                await self.run_guardrails(content, 0, {"module_names": page_modules})

        if hasattr(memory, "discovered_entity_uids") and memory.discovered_entity_uids:
            entity_uids = list(memory.discovered_entity_uids)
            for page in pages:
                page["covered_entity_uids"] = entity_uids

        self._attach_quality_flags(pages)
        return pages

    def get_phase_timeout(self, phase: str) -> float | None:
        timeouts = {"explore": float(EXPLORE_TIMEOUT_SEC), "write": float(WRITE_TIMEOUT_SEC)}
        return timeouts.get(phase)

    async def run_guardrails(self, content: str, iteration: int, context: dict[str, Any]) -> Any | None:
        if self._output_guardrail is None:
            return None
        result = await self._output_guardrail.evaluate(
            content,
            {
                "module_names": context.get("module_names", []),
                "target_language": self.content_language,
                "cn_ratio_threshold": get_settings().wiki.language_guardrail_cn_ratio,
                "page_type": context.get("page_type", ""),
            },
        )
        if result and not result.passed:
            failed_checks = [n for n, c in result.details.items() if not c.passed]
            should_heal = any(getattr(c, "should_heal", False) for c in result.details.values())
            log.warning(
                "output_guardrail_failed",
                domain=self.domain_name,
                iteration=iteration,
                total_score=result.total_score,
                failed_checks=failed_checks,
                should_heal=should_heal,
            )
            if should_heal:
                return result

        term_glossary = getattr(self, "_term_glossary", None)
        if term_glossary:
            from wiki.output_guardrail import TermConsistencyCheck

            term_check = TermConsistencyCheck()
            term_result = await term_check.evaluate(content, {"term_glossary": term_glossary})
            if term_result.has_violations:
                log.warning(
                    "term_consistency_violations",
                    domain=self.domain_name,
                    iteration=iteration,
                    violations=term_result.violations[:5],
                )

        return None

    def build_iteration_trace(self, iteration: int, quality: Any) -> dict[str, Any] | None:
        trace = {
            "iteration": iteration,
            "coverage": getattr(quality, "coverage", 0),
            "citation_density": getattr(quality, "citation_density", 0),
            "context_gaps": getattr(quality, "context_gap_count", 0),
            "uncovered_count": len(getattr(quality, "uncovered_modules", [])),
        }
        self.iteration_history.append(trace)
        return trace

    # --- Backward-compatible internal helper (renamed from _pre_fill_snippets) ---
    async def _pre_fill_snippets(
        self,
        memory: WorkingMemory,
        module_names: list[str],
        *,
        valid_pairs: list[str] | None = None,
    ) -> None:
        """Backward compat: delegates to pre_fill hook."""
        await self.pre_fill(memory, module_names, valid_pairs=valid_pairs)

    async def _plan_topics(
        self,
        module_names: list[str],
        memory: WorkingMemory,
    ) -> DomainTopicOutline:
        """Plan topic structure via single LLM call after explore phase."""
        min_modules = get_settings().wiki.plan_topics_min_modules
        if len(module_names) < min_modules:
            return DomainTopicOutline(
                should_split=False,
                topics=[
                    OutlineTopicItem(
                        title=self.domain_display_name,
                        modules=list(module_names),
                        description=f"{self.domain_display_name} overview",
                    )
                ],
            )

        from wiki.agent_prompts import get_topic_planner_prompt

        topic_planner_prompt = get_topic_planner_prompt(self.content_language)
        term_glossary = getattr(self, "_term_glossary", None)
        if term_glossary:
            from wiki.agent_prompts import build_term_glossary_prompt

            glossary_section = build_term_glossary_prompt(term_glossary)
            if glossary_section:
                topic_planner_prompt += "\n" + glossary_section

        module_list = "\n".join(f"- {m}" for m in module_names)
        call_info = (
            "\n".join(memory.discovered_call_chains[:20])
            if memory.discovered_call_chains
            else "No call chain data available."
        )

        user_prompt = (
            f"## Domain: {self.domain_display_name}\n\n"
            f"## Module List ({len(module_names)} modules)\n{module_list}\n\n"
            f"## Key Call Relationships\n{call_info}\n"
        )
        messages = [
            {"role": "system", "content": topic_planner_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            llm = self._page_agent._llm
            from wiki.token_budget import resolve_max_tokens

            plan_tokens = resolve_max_tokens(self._budget_resolver, "topic_plan")
            if hasattr(llm, "complete_json"):
                from wiki.llm_schemas import TopicPlanOutput

                result = await llm.complete_json(
                    messages, TopicPlanOutput.model_json_schema(), max_tokens=plan_tokens,
                )
                if isinstance(result, dict):
                    raw = json.dumps(result, ensure_ascii=False)
                else:
                    raw = str(result)
            else:
                raw = await llm.generate(
                    user_prompt,
                    system=topic_planner_prompt,
                    max_tokens=plan_tokens,
                )
                raw = str(raw)
            outline = _parse_topic_outline(
                raw,
                domain_slug=self.domain_name,
                used_slugs=getattr(self, "_global_topic_slugs", None),
            )
            if outline:
                outline = _validate_topic_plan_outline(outline)
                log.info("plan_topics_success", domain=self.domain_name, topics=len(outline.topics))
                return outline
            log.warning("plan_topics_parse_failed", domain=self.domain_name)
            fallback = self._build_mechanical_topic_split(module_names)
            if fallback:
                fallback = _validate_topic_plan_outline(fallback)
                flags = getattr(self, "_pending_quality_flags", None)
                if flags is None:
                    self._pending_quality_flags = []
                    flags = self._pending_quality_flags
                flags.append("PLAN_PARSE_FAILED")
                return fallback
        except Exception:
            log.warning("plan_topics_failed", domain=self.domain_name, exc_info=True)

        return DomainTopicOutline(
            should_split=False,
            topics=[
                OutlineTopicItem(
                    title=self.domain_display_name,
                    modules=list(module_names),
                    description=f"{self.domain_display_name} overview",
                )
            ],
        )

    async def _write_with_outline(
        self,
        outline: DomainTopicOutline,
        baseline_context: str,
        memory: WorkingMemory,
        module_names: list[str],
    ) -> list[dict[str, Any]]:
        """Write pages according to topic outline."""
        if not outline.should_split or len(outline.topics) <= 1:
            content = await self._page_agent.write(
                self.domain_name,
                baseline_context,
                memory,
            )
            content = await self._verify_code_blocks(content, memory)
            pages = self._maybe_split(content)
            _inject_executive_summaries(pages)
            return pages

        from wiki.path_conventions import domain_topic_path

        topic_pages: list[dict[str, Any]] = []
        topic_links: list[str] = []

        glossary_section = ""
        term_glossary = getattr(self, "_term_glossary", None)
        if term_glossary:
            from wiki.agent_prompts import build_term_glossary_prompt

            glossary_section = build_term_glossary_prompt(term_glossary)

        lang = ContentLanguage.from_any(self.content_language)
        for topic in outline.topics:
            topic_module_list = ", ".join(topic.modules)
            if lang.is_chinese:
                scope_text = (
                    f"--- 主题范围 ---\n"
                    f"你正在撰写「{topic.title}」章节。\n"
                    f"仅聚焦以下模块：{topic_module_list}\n"
                    f"描述：{topic.description}\n"
                )
            else:
                scope_text = (
                    f"--- TOPIC SCOPE ---\n"
                    f'You are writing the "{topic.title}" section.\n'
                    f"Focus ONLY on these modules: {topic_module_list}\n"
                    f"Description: {topic.description}\n"
                )
            plan_context = _format_full_plan_context(outline, topic)
            topic_modules = set(topic.modules)
            topic_baseline = _filter_baseline_for_topic(baseline_context, topic_modules)
            topic_memory = memory.slice_for_modules(topic_modules)
            topic_context = f"{topic_baseline}\n\n{scope_text}\n\n{plan_context}" + glossary_section
            topic_content = await self._page_agent.write(
                self.domain_name,
                topic_context,
                topic_memory,
                page_type="topic",
            )
            topic_content = await self._verify_code_blocks(topic_content, topic_memory)
            topic_module_names = list(topic.modules)
            guardrail_result = await self.run_guardrails(
                topic_content,
                0,
                {
                    "module_names": topic_module_names,
                    "page_type": "topic",
                },
            )
            if guardrail_result is not None:
                log.info(
                    "topic_guardrail_heal_retry",
                    topic=topic.title,
                    domain=self.domain_name,
                )
                heal_hint = (
                    "\n\n--- 重要提示 ---\n"
                    "请务必使用中文撰写全部正文内容。所有章节标题必须使用中文"
                    "（如「## 概述」而非「## Overview」）。"
                    "代码标识符保持英文，但描述性文字必须是中文。\n"
                )
                retry_context = topic_context + heal_hint
                retry_content = await self._page_agent.write(
                    self.domain_name,
                    retry_context,
                    topic_memory,
                    page_type="topic",
                )
                retry_content = await self._verify_code_blocks(retry_content, topic_memory)
                retry_guardrail = await self.run_guardrails(
                    retry_content,
                    1,
                    {"module_names": topic_module_names, "page_type": "topic"},
                )
                if retry_guardrail is None:
                    log.info("topic_guardrail_heal_success", topic=topic.title)
                else:
                    log.warning("topic_guardrail_heal_exhausted", topic=topic.title)
                topic_content = retry_content
            topic_path = domain_topic_path(self.domain_name, topic.slug or topic.title)
            topic_pages.append(
                {
                    "page_type": "topic",
                    "title": topic.title,
                    "path": topic_path,
                    "content": topic_content,
                    "content_language": self.content_language,
                    "canonical_key": self.domain_name,
                    "diagrams": [],
                    "source_locations": [],
                    "metadata": {
                        "node_count": len(topic.modules),
                        "edge_count": 0,
                        "generation_mode": "agent",
                        "covered_modules": list(topic.modules),
                    },
                    "business_domain": self.domain_name,
                }
            )
            topic_links.append(f"- [[{topic.title}]]")

        nav_heading = "## 章节导航" if lang.is_chinese else "## Section Navigation"

        topic_names = ", ".join(t.title for t in outline.topics)
        if lang.is_chinese:
            summary_prompt = (
                f"为「{self.domain_display_name}」域撰写 2-3 段业务概述（200-400 字），"
                f"概括该域的业务价值、整体架构和核心能力。"
                f"该域包含以下子主题：{topic_names}。"
                f"只写概述段落，不要列举子主题。"
            )
        else:
            summary_prompt = (
                f"Write a 2-3 paragraph business overview (200-400 words) for the '{self.domain_display_name}' domain. "
                f"Summarize its business value, architecture, and key capabilities. "
                f"Sub-topics: {topic_names}. Do not list sub-topics."
            )

        summary_text = ""
        try:
            summary_text = await self._page_agent.write(
                self.domain_name,
                summary_prompt,
                memory,
            )
            summary_text = summary_text.strip()
        except Exception:
            log.warning("topic_index_overview_synthesis_failed", domain=self.domain_name, exc_info=True)

        overview_content = (
            f"# {self.domain_display_name}\n\n"
            + (f"{summary_text}\n\n" if summary_text else "")
            + "\n".join(f"## {t.title}\n{t.description}\n" for t in outline.topics)
            + f"\n{nav_heading}\n\n"
            + "\n".join(topic_links)
        )
        overview_page = _make_page(overview_content, self.domain_name, self.domain_display_name)
        overview_page["metadata"]["overview_kind"] = "topic_index"

        pages = [overview_page, *topic_pages]
        _inject_executive_summaries(pages)
        return pages

    async def generate_with_iterations(
        self,
        module_names: list[str],
        baseline_context: str,
        *,
        valid_pairs: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Generate domain documentation with Explore → Write → Quality loop.

        Each phase (explore, write) has its own timeout. Write retries once
        on first timeout. A total elapsed-time budget prevents runaway loops.
        """
        warnings.warn(
            "DomainDocAgent.generate_with_iterations() is deprecated; "
            "prefer DocOrchestrator.generate() via use_orchestrator_template.",
            DeprecationWarning,
            stacklevel=2,
        )
        from core.config import get_settings

        wiki_cfg = get_settings().wiki
        if wiki_cfg.use_orchestrator_template:
            self._valid_pairs = valid_pairs
            pages = await self.generate(module_names, baseline_context)
            _inject_executive_summaries(pages)
            return pages

        start_time = time.monotonic()
        total_budget = _domain_agent_total_budget_sec()
        loop = asyncio.get_running_loop()
        t0 = loop.time()

        def _remaining() -> float:
            return max(0, total_budget - (loop.time() - t0))

        memory = WorkingMemory()
        await self._pre_fill_snippets(memory, module_names, valid_pairs=valid_pairs)
        try:
            timeout = min(EXPLORE_TIMEOUT_SEC, _remaining())
            await asyncio.wait_for(
                self._page_agent.explore(
                    module_names=module_names,
                    domain_name=self.domain_name,
                    baseline_context=baseline_context,
                    memory=memory,
                ),
                timeout=timeout,
            )
        except TimeoutError:
            log.warning(
                "explore_timeout_partial",
                domain=self.domain_name,
                memory_chars=memory._total_chars(),
            )

        # Topic planning after explore
        outline = await self._plan_topics(module_names, memory)
        memory.topic_outline = outline
        if outline.should_split:
            self._topic_split_done = True

        # Early branch: if topic planning says split, skip monolithic write loop
        if outline.should_split and len(outline.topics) > 1:
            pages = await self._write_with_outline(
                outline,
                baseline_context,
                memory,
                module_names,
            )

            from core.config import get_settings

            wiki_cfg = get_settings().wiki
            if wiki_cfg.topic_split_quality_check and _remaining() > 30:
                for page in pages:
                    content = page.get("content", "")
                    page_modules = page.get("metadata", {}).get("covered_modules", module_names)
                    quality = evaluate_quality(content, page_modules)
                    if quality.coverage < wiki_cfg.domain_agent_early_exit_quality:
                        log.info(
                            "topic_split_low_quality",
                            domain=self.domain_name,
                            topic=page.get("title", ""),
                            coverage=quality.coverage,
                        )
                        if quality.uncovered_modules and _remaining() > 20:
                            try:
                                focus_modules = quality.uncovered_modules[:5]
                                timeout = min(30, _remaining())
                                await asyncio.wait_for(
                                    self._page_agent.explore(
                                        module_names=focus_modules,
                                        domain_name=self.domain_name,
                                        baseline_context=baseline_context,
                                        memory=memory,
                                    ),
                                    timeout=timeout,
                                )
                            except TimeoutError:
                                pass

            if memory.discovered_entity_uids:
                entity_uids = list(memory.discovered_entity_uids)
                for page in pages:
                    page["covered_entity_uids"] = entity_uids
            _inject_executive_summaries(pages)
            return pages

        if not module_names:
            content = await self._page_agent.write(
                self.domain_name,
                baseline_context,
                memory,
            )
            content = await self._verify_code_blocks(content, memory)
            pages = self._maybe_split(content)
            if memory.discovered_entity_uids:
                entity_uids = list(memory.discovered_entity_uids)
                for page in pages:
                    page["covered_entity_uids"] = entity_uids
            _inject_executive_summaries(pages)
            return pages

        content = ""
        write_timeout_count = 0
        quality = None

        for iteration in range(self._max_iterations):
            if _remaining() <= 0:
                log.warning("total_budget_exhausted", domain=self.domain_name)
                break

            try:
                timeout = min(WRITE_TIMEOUT_SEC, _remaining())
                content = await asyncio.wait_for(
                    self._page_agent.write(
                        self.domain_name,
                        baseline_context,
                        memory,
                    ),
                    timeout=timeout,
                )
                write_timeout_count = 0
                content = await self._verify_code_blocks(content, memory)
            except TimeoutError:
                write_timeout_count += 1
                log.warning(
                    "write_timeout",
                    domain=self.domain_name,
                    attempt=write_timeout_count,
                )
                if write_timeout_count >= 2:
                    break
                continue

            quality = evaluate_quality(content, module_names)
            from core.config import get_settings

            early_exit = get_settings().wiki.domain_agent_early_exit_quality
            min_chars = get_settings().wiki.domain_agent_early_exit_min_chars
            if quality.coverage >= early_exit and quality.citation_density >= 0.3 and len(content or "") >= min_chars:
                self.iteration_history.append(
                    {
                        "iteration": iteration,
                        "coverage": quality.coverage,
                        "citation_density": quality.citation_density,
                        "context_gaps": quality.context_gap_count,
                        "uncovered_count": len(quality.uncovered_modules),
                    }
                )
                log.info(
                    "agent_early_exit",
                    domain=self.domain_name,
                    coverage=quality.coverage,
                    citation=quality.citation_density,
                )
                break

            guardrail_result = await self._output_guardrail.evaluate(
                content,
                {
                    "module_names": module_names,
                    "target_language": self.content_language,
                    "cn_ratio_threshold": get_settings().wiki.language_guardrail_cn_ratio,
                },
            )
            lang_detail = guardrail_result.details.get("language_consistency")
            log.info(
                "output_guardrail_result",
                domain=self.domain_name,
                iteration=iteration,
                passed=guardrail_result.passed,
                score=guardrail_result.total_score,
                language_consistency=lang_detail.score if lang_detail else None,
            )
            self.iteration_history.append(
                {
                    "iteration": iteration,
                    "coverage": quality.coverage,
                    "citation_density": quality.citation_density,
                    "context_gaps": quality.context_gap_count,
                    "uncovered_count": len(quality.uncovered_modules),
                }
            )

            log.info(
                "domain_agent_iteration",
                domain=self.domain_name,
                iteration=iteration,
                coverage=quality.coverage,
                citation_density=quality.citation_density,
                gaps=quality.context_gap_count,
                depth=getattr(quality, "implementation_depth", 0),
            )

            if (
                quality.coverage >= 0.95
                and quality.citation_density >= 0.5
                and getattr(quality, "implementation_depth", 1.0) >= 0.6
                and quality.context_gap_count == 0
            ):
                log.info("quality_perfect_exit", domain=self.domain_name, iteration=iteration)
                break

            if (
                iteration >= 2
                and quality.coverage >= 0.9
                and quality.citation_density >= 0.3
                and getattr(quality, "implementation_depth", 1.0) >= 0.4
            ):
                log.info(
                    "quality_acceptable_exit",
                    domain=self.domain_name,
                    iteration=iteration,
                    coverage=quality.coverage,
                    citation_density=quality.citation_density,
                )
                break

            if iteration >= 4:
                log.info("quality_max_iteration_exit", domain=self.domain_name, iteration=iteration)
                break

            if _remaining() <= 0:
                break

            supplemental_memory = WorkingMemory()
            try:
                timeout = min(EXPLORE_TIMEOUT_SEC, _remaining())
                await asyncio.wait_for(
                    self._page_agent.explore(
                        module_names,
                        self.domain_name,
                        baseline_context,
                        focus_modules=quality.uncovered_modules or None,
                        memory=supplemental_memory,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                log.warning("reexplore_timeout", domain=self.domain_name)
            finally:
                if supplemental_memory._total_chars() > 0:
                    memory.merge(supplemental_memory)
            if _remaining() <= 0:
                break

        if len(self.iteration_history) >= self._max_iterations:
            log.warning("max_safety_iterations", domain=self.domain_name)

        if not content:
            content = self._page_agent._generate_skeleton(module_names, self.domain_name)

        pages = self._maybe_split(content)
        if memory.discovered_entity_uids:
            entity_uids = list(memory.discovered_entity_uids)
            log.info(
                "entity_uids_from_explore",
                domain=self.domain_name,
                uid_count=len(entity_uids),
            )
            for page in pages:
                page["covered_entity_uids"] = entity_uids

        _inject_executive_summaries(pages)

        try:
            covered = [m for m in module_names if m.lower() in (content or "").lower()]
            trace = AgentTrace(
                domain=self.domain_name,
                page_title=self.domain_display_name or self.domain_name,
                timestamp=datetime.now(UTC),
                explore_rounds=len(self.iteration_history),
                tools_called=[],
                quality_score=quality.coverage if quality else 0.0,
                modules_expected=module_names,
                modules_covered=covered,
                generation_time_ms=int((time.monotonic() - start_time) * 1000),
            )
            collector = TraceCollector()
            await collector.record(trace)
        except Exception:
            log.warning("trace_collection_failed", domain=self.domain_name, exc_info=True)

        return pages
