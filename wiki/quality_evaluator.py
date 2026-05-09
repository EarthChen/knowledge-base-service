"""Wiki page quality evaluation: structural checks, LLM-as-Judge, aggregation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger
from wiki.context_gap import CONTEXT_GAP_DETECT_RE as _CONTEXT_GAP
from wiki.mermaid_validator import validate_mermaid_block
from wiki.harness_evaluator import WikiPageEvaluator
from wiki.models import (
    ImportanceTier,
    WikiPage,
    WikiPageQualityScore,
)
from wiki.page_agent import _THINKING_PREFIX_RE as _THINKING_LEAK_RE

log = get_logger(__name__)


def _l3_dimensions_to_wiki_page_quality(
    page_path: str,
    dims: dict[str, float],
    issues: list[str],
) -> WikiPageQualityScore:
    """Map L3 1–5 dimensions to persisted 0–1 fields (same normalization as quality_gate l3_llm_judge)."""

    def norm_15_to_01(x: float) -> float:
        v = max(1.0, min(5.0, float(x)))
        return round((v - 1.0) / 4.0, 3)

    c = dims["completeness"]
    a = dims["accuracy"]
    r = dims["readability"]
    s = dims["structure"]
    avg_15 = (c + a + r + s) / 4.0
    return WikiPageQualityScore(
        page_path=page_path,
        completeness=norm_15_to_01(c),
        helpfulness=round((norm_15_to_01(r) + norm_15_to_01(s)) / 2.0, 3),
        truthfulness=norm_15_to_01(a),
        overall=round((avg_15 - 1.0) / 4.0, 3),
        issues=list(issues),
        l3_dimensions=dict(dims),
    )

_MERMAID_FENCE = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_MERMAID_VALID_PREFIXES = (
    "sequencediagram",
    "flowchart",
    "graph",
    "classdiagram",
    "statediagram",
)
_TECH_CAMEL = re.compile(r"\b[A-Z][a-z]+(?:[A-Z][a-zA-Z0-9]*)+\b")
_TECH_METHOD = re.compile(r"\b[a-zA-Z_][a-zA-Z0-9_]*\s*\(\s*\)")
_TECH_KEYWORDS = re.compile(
    r"\b(?:JWT|DTO|CRUD|API|HTTP|HTTPS|SQL|JSON|XML|UUID|OAuth|async|await|"
    r"interface|namespace|token|register|validate|sequenceDiagram)\b",
    re.IGNORECASE,
)
_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
_SOURCE_REF = re.compile(r"source://[^\s)\]>]+")
_HTTP_LINK = re.compile(r"https?://[^\s)\]>]+")
_CODE_FENCE = re.compile(r"```")
_FAKE_SOURCE_RE = re.compile(r"com/xxx/|source://src/")

_STRUCT_OVERVIEW_MARKERS = ("## Overview", "## 业务概述", "## 概述")
_STRUCT_COMPONENT_MARKERS = (
    "## Key components",
    "## Methods",
    "## 核心服务要点",
    "## 核心服务详情",
    "## 核心业务流程",
)
_STRUCT_RELATIONSHIP_MARKERS = ("## Relationships", "## 关联主题", "## 关联关系")


def _structural_has_overview(content: str) -> bool:
    return any(m in content for m in _STRUCT_OVERVIEW_MARKERS)


def _structural_has_components(content: str) -> bool:
    return any(m in content for m in _STRUCT_COMPONENT_MARKERS)


def _structural_has_relationships(content: str) -> bool:
    return any(m in content for m in _STRUCT_RELATIONSHIP_MARKERS)


@dataclass
class DepthScore:
    avg_section_length: float  # 平均段落字数（字符计）
    technical_density: float  # 技术术语占比 (0-1)
    has_examples: bool  # 是否包含代码示例
    section_count: int  # 段落数
    overall: float  # 综合得分 (0-1)


@dataclass
class DiagramScore:
    mermaid_block_count: int  # Mermaid 代码块数量
    diagram_types: list[str] = field(default_factory=list)  # 图表类型 (sequence, flowchart 等)
    valid_syntax: bool = False  # 语法是否可能有效
    overall: float = 0.0


@dataclass
class LinkScore:
    wikilink_count: int  # [[wiki-link]] 数量
    source_ref_count: int  # source:// 引用数
    external_link_count: int  # http 链接数
    overall: float = 0.0


@dataclass
class BenchScore:
    structure: Any  # WikiPageQualityScore from structural_check
    depth: DepthScore
    diagrams: DiagramScore
    links: LinkScore
    overall: float  # 加权平均


class WikiQualityEvaluator:
    def __init__(self, llm: Any = None, judge_model: str = "") -> None:
        self._llm = llm
        self._judge_model = judge_model

    def structural_check(self, page: WikiPage) -> WikiPageQualityScore:
        """Quick structural quality assessment without LLM."""
        issues: list[str] = []
        completeness = 0.0
        body = page.content or ""
        checks = [
            (_structural_has_overview(body), "missing_overview", 0.25),
            (_structural_has_components(body), "missing_components", 0.25),
            (_structural_has_relationships(body), "missing_relationships", 0.2),
            (len(body) > 200, "content_too_short", 0.15),
            (len(page.diagrams) > 0, "no_diagrams", 0.15),
        ]
        for present, issue_id, weight in checks:
            if present:
                completeness += weight
            else:
                issues.append(issue_id)

        context_gaps = _CONTEXT_GAP.findall(body)
        if context_gaps:
            issues.append(f"context_gaps:{len(context_gaps)}")
            for gap in context_gaps[:5]:
                log.info("context_gap_detected", page=page.path, gap=gap[:120])

        truthfulness = 1.0
        body_stripped = body.strip()
        if _THINKING_LEAK_RE.match(body_stripped):
            truthfulness -= 0.4
            issues.append("thinking_leak_detected")
        if _FAKE_SOURCE_RE.search(body_stripped):
            truthfulness -= 0.3
            issues.append("fake_source_detected")
        truthfulness = max(0.0, round(truthfulness, 2))

        return WikiPageQualityScore(
            page_path=page.path,
            completeness=round(completeness, 2),
            helpfulness=round(completeness * 0.8, 2),
            truthfulness=truthfulness,
            overall=round(completeness * 0.9 * truthfulness, 2),
            issues=issues,
        )

    def content_depth_check(self, page: WikiPage) -> DepthScore:
        """WikiQualityBench: depth from section size, technical density, and code examples."""
        raw = page.content or ""
        parts = [s.strip() for s in raw.split("## ") if s.strip()]
        section_count = len(parts)
        if section_count == 0:
            avg_len = 0.0
        else:
            avg_len = sum(len(s) for s in parts) / section_count

        words = re.findall(r"\S+", raw)
        word_n = max(len(words), 1)
        tech_hits = (
            len(_TECH_CAMEL.findall(raw))
            + len(_TECH_METHOD.findall(raw))
            + len(_TECH_KEYWORDS.findall(raw))
        )
        technical_density = min(tech_hits / max(word_n * 0.12, 6.0), 1.0)

        fence_pairs = raw.count("```")
        has_examples = fence_pairs >= 2

        avg_length_score = min(avg_len / 100.0, 1.0)
        section_count_score = min(section_count / 6.0, 1.0)
        examples_bonus = 1.0 if has_examples else 0.0
        overall = round(
            0.35 * avg_length_score
            + 0.35 * technical_density
            + 0.15 * examples_bonus
            + 0.15 * section_count_score,
            4,
        )
        return DepthScore(
            avg_section_length=round(avg_len, 2),
            technical_density=round(technical_density, 4),
            has_examples=has_examples,
            section_count=section_count,
            overall=max(0.0, min(1.0, overall)),
        )

    def diagram_quality_check(self, page: WikiPage) -> DiagramScore:
        """WikiQualityBench: Mermaid blocks and lightweight syntax cues."""
        raw = page.content or ""
        bodies = _MERMAID_FENCE.findall(raw)
        mermaid_block_count = len(bodies)
        diagram_types: list[str] = []
        any_type_matched = False
        all_valid = True
        for body in bodies:
            stripped = body.strip()
            first_line = stripped.split("\n", 1)[0].strip() if stripped else ""
            lead = first_line.lower()
            matched = False
            if lead.startswith("sequencediagram"):
                diagram_types.append("sequenceDiagram")
                matched = True
            elif lead.startswith("flowchart"):
                diagram_types.append("flowchart")
                matched = True
            elif lead.startswith("classdiagram"):
                diagram_types.append("classDiagram")
                matched = True
            elif lead.startswith("statediagram"):
                diagram_types.append("stateDiagram")
                matched = True
            elif lead.startswith("graph"):
                diagram_types.append("graph")
                matched = True
            if matched:
                any_type_matched = True
            if not matched and first_line:
                diagram_types.append("unknown")

            validation = validate_mermaid_block(stripped)
            if not validation.is_valid:
                all_valid = False

        valid_syntax = bool(mermaid_block_count > 0 and any_type_matched and all_valid)

        diversity_bonus = min(len(set(diagram_types)) / 2.0, 1.0) if diagram_types else 0.0
        count_part = min(mermaid_block_count / 2.0, 1.0) * 0.6
        syntax_bonus = 0.02 if valid_syntax and mermaid_block_count > 0 else 0.0
        overall = round(count_part + diversity_bonus * 0.4 + syntax_bonus, 4)
        return DiagramScore(
            mermaid_block_count=mermaid_block_count,
            diagram_types=diagram_types,
            valid_syntax=valid_syntax,
            overall=max(0.0, min(1.0, overall)),
        )

    def link_quality_check(self, page: WikiPage) -> LinkScore:
        """WikiQualityBench: wikilinks, source:// refs, and HTTP links."""
        raw = page.content or ""
        wikilink_count = len(_WIKILINK.findall(raw))
        source_ref_count = len(_SOURCE_REF.findall(raw))
        external_link_count = len(_HTTP_LINK.findall(raw))
        total_links = wikilink_count + source_ref_count + external_link_count
        overall = round(min(total_links / 5.0, 1.0), 4)
        return LinkScore(
            wikilink_count=wikilink_count,
            source_ref_count=source_ref_count,
            external_link_count=external_link_count,
            overall=max(0.0, min(1.0, overall)),
        )

    def bench_score(self, page: WikiPage) -> BenchScore:
        """Aggregate WikiQualityBench dimensions with fixed weights."""
        structure = self.structural_check(page)
        depth = self.content_depth_check(page)
        diagrams = self.diagram_quality_check(page)
        links = self.link_quality_check(page)
        overall = round(
            structure.overall * 0.25
            + depth.overall * 0.35
            + diagrams.overall * 0.2
            + links.overall * 0.2,
            4,
        )
        return BenchScore(
            structure=structure,
            depth=depth,
            diagrams=diagrams,
            links=links,
            overall=max(0.0, min(1.0, overall)),
        )

    async def llm_judge_evaluate(
        self,
        page: WikiPage,
        source_code: str = "",
        graph_metadata: str = "",
    ) -> WikiPageQualityScore:
        """LLM judge via ``WikiPageEvaluator.evaluate_l3`` (4 dimensions, 1–5 scale).

        ``source_code`` / ``graph_metadata`` are retained for call compatibility; the L3
        prompt is defined on ``WikiPageEvaluator`` (content + module names only).
        """
        _ = source_code, graph_metadata
        if not self._llm:
            return self.structural_check(page)

        modules = [page.title or page.path]
        harness = WikiPageEvaluator()
        l3_result = await harness.evaluate_l3(
            page.content or "",
            modules,
            self._llm,
            model=self._judge_model or None,
        )
        if not l3_result.dimensions:
            return self.structural_check(page)

        return _l3_dimensions_to_wiki_page_quality(page.path, l3_result.dimensions, [])

    def aggregate_scores(
        self,
        page_scores: list[WikiPageQualityScore],
        tier_map: dict[str, ImportanceTier],
    ) -> dict[str, Any]:
        """Aggregate page scores into module/repo score with tier weighting."""
        tier_weights = {
            ImportanceTier.CORE: 3.0,
            ImportanceTier.STANDARD: 2.0,
            ImportanceTier.SKELETON: 1.0,
        }
        total_weight = 0.0
        weighted_sum = 0.0
        for score in page_scores:
            tier = tier_map.get(score.page_path)
            w = tier_weights.get(tier, 1.0) if tier else 1.0
            weighted_sum += score.overall * w
            total_weight += w
        return {
            "overall": round(weighted_sum / total_weight, 3) if total_weight > 0 else 0,
            "page_count": len(page_scores),
        }

    def select_sample_pages(
        self,
        pages: list[WikiPage],
        tier_map: dict[str, ImportanceTier],
        sample_size: int = 20,
    ) -> list[WikiPage]:
        """Select representative pages for sampled quality evaluation."""
        import random

        core_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.CORE]
        standard_pages = [p for p in pages if tier_map.get(p.path) == ImportanceTier.STANDARD]
        sample = list(core_pages)
        remaining = max(0, sample_size - len(sample))
        if remaining > 0 and standard_pages:
            sample.extend(random.sample(standard_pages, min(remaining, len(standard_pages))))
        return sample

    def identify_pages_for_heal(
        self,
        scores: list[WikiPageQualityScore],
        min_score: float = 0.6,
    ) -> list[str]:
        return [s.page_path for s in scores if s.overall < min_score]

    def build_heal_prompt_hint(self, score: WikiPageQualityScore) -> str:
        if not score.issues:
            return ""
        issue_descriptions = {
            "missing_overview": "Add a clear ## Overview section explaining the component's purpose.",
            "missing_components": "Add a ## Key components or ## Methods section listing important members.",
            "missing_relationships": "Add a ## Relationships section showing dependencies and callers.",
            "content_too_short": "Expand the documentation with more detail about behavior and usage.",
            "no_diagrams": "Consider what visual diagram would help explain the architecture.",
        }
        hints = [issue_descriptions.get(i, f"Address: {i}") for i in score.issues]
        return (
            "\n\n## Quality Improvement Instructions\n"
            "The previous version of this documentation was flagged for quality issues. "
            "Please specifically address:\n"
            + "\n".join(f"- {h}" for h in hints)
        )

    def build_heal_prompt_hint_v2(self, bench: BenchScore) -> str:
        """Actionable hints from multi-dimensional WikiQualityBench scores."""
        lines: list[str] = []
        threshold = 0.55

        struct = bench.structure
        if hasattr(struct, "issues") and struct.issues:
            lines.append(
                "Structure: fix checklist gaps — "
                + ", ".join(str(i) for i in struct.issues)
                + "."
            )
        elif getattr(struct, "overall", 1.0) < threshold:
            lines.append(
                "Structure: add Overview, components/methods, relationships, "
                "substantial prose, or embedded diagrams per template."
            )

        if bench.depth.overall < threshold:
            lines.append(
                "Depth: expand sections under ## headings with more explanation; "
                "include API/type names and fenced code examples where helpful."
            )

        if bench.diagrams.overall < threshold:
            lines.append(
                "Diagrams: add ```mermaid blocks (sequenceDiagram, flowchart, "
                "graph, classDiagram, or stateDiagram) for key flows."
            )

        if bench.links.overall < threshold:
            lines.append(
                "Links: add [[wikilinks]] to related pages, source:// references "
                "to code, and optional https links for external context."
            )

        if not lines:
            lines.append(
                "All WikiQualityBench dimensions look acceptable; polish wording "
                "and verify accuracy against source."
            )

        return (
            "\n\n## WikiQualityBench improvement hints\n"
            + "\n".join(f"- {h}" for h in lines)
        )
