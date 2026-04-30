"""Phase 3: Topic page content generator for leaf domains.

Routes by complexity: single page (≤5 entities), split (6-15), group+split (>15).
Generates Markdown with Mermaid business flow diagrams and inline DATA_MODEL tables.
"""
from __future__ import annotations

from typing import Any, Protocol

from log import get_logger
from wiki.json_robust import parse_json_robust_sync

log = get_logger(__name__)

_SYSTEM_WIKI = (
    "You are a technical wiki author writing business domain documentation. "
    "Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
    "Do NOT explain frameworks or annotations — focus on business logic."
)


class LLMPort(Protocol):
    async def generate(
        self,
        prompt: str,
        system: str = "",
        *,
        model: str | None = None,
        max_tokens: int | None = None,
    ) -> str: ...


class TopicPageComposer:
    SIMPLE_THRESHOLD = 5
    COMPLEX_THRESHOLD = 15

    def __init__(self, llm: LLMPort, *, token_budget: int = 8000) -> None:
        self._llm = llm
        self._token_budget = token_budget

    def _token_budget_instruction(self) -> str:
        return f"\n\nIMPORTANT: Keep response under {self._token_budget} tokens.\n"

    async def compose_leaf_domain(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate wiki pages for a single leaf domain.

        Returns list of page dicts: title, content, path, page_type, domain.
        """
        biz_entities = domain.get("biz_entities", [])
        biz_count = len(biz_entities)

        if biz_count <= self.SIMPLE_THRESHOLD:
            return await self._compose_single_page(domain)
        elif biz_count <= self.COMPLEX_THRESHOLD:
            return await self._compose_split_pages(domain)
        else:
            return await self._compose_grouped_pages(domain)

    async def _compose_single_page(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        prompt = self._build_single_page_prompt(domain)
        content = await self._llm.generate(
            prompt, system=_SYSTEM_WIKI, max_tokens=self._token_budget,
        )

        data_table = self.format_data_model_table(domain.get("data_models", []))
        if data_table and "## 数据模型" not in content:
            content += f"\n\n## 数据模型\n{data_table}"

        return [{"title": name, "content": content, "path": f"wiki/{name}", "page_type": "topic", "domain": name}]

    async def _compose_split_pages(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])
        pages: list[dict[str, Any]] = []

        overview_prompt = self._build_overview_prompt(domain)
        overview_content = await self._llm.generate(
            overview_prompt, system=_SYSTEM_WIKI, max_tokens=self._token_budget,
        )
        pages.append({"title": name, "content": overview_content, "path": f"wiki/{name}", "page_type": "domain_overview", "domain": name})

        chunk_size = max(self.SIMPLE_THRESHOLD, 1)
        for i in range(0, len(biz_entities), chunk_size):
            chunk = biz_entities[i:i + chunk_size]
            if not chunk:
                sub_name = f"{name}-part-{i}"
            elif len(chunk) == 1:
                sub_name = chunk[0]["name"]
            else:
                sub_name = f"{name}-{chunk[0]['name']}-group"
            sibling_titles = [e["name"] for e in biz_entities if e not in chunk]

            sub_domain = {
                "name": sub_name,
                "parent": name,
                "biz_entities": chunk,
                "data_models": domain.get("data_models", []),
                "sibling_summaries": [{"name": t, "description": ""} for t in sibling_titles[:5]],
                "overview_summary": overview_content[:500],
            }
            sub_prompt = self._build_sub_page_prompt(sub_domain)
            sub_content = await self._llm.generate(
                sub_prompt, system=_SYSTEM_WIKI, max_tokens=self._token_budget,
            )
            pages.append({"title": sub_name, "content": sub_content, "path": f"wiki/{name}/{sub_name}", "page_type": "topic", "domain": name})

        return pages

    async def _compose_grouped_pages(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])

        group_prompt = self._build_grouping_prompt(biz_entities)
        raw_groups = await self._llm.generate(
            group_prompt,
            system="Reply with JSON only. No markdown fences.",
            max_tokens=self._token_budget,
        )

        groups = parse_json_robust_sync(raw_groups)
        if not isinstance(groups, list):
            groups = [{"name": name, "entities": [e["name"] for e in biz_entities]}]

        pages: list[dict[str, Any]] = []

        overview_prompt = self._build_overview_prompt(domain)
        overview_content = await self._llm.generate(
            overview_prompt, system=_SYSTEM_WIKI, max_tokens=self._token_budget,
        )
        pages.append({"title": name, "content": overview_content, "path": f"wiki/{name}", "page_type": "domain_overview", "domain": name})

        entity_by_name = {e["name"]: e for e in biz_entities}
        for group in groups:
            group_name = group.get("name", "unknown")
            entity_names = group.get("entities", [])
            chunk = [entity_by_name[n] for n in entity_names if n in entity_by_name]
            if not chunk:
                continue
            sub_domain = {
                "name": group_name,
                "parent": name,
                "biz_entities": chunk,
                "data_models": domain.get("data_models", []),
                "sibling_summaries": [{"name": g.get("name", ""), "description": ""} for g in groups if g.get("name") != group_name][:5],
                "overview_summary": overview_content[:500],
            }
            sub_prompt = self._build_sub_page_prompt(sub_domain)
            sub_content = await self._llm.generate(
                sub_prompt, system=_SYSTEM_WIKI, max_tokens=self._token_budget,
            )
            pages.append({"title": group_name, "content": sub_content, "path": f"wiki/{name}/{group_name}", "page_type": "topic", "domain": name})

        return pages

    def _build_single_page_prompt(self, domain: dict[str, Any]) -> str:
        name = domain["name"]
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])}; calls: {', '.join(e.get('calls', [])[:5])})"
            for e in domain.get("biz_entities", [])
        )
        siblings = ", ".join(s["name"] for s in domain.get("sibling_summaries", [])[:5])
        data_models = self.format_data_model_table(domain.get("data_models", []))
        return (
            f"Generate a wiki page for the business domain: **{name}**\n"
            f"Parent domain: {domain.get('parent', 'root')}\n"
            f"Sibling domains: {siblings or 'none'}\n\n"
            f"Core services:\n{entities_desc}\n\n"
            f"Related data models:\n{data_models or 'none'}\n\n"
            "Required sections:\n"
            "1. ## 业务概述 (what this domain does)\n"
            "2. ## 核心业务流程 (Mermaid sequenceDiagram/flowchart based on CALLS edges)\n"
            "3. ## 核心服务详情 (### per service: responsibilities, key APIs, params)\n"
            "4. ## 数据模型 (inline table of related DTOs/enums)\n"
            "5. ## 关联主题 ([[wiki-link]] to sibling domains referenced via CALLS)\n"
        ) + self._token_budget_instruction()

    def _build_overview_prompt(self, domain: dict[str, Any]) -> str:
        name = domain["name"]
        entities = domain.get("biz_entities", [])
        entity_list = "\n".join(f"- {e['name']}: {e.get('summary', '')}" for e in entities)
        return (
            f"Generate a domain overview for: **{name}**\n"
            f"This domain contains {len(entities)} core services:\n{entity_list}\n\n"
            "Output:\n"
            "1. ## 域概览 (overall business capability description)\n"
            "2. ## 架构关系图 (Mermaid diagram showing service relationships)\n"
            "3. ## 子主题 (list sub-topic pages that will be generated)\n"
        ) + self._token_budget_instruction()

    def _build_sub_page_prompt(self, sub_domain: dict[str, Any]) -> str:
        name = sub_domain["name"]
        parent = sub_domain.get("parent", "")
        overview = sub_domain.get("overview_summary", "")
        siblings = ", ".join(s["name"] for s in sub_domain.get("sibling_summaries", []))
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])})"
            for e in sub_domain.get("biz_entities", [])
        )
        return (
            f"Generate a wiki sub-page for: **{name}** (part of domain: {parent})\n"
            f"Domain overview: {overview[:300]}\n"
            f"Sibling pages: {siblings or 'none'}\n\n"
            f"Services in this sub-page:\n{entities_desc}\n\n"
            "Format: same as main topic page (业务概述, 核心业务流程 with Mermaid, 核心服务详情, 关联主题)"
        ) + self._token_budget_instruction()

    def _build_grouping_prompt(self, entities: list[dict[str, Any]]) -> str:
        entity_list = "\n".join(
            f"- {e['name']}: {e.get('summary', '')} (calls: {', '.join(e.get('calls', [])[:5])})"
            for e in entities
        )
        return (
            f"Group these {len(entities)} services into 3-7 logical sub-groups based on business functionality:\n"
            f"{entity_list}\n\n"
            'Return JSON: [{"name": "group-name", "entities": ["ServiceA", "ServiceB"]}, ...]'
        ) + self._token_budget_instruction()

    @staticmethod
    def format_data_model_table(data_models: list[dict[str, Any]]) -> str:
        if not data_models:
            return ""
        rows = ["| 类名 | 类型 | 字段 | 说明 |", "|------|------|------|------|"]
        for dm in data_models:
            name = dm.get("name", "")
            dtype = dm.get("type", "DTO")
            fields = ", ".join(str(f) for f in dm.get("fields", [])[:8])
            desc = dm.get("description", "")
            rows.append(f"| {name} | {dtype} | {fields} | {desc} |")
        return "\n".join(rows)
