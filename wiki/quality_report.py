"""Programmatic wiki quality evaluation.

All metrics use regex/string matching — zero LLM dependency.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_SOURCE_LINK_RE = re.compile(r"source://\S+")
_CODE_BLOCK_RE = re.compile(r"```(?!mermaid)\w*\n[\s\S]*?```")
_CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP\s*:")
_MERMAID_BLOCK_RE = re.compile(r"```mermaid\n[\s\S]*?```")
_WIKILINK_RE = re.compile(r"\[\[.+?\]\]")
_INLINE_CODE_RE = re.compile(r"`[A-Z][a-zA-Z0-9]+(?:\.[a-zA-Z]\w*\(\))?`")
_H3_HEADING_RE = re.compile(r"^### (.+)", re.MULTILINE)
_CODE_REF_RE = re.compile(r"<!-- CODE_REF:\s*(\S+)")


@dataclass(frozen=True)
class QualityReport:
    coverage: float
    citation_density: float
    context_gap_count: int
    uncovered_modules: list[str] = field(default_factory=list)
    visual_aids_count: int = 0
    cross_ref_density: float = 0.0
    implementation_depth: float = 0.0

    @property
    def is_acceptable(self) -> bool:
        return self.coverage >= 0.8 and self.citation_density >= 0.5


def _strip_compound_prefix(name: str) -> str:
    """Strip 'repo|' prefix from compound module keys like 'ultron|ClassName'."""
    if "|" in name:
        return name.split("|", 1)[1]
    return name


def _module_short_name(name: str) -> str:
    """Return searchable short name: strip repo prefix, then last dotted segment."""
    base = _strip_compound_prefix(name)
    return base.rsplit(".", 1)[-1] if "." in base else base


def _count_module_inline_refs(content: str, module_names: list[str]) -> int:
    """Count modules referenced via inline code (e.g. `ClassName` or `ClassName.method()`)."""
    inline_codes = set(_INLINE_CODE_RE.findall(content))
    ref_count = 0
    for m in module_names:
        short = _module_short_name(m)
        if any(short in c for c in inline_codes):
            ref_count += 1
    return ref_count


def _module_word_pattern(name: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![\w]){re.escape(name)}(?![\w])", re.IGNORECASE)


def _is_module_covered(content: str, module_name: str) -> bool:
    """True when *module_name* (or its short segment) appears as a standalone token."""
    name = _strip_compound_prefix(module_name.strip())
    if not name:
        return False
    variants = [name]
    short = name.rsplit(".", 1)[-1]
    if short and short != name:
        variants.append(short)
    for variant in variants:
        if _module_word_pattern(variant).search(content):
            return True
    return False


def _calc_implementation_depth(content: str, module_names: list[str]) -> float:
    if not module_names:
        return 1.0
    h3_headings = set(_H3_HEADING_RE.findall(content))
    code_refs = set(_CODE_REF_RE.findall(content))
    all_markers = h3_headings | code_refs
    detailed = 0
    for m in module_names:
        short = _module_short_name(m)
        if any(short.lower() in marker.lower() for marker in all_markers):
            detailed += 1
    return detailed / len(module_names)


def evaluate_quality(content: str, module_names: list[str]) -> QualityReport:
    if not module_names:
        return QualityReport(
            coverage=1.0, citation_density=0.0, context_gap_count=0,
            implementation_depth=1.0,
        )

    covered = [m for m in module_names if _is_module_covered(content, m)]
    uncovered = [m for m in module_names if m not in covered]
    coverage = len(covered) / len(module_names) if module_names else 0.0

    source_count = len(_SOURCE_LINK_RE.findall(content))
    code_count = len(_CODE_BLOCK_RE.findall(content))
    inline_ref_count = _count_module_inline_refs(content, module_names)
    citation_total = source_count + code_count + inline_ref_count
    citation_density = citation_total / len(module_names) if module_names else 0.0

    gap_count = len(_CONTEXT_GAP_RE.findall(content))
    mermaid_count = len(_MERMAID_BLOCK_RE.findall(content))
    wikilink_count = len(_WIKILINK_RE.findall(content))
    cross_ref = wikilink_count / len(module_names) if module_names else 0.0

    impl_depth = _calc_implementation_depth(content, module_names)

    return QualityReport(
        coverage=round(coverage, 4),
        citation_density=round(citation_density, 4),
        context_gap_count=gap_count,
        uncovered_modules=uncovered,
        visual_aids_count=mermaid_count,
        cross_ref_density=round(cross_ref, 4),
        implementation_depth=round(impl_depth, 4),
    )
