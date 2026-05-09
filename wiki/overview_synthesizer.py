"""Synthesize domain overviews from already-generated child page content."""
from __future__ import annotations

import re

_OVERVIEW_RE = re.compile(
    r"##\s*(?:概述|Overview|业务概述)\s*\n(.*?)(?=\n##|\Z)",
    re.DOTALL,
)

_BUSINESS_SUMMARY_RE = re.compile(
    r"该[类处理器服务]+属于.*?领域，(.*?)(?:\.|。)",
    re.DOTALL,
)


def _extract_overview(content: str) -> str:
    """Extract the first overview section from page content."""
    m = _OVERVIEW_RE.search(content)
    if m:
        return m.group(1).strip()
    # Try extracting business_summary style text
    m2 = _BUSINESS_SUMMARY_RE.search(content)
    if m2:
        return m2.group(0).strip()
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
        return f"# {domain_name}\n\n## 概述\n\n{domain_name} 域暂无子模块内容。\n"

    parts = [f"# {domain_name}\n", "## 概述\n"]

    child_summaries = []
    for child in children:
        title = child.get("title", "Unknown")
        content = child.get("content", "")
        overview = _extract_overview(content) if content else ""
        child_summaries.append((title, overview))

    summaries_with_content = [(t, o) for t, o in child_summaries if o]
    if summaries_with_content:
        intro = f"{domain_name} 域负责以下核心能力：\n\n"
        for title, overview in summaries_with_content[:5]:
            intro += f"- **{title}**：{overview[:150]}\n"
        parts.append(f"{intro}\n")
    else:
        parts.append(f"{domain_name} 包含以下 {len(children)} 个子模块:\n")

    parts.append("\n## 核心模块\n")
    parts.append("| 模块 | 类型 | 职责 |")
    parts.append("|------|------|------|")
    for child in children:
        title = child.get("title", "Unknown")
        content = child.get("content", "")
        overview = _extract_overview(content) if content else ""
        mod_type = _infer_module_type(title, overview)
        summary = overview[:120] if overview else ""
        parts.append(f"| `{title}` | {mod_type} | {summary} |")

    parts.append("")

    if summaries_with_content:
        parts.append("\n## 业务流程\n")
        parts.append(f"以下描述 {domain_name} 域各模块间的协作关系：\n")
        for title, overview in summaries_with_content[:6]:
            parts.append(f"### {title}\n")
            parts.append(f"{overview}\n")

    return "\n".join(parts)


def _infer_module_type(title: str, overview: str) -> str:
    """Infer module type from title and overview text."""
    combined = (title + " " + overview).lower()
    if "handler" in combined or "kafka" in combined or "回调" in combined:
        return "Kafka Handler"
    if "remote" in combined and "impl" in combined:
        return "Remote Service"
    if "service" in combined and "impl" in combined:
        return "Service Impl"
    if "service" in combined:
        return "Service"
    if "dao" in combined or "repo" in combined:
        return "Data Access"
    if "config" in combined or "provider" in combined:
        return "Config"
    if "wrapper" in combined or "moa" in combined:
        return "MOA Wrapper"
    return "Module"
