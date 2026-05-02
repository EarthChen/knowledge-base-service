"""System-level architecture overview composer for cross-repo business wiki."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from core.log import get_logger
from wiki.models import (
    DiagramType,
    EnrichmentLevel,
    PageType,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort
    from wiki.dependency_graph import DomainNode

log = get_logger(__name__)

_SYSTEM_PROMPT = (
    "You are a senior architect writing a system architecture overview for a microservice platform. "
    "This system spans multiple repositories. Generate a comprehensive Markdown document with:\n"
    "1. **System Purpose** — What this platform does in business terms\n"
    "2. **Microservice Architecture** — MUST include a Mermaid graph showing how repos/services interact\n"
    "3. **Repositories** — For EACH repository: its role, key modules, tech stack, entry points\n"
    "4. **Business Domains** — Each domain with its purpose, which repos contribute to it\n"
    "5. **Cross-Service Communication** — How services communicate (RPC, messaging, shared DB, etc.)\n"
    "6. **Key Entry Points** — All API endpoints, RPC providers, message listeners across all repos\n"
    "7. **Technology Stack Summary** — Languages, frameworks, databases, messaging systems\n"
    "Every repository name from the prompt must appear in the document."
)

_SYSTEM_PROMPT_ZH = (
    "你是一位资深架构师，正在为微服务平台编写系统架构概述。"
    "该系统跨越多个仓库。生成一份完整的 Markdown 文档，包含：\n"
    "1. **系统定位** — 该平台的业务用途\n"
    "2. **微服务架构** — 必须包含展示各服务交互的 Mermaid 图\n"
    "3. **仓库清单** — 每个仓库的职责、关键模块、技术栈、入口点\n"
    "4. **业务域** — 每个域的用途及参与的仓库\n"
    "5. **跨服务通信** — 服务间如何通信（RPC、消息、共享数据库等）\n"
    "6. **关键入口点** — 所有 API 端点、RPC 提供者、消息监听器\n"
    "7. **技术栈总结** — 语言、框架、数据库、消息系统\n"
    "提示中给出的每个仓库名称必须出现在文档中。"
)


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
                    title="System architecture",
                ),
            )
    body = pattern.sub("", raw).strip()
    return body, diagrams


class SystemOverviewComposer:
    """Generate a single cross-repo system architecture overview page."""

    def __init__(self, llm: LLMPort | None) -> None:
        self._llm = llm

    async def compose(
        self,
        business_id: str,
        repositories: list[str],
        domain_tree: list[DomainNode] | list,
        entry_points_by_repo: dict[str, list[str]],
        domain_overviews: dict[str, str],
        stats_by_repo: dict[str, dict[str, int]],
        language: str = "en",
    ) -> WikiPage:
        prompt = self._build_prompt(
            repositories,
            domain_tree,
            entry_points_by_repo,
            domain_overviews,
            stats_by_repo,
            language,
        )
        system = _SYSTEM_PROMPT_ZH if language == "zh" else _SYSTEM_PROMPT

        content: str = ""
        diagrams: list[WikiDiagram] = []
        llm_succeeded = False

        if self._llm is not None:
            try:
                raw = (await self._llm.generate(prompt, system=system)).strip()
                content, diagrams = _extract_mermaid(raw)
                if content.strip():
                    llm_succeeded = True
            except Exception:
                log.warning("system_overview_llm_failed", exc_info=True)
                content = ""

        if not content.strip():
            content = self._fallback_content(
                repositories,
                stats_by_repo,
                entry_points_by_repo,
                domain_overviews,
                language,
            )

        path = f"system_overview_{business_id}"
        lang_label = language if language in ("en", "zh") else "en"
        title = "System Architecture Overview" if lang_label == "en" else "系统架构概述"

        meta = WikiPageMetadata(
            node_count=sum(
                s.get("module_count", 0) + s.get("class_count", 0) + s.get("function_count", 0)
                for s in stats_by_repo.values()
            ),
            edge_count=0,
            generation_mode="business",
            enrichment_level=EnrichmentLevel.ENRICHED if llm_succeeded else EnrichmentLevel.BASE,
        )
        return WikiPage(
            path=path,
            title=title,
            page_type=PageType.REPO_OVERVIEW,
            content=content,
            diagrams=diagrams,
            source_locations=[],
            metadata=meta,
        )

    def _build_prompt(
        self,
        repositories: list[str],
        domain_tree: list,
        entry_points_by_repo: dict[str, list[str]],
        domain_overviews: dict[str, str],
        stats_by_repo: dict[str, dict[str, int]],
        language: str,
    ) -> str:
        sections: list[str] = []

        sections.append(f"## Repositories ({len(repositories)} total)")
        for repo in repositories:
            stats = stats_by_repo.get(repo, {})
            eps = entry_points_by_repo.get(repo, [])
            sections.append(
                f"### {repo}\n"
                f"- Modules: {stats.get('module_count', '?')}, "
                f"Classes: {stats.get('class_count', '?')}, "
                f"Functions: {stats.get('function_count', '?')}\n"
                f"- Entry Points: {', '.join(eps[:20]) if eps else 'None identified'}"
            )

        if domain_overviews:
            sections.append(f"\n## Business Domains ({len(domain_overviews)} domains)")
            for name, summary in domain_overviews.items():
                sections.append(f"### {name}\n{summary[:500]}")

        if domain_tree:
            sections.append("\n## Domain Tree Structure")
            for node in domain_tree:
                name = node.name if hasattr(node, "name") else str(node)
                desc = getattr(node, "description", "")
                modules = getattr(node, "modules", [])
                sections.append(f"- **{name}**: {desc} (modules: {', '.join(str(m) for m in modules[:10])})")

        return "\n\n".join(sections)

    def _fallback_content(
        self,
        repositories: list[str],
        stats_by_repo: dict[str, dict[str, int]],
        entry_points_by_repo: dict[str, list[str]],
        domain_overviews: dict[str, str],
        language: str,
    ) -> str:
        lang = language if language in ("en", "zh") else "en"
        if lang == "zh":
            lines = ["# 系统架构概述\n"]
            lines.append(f"本系统跨 **{len(repositories)} 个仓库**。\n")
        else:
            lines = ["# System Architecture Overview\n"]
            lines.append(f"This system spans **{len(repositories)} repositories**.\n")

        for repo in repositories:
            stats = stats_by_repo.get(repo, {})
            eps = entry_points_by_repo.get(repo, [])
            lines.append(f"## {repo}\n")
            lines.append(f"- Modules: {stats.get('module_count', 0)}")
            lines.append(f"- Classes: {stats.get('class_count', 0)}")
            lines.append(f"- Functions: {stats.get('function_count', 0)}")
            if eps:
                lines.append(f"- Entry Points: {', '.join(eps[:10])}")
            lines.append("")

        if domain_overviews:
            if lang == "zh":
                lines.append("## 业务域\n")
            else:
                lines.append("## Business Domains\n")
            for name, summary in domain_overviews.items():
                lines.append(f"### {name}\n{summary[:300]}\n")

        return "\n".join(lines)
