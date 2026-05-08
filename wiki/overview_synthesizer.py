"""Synthesize domain overviews from already-generated child page content."""
from __future__ import annotations

import re

_OVERVIEW_RE = re.compile(
    r"##\s*(?:概述|Overview|业务概述)\s*\n(.*?)(?=\n##|\Z)",
    re.DOTALL,
)


def _extract_overview(content: str) -> str:
    """Extract the first overview section from page content."""
    m = _OVERVIEW_RE.search(content)
    if m:
        return m.group(1).strip()
    lines = [l for l in content.split("\n") if l.strip() and not l.startswith("#")]
    return " ".join(lines[:3]).strip()[:300]


def synthesize_overview_from_children(
    domain_name: str,
    children: list[dict],
) -> str:
    """Build a domain overview page from child page summaries.

    Uses actual generated content instead of LLM fabrication.
    """
    if not children:
        return (
            f"# {domain_name}\n\n"
            f"## 概述\n\n"
            f"<!-- CONTEXT_GAP: 无子页面内容可用于合成概述 -->\n"
        )

    parts = [f"# {domain_name}\n", "## 概述\n"]
    parts.append(f"{domain_name} 包含以下子模块:\n")

    child_summaries = []
    for child in children:
        title = child.get("title", "Unknown")
        content = child.get("content", "")
        overview = _extract_overview(content) if content else ""
        child_summaries.append((title, overview))

    for title, overview in child_summaries:
        if overview:
            parts.append(f"### {title}\n")
            parts.append(f"{overview}\n")
        else:
            parts.append(f"### {title}\n")
            parts.append(f"<!-- CONTEXT_GAP: {title} 缺少概述内容 -->\n")

    parts.append("\n## 子模块列表\n")
    for title, _ in child_summaries:
        parts.append(f"- [[{title}]]")

    return "\n".join(parts)
