"""Compose business domain overview wiki pages from cross-repository module nodes."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import TYPE_CHECKING

from core.log import get_logger
from store.schema import GraphNode
from wiki.models import DiagramType, EnrichmentLevel, PageType, WikiDiagram, WikiPage, WikiPageMetadata

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort

log = get_logger(__name__)


def _effective_language(language: str) -> str:
    return language if language in ("en", "zh") else "en"


def _module_summary(node: GraphNode) -> str:
    bs = node.properties.get("business_summary")
    if isinstance(bs, str) and bs.strip():
        return bs.strip()
    ds = node.properties.get("docstring")
    if isinstance(ds, str) and ds.strip():
        return ds.strip()
    return ""


def _group_modules(
    modules: list[tuple[str, str, GraphNode]],
) -> dict[str, list[tuple[str, GraphNode]]]:
    grouped: dict[str, list[tuple[str, GraphNode]]] = defaultdict(list)
    for repository, module_name, node in modules:
        grouped[repository].append((module_name, node))
    return dict(grouped)


def _extract_mermaid(raw: str) -> tuple[str, list[WikiDiagram]]:
    pattern = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
    diagrams: list[WikiDiagram] = []
    for m in pattern.finditer(raw):
        body = m.group(1).strip()
        if body:
            diagrams.append(
                WikiDiagram(
                    diagram_type=DiagramType.FLOWCHART,
                    content=body + "\n",
                    title="Domain collaboration",
                ),
            )
    body = pattern.sub("", raw).strip()
    return body, diagrams


def _ensure_repo_names_in_content(content: str, repositories: list[str]) -> str:
    if not repositories:
        return content
    missing = [r for r in repositories if r and r not in content]
    if not missing:
        return content
    block_lines = ["", "## Repositories", ""]
    block_lines.extend(f"- `{r}`" for r in sorted(missing))
    return content + "\n".join(block_lines)


def _structural_markdown(domain_name: str, grouped: dict[str, list[tuple[str, GraphNode]]], language: str) -> str:
    lang = _effective_language(language)
    if lang == "zh":
        title = f"# 业务域：{domain_name}"
        intro_empty = "_此业务域尚无已索引模块。_"
        repo_heading = "## 仓库与模块"
    else:
        title = f"# Domain: {domain_name}"
        intro_empty = "_No modules indexed for this domain yet._"
        repo_heading = "## Repositories and modules"

    if not grouped:
        return f"{title}\n\n{intro_empty}\n"

    lines = [title, "", repo_heading, ""]
    for repo in sorted(grouped.keys()):
        if lang == "zh":
            lines.append(f"### 仓库 `{repo}`")
        else:
            lines.append(f"### Repository `{repo}`")
        lines.append("")
        for mod_name, node in sorted(grouped[repo], key=lambda x: x[0].lower()):
            summary = _module_summary(node)
            summary_part = summary if summary else ("（无摘要）" if lang == "zh" else "_(no summary)_")
            lines.append(f"- **{mod_name}**: {summary_part}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class DomainOverviewComposer:
    """Builds DOMAIN_OVERVIEW pages from per-repository module graph nodes."""

    def __init__(self, llm: LLMPort | None = None) -> None:
        self._llm = llm

    def _build_nested_navigation(self, domain_tree: list) -> str:
        """Generate nested sub-domain navigation links."""
        if not domain_tree:
            return ""
        lines = ["## Sub-Domains", ""]
        for domain in domain_tree:
            desc = f": {domain.description}" if hasattr(domain, "description") and domain.description else ""
            lines.append(f"- **{domain.name}**{desc}")
            children = getattr(domain, "children", [])
            for child in children:
                child_desc = (
                    f": {child.description}" if hasattr(child, "description") and child.description else ""
                )
                lines.append(f"  - {child.name}{child_desc}")
        return "\n".join(lines) + "\n"

    def _build_entry_points_section(self, entry_points: list[str]) -> str:
        """List module entry points."""
        if not entry_points:
            return ""
        lines = ["## Entry Points", ""]
        for ep in entry_points:
            lines.append(f"- `{ep}`")
        return "\n".join(lines) + "\n"

    async def compose(
        self,
        domain_name: str,
        modules: list[tuple[str, str, GraphNode]],
        language: str = "en",
        *,
        domain_tree: list | None = None,
        entry_points: list[str] | None = None,
    ) -> WikiPage:
        grouped = _group_modules(modules)
        repositories = sorted(grouped.keys())
        structural = _structural_markdown(domain_name, grouped, language)
        lang = _effective_language(language)

        content = structural
        diagrams: list[WikiDiagram] = []

        if self._llm is not None and modules:
            try:
                prompt = self._llm_prompt(domain_name, grouped, lang)
                system = self._llm_system(lang)
                raw = (await self._llm.generate(prompt, system=system)).strip()
                body, diagrams = _extract_mermaid(raw)
                if not body.strip():
                    content = structural
                    diagrams = []
                else:
                    content = _ensure_repo_names_in_content(body, repositories)
            except Exception as exc:
                log.warning(
                    "domain_overview_llm_failed",
                    domain=domain_name,
                    error=str(exc),
                    exc_info=True,
                )
                content = structural
                diagrams = []

        extra_sections: list[str] = []
        if domain_tree:
            nav = self._build_nested_navigation(domain_tree)
            if nav:
                extra_sections.append(nav)
        if entry_points:
            ep_section = self._build_entry_points_section(entry_points)
            if ep_section:
                extra_sections.append(ep_section)
        if extra_sections:
            content = content.rstrip() + "\n\n" + "\n".join(extra_sections)

        path = f"/{domain_name}/_overview"
        title = f"{domain_name} — overview" if lang == "en" else f"{domain_name} — 概述"

        meta = WikiPageMetadata(
            node_count=len(modules),
            edge_count=0,
            generation_mode="business",
            enrichment_level=EnrichmentLevel.BASE,
        )
        return WikiPage(
            path=path,
            title=title,
            page_type=PageType.DOMAIN_OVERVIEW,
            content=content,
            diagrams=diagrams,
            source_locations=[],
            metadata=meta,
        )

    def _llm_system(self, language: str) -> str:
        if language == "zh":
            return (
                "你是资深系统架构作者。用 Markdown 撰写业务域概述。"
                "必须包含：业务目的、关键模块与职责、跨模块协作。"
                "在文末使用 ```mermaid 代码块给出模块协作图（flowchart 或 graph）。"
                "Repositories 列表必须覆盖提示中给出的每个仓库名。"
            )
        return (
            "You are a senior system architect writing wiki content. "
            "Respond in Markdown with: business purpose, key modules and roles, "
            "and inter-module collaboration. "
            "End with a ```mermaid fenced block showing how modules collaborate "
            "(flowchart or graph). "
            "Every repository name from the prompt must appear in the document."
        )

    def _llm_prompt(self, domain_name: str, grouped: dict[str, list[tuple[str, GraphNode]]], language: str) -> str:
        blocks: list[str] = []
        if language == "zh":
            blocks.append(f"业务域名称：{domain_name}")
            blocks.append("\n跨仓库模块：")
        else:
            blocks.append(f"Domain name: {domain_name}")
            blocks.append("\nCross-repository modules:")
        for repo in sorted(grouped.keys()):
            blocks.append(f"\nRepository `{repo}`:")
            for mod_name, node in sorted(grouped[repo], key=lambda x: x[0].lower()):
                summary = _module_summary(node)
                blocks.append(f"  - Module `{mod_name}`: {summary or '(no summary)'}")
        if language == "zh":
            blocks.append("\n请生成该业务域概述页正文（Markdown）。")
        else:
            blocks.append("\nGenerate the domain overview page body (Markdown).")
        return "\n".join(blocks)
