"""Phase 3: Topic page content generator for leaf domains.

Routes by DomainComplexityScorer (entities, methods, calls, LOC, coupling hints):
LOW → single concise page; MEDIUM → overview + split sub-pages; HIGH → LLM grouping + overview + sub-pages with higher token budget.
Generates Markdown with Mermaid business flow diagrams and inline DATA_MODEL tables.
"""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.llm_port import LLMPort
from wiki.domain_complexity import DomainComplexity, DomainComplexityScorer
from wiki.json_robust import parse_json_robust_sync
from wiki.prompts import (
    SYSTEM_JSON_ONLY,
    SYSTEM_WIKI_AUTHOR,
    SYSTEM_WIKI_PARENT_OVERVIEW,
)
from wiki.reasoning import MultiStepReasoner, ReasoningLevel

log = get_logger(__name__)

_EXECUTIVE_SUMMARY_JSON_INSTRUCTION = (
    'Also include an "executive_summary" field (string, 150-300 chars) that '
    "captures the domain's core purpose in 1-2 sentences."
)

_WIKI_PAGE_JSON_SCHEMA_INSTRUCTION = (
    "\n\nReturn ONLY valid JSON (no markdown fences) with this shape:\n"
    '  {"executive_summary": "<string>", "content": "<Markdown body with Mermaid; '
    'Chinese for business descriptions>"}\n'
    + _EXECUTIVE_SUMMARY_JSON_INSTRUCTION
    + "\n"
)

_OVERVIEW_JSON_SCHEMA_INSTRUCTION = (
    "\n\nReturn ONLY valid JSON (no markdown fences) with this shape:\n"
    '  {"executive_summary": "<string>", "content": "<Markdown with sections ## 域概览, '
    '## 架构关系图, ## 子主题>"}\n'
    + _EXECUTIVE_SUMMARY_JSON_INSTRUCTION
    + "\n"
)


class TopicPageComposer:
    SIMPLE_THRESHOLD = 5

    def __init__(
        self,
        llm: LLMPort,
        *,
        token_budget: int = 8000,
        complexity_scorer: DomainComplexityScorer | None = None,
        reasoning_level: ReasoningLevel | None = None,
    ) -> None:
        self._llm = llm
        self._token_budget = token_budget
        self._complexity_scorer = complexity_scorer or DomainComplexityScorer()
        self._reasoning_level = reasoning_level

    @staticmethod
    def _snippet_block(domain: dict[str, Any]) -> str:
        block = domain.get("snippet_section") or ""
        return block if isinstance(block, str) else ""

    @staticmethod
    def _parse_wiki_json_response(raw: str) -> tuple[str, str]:
        """Extract markdown content and executive_summary from LLM JSON; fallback to raw markdown."""
        stripped = (raw or "").strip()
        if not stripped:
            return "", ""
        parsed = parse_json_robust_sync(stripped)
        if isinstance(parsed, dict):
            exec_raw = parsed.get("executive_summary")
            summary = exec_raw.strip() if isinstance(exec_raw, str) else ""
            body = parsed.get("content")
            if isinstance(body, str) and body.strip():
                return body.strip(), summary
        return stripped, ""

    def _page_metadata(self, executive_summary: str) -> dict[str, str]:
        return {"executive_summary": executive_summary or ""}

    def _token_budget_instruction(self, max_tokens: int | None = None) -> str:
        cap = max_tokens if max_tokens is not None else self._token_budget
        return f"\n\nIMPORTANT: Keep response under {cap} tokens.\n"

    def _effective_token_budget(self, complexity: DomainComplexity) -> int:
        if complexity == DomainComplexity.HIGH:
            return int(self._token_budget * 1.5)
        return self._token_budget

    async def compose_leaf_domain(self, domain: dict[str, Any]) -> list[dict[str, Any]]:
        """Generate wiki pages for a single leaf domain.

        Returns list of page dicts: title, content, path, page_type, domain.
        """
        metrics = self._complexity_scorer.score(domain)
        complexity = metrics.complexity

        if complexity == DomainComplexity.LOW:
            return await self._compose_single_page(domain, complexity)
        if complexity == DomainComplexity.MEDIUM:
            return await self._compose_split_pages(domain, complexity)
        return await self._compose_grouped_pages(domain, complexity)

    async def _compose_single_page(self, domain: dict[str, Any], complexity: DomainComplexity) -> list[dict[str, Any]]:
        name = domain["name"]
        concise = complexity == DomainComplexity.LOW
        budget = self._effective_token_budget(complexity)
        executive_summary = ""
        raw_response = ""

        if self._reasoning_level == ReasoningLevel.MULTI_STEP and not concise:
            reasoner = MultiStepReasoner()
            raw_response = await reasoner.plan_and_compose(
                domain, self._llm, system=SYSTEM_WIKI_AUTHOR, max_tokens=budget,
            )
        else:
            prompt = self._build_single_page_prompt(domain, concise=concise)
            raw_response = await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY, max_tokens=budget)

        content, executive_summary = self._parse_wiki_json_response(raw_response)
        if not content:
            content = raw_response.strip()

        data_table = self.format_data_model_table(domain.get("data_models", []))
        if data_table and "## 数据模型" not in content:
            content += f"\n\n## 数据模型\n{data_table}"

        return [{
            "title": name,
            "content": content,
            "path": f"wiki/{name}",
            "page_type": "topic",
            "domain": name,
            "metadata": self._page_metadata(executive_summary),
        }]

    async def _compose_split_pages(self, domain: dict[str, Any], complexity: DomainComplexity) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])
        pages: list[dict[str, Any]] = []
        budget = self._effective_token_budget(complexity)

        overview_prompt = self._build_overview_prompt(domain, max_tokens=budget)
        overview_raw = await self._llm.generate(
            overview_prompt, system=SYSTEM_WIKI_PARENT_OVERVIEW, max_tokens=budget,
        )
        overview_content, overview_exec = self._parse_wiki_json_response(overview_raw)
        if not overview_content:
            overview_content = overview_raw.strip()
        pages.append({
            "title": name,
            "content": overview_content,
            "path": f"wiki/{name}",
            "page_type": "domain_overview",
            "domain": name,
            "metadata": self._page_metadata(overview_exec),
        })

        snippet_parent = self._snippet_block(domain)
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
                "snippet_section": snippet_parent,
            }
            sub_exec = ""
            if self._reasoning_level == ReasoningLevel.MULTI_STEP:
                reasoner = MultiStepReasoner()
                sub_raw = await reasoner.plan_and_compose(
                    sub_domain,
                    self._llm,
                    system=SYSTEM_WIKI_AUTHOR,
                    max_tokens=budget,
                )
                sub_content, sub_exec = self._parse_wiki_json_response(sub_raw)
                if not sub_content:
                    sub_content = sub_raw.strip()
            else:
                sub_prompt = self._build_sub_page_prompt(sub_domain, max_tokens=budget)
                sub_raw = await self._llm.generate(
                    sub_prompt, system=SYSTEM_JSON_ONLY, max_tokens=budget,
                )
                sub_content, sub_exec = self._parse_wiki_json_response(sub_raw)
                if not sub_content:
                    sub_content = sub_raw.strip()
            pages.append({
                "title": sub_name,
                "content": sub_content,
                "path": f"wiki/{name}/{sub_name}",
                "page_type": "topic",
                "domain": name,
                "metadata": self._page_metadata(sub_exec),
            })

        return pages

    async def _compose_grouped_pages(self, domain: dict[str, Any], complexity: DomainComplexity) -> list[dict[str, Any]]:
        name = domain["name"]
        biz_entities = domain.get("biz_entities", [])
        budget = self._effective_token_budget(complexity)

        group_prompt = self._build_grouping_prompt(biz_entities, max_tokens=budget)
        raw_groups = await self._llm.generate(
            group_prompt,
            system=SYSTEM_JSON_ONLY,
            max_tokens=budget,
        )

        groups = parse_json_robust_sync(raw_groups)
        if not isinstance(groups, list):
            groups = [{"name": name, "entities": [e["name"] for e in biz_entities]}]

        pages: list[dict[str, Any]] = []

        overview_prompt = self._build_overview_prompt(domain, max_tokens=budget)
        overview_raw = await self._llm.generate(
            overview_prompt, system=SYSTEM_WIKI_PARENT_OVERVIEW, max_tokens=budget,
        )
        overview_content, overview_exec = self._parse_wiki_json_response(overview_raw)
        if not overview_content:
            overview_content = overview_raw.strip()
        pages.append({
            "title": name,
            "content": overview_content,
            "path": f"wiki/{name}",
            "page_type": "domain_overview",
            "domain": name,
            "metadata": self._page_metadata(overview_exec),
        })

        snippet_parent = self._snippet_block(domain)
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
                "snippet_section": snippet_parent,
            }
            sub_exec = ""
            if self._reasoning_level == ReasoningLevel.MULTI_STEP:
                reasoner = MultiStepReasoner()
                sub_raw = await reasoner.plan_and_compose(
                    sub_domain,
                    self._llm,
                    system=SYSTEM_WIKI_AUTHOR,
                    max_tokens=budget,
                )
                sub_content, sub_exec = self._parse_wiki_json_response(sub_raw)
                if not sub_content:
                    sub_content = sub_raw.strip()
            else:
                sub_prompt = self._build_sub_page_prompt(sub_domain, max_tokens=budget)
                sub_raw = await self._llm.generate(
                    sub_prompt, system=SYSTEM_JSON_ONLY, max_tokens=budget,
                )
                sub_content, sub_exec = self._parse_wiki_json_response(sub_raw)
                if not sub_content:
                    sub_content = sub_raw.strip()
            pages.append({
                "title": group_name,
                "content": sub_content,
                "path": f"wiki/{name}/{group_name}",
                "page_type": "topic",
                "domain": name,
                "metadata": self._page_metadata(sub_exec),
            })

        return pages

    def _build_single_page_prompt(self, domain: dict[str, Any], *, concise: bool = False) -> str:
        name = domain["name"]
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])}; calls: {', '.join(e.get('calls', [])[:5])})"
            for e in domain.get("biz_entities", [])
        )
        siblings = ", ".join(s["name"] for s in domain.get("sibling_summaries", [])[:5])
        data_models = self.format_data_model_table(domain.get("data_models", []))
        snip = self._snippet_block(domain)
        tail = (f"\n{snip}\n" if snip else "") + _WIKI_PAGE_JSON_SCHEMA_INSTRUCTION
        if concise:
            return (
                f"Generate a wiki page for the business domain: **{name}**\n"
                f"Parent domain: {domain.get('parent', 'root')}\n"
                f"Sibling domains: {siblings or 'none'}\n\n"
                f"Core services:\n{entities_desc}\n\n"
                f"Related data models:\n{data_models or 'none'}\n\n"
                "精简与简要输出：避免冗长解释，用短段落与条目即可。\n"
                "Required sections (minimal):\n"
                "1. ## 业务概述\n"
                "2. ## 核心业务流程 (one concise Mermaid diagram)\n"
                "3. ## 核心服务要点 (bullet list per service; skip deep API tables)\n"
            ) + tail + self._token_budget_instruction()
        return (
            f"Write a wiki page for domain: **{name}**\n"
            f"Parent domain: {domain.get('parent', 'root')}\n"
            f"Sibling domains: {siblings or 'none'}\n\n"
            f"Core services:\n{entities_desc}\n\n"
            f"Related data models:\n{data_models or 'none'}\n\n"
            "Before writing, analyze:\n"
            "1. What is each service's primary business role?\n"
            "2. How do these services interact? (callers, shared data)\n"
            "3. Which flows deserve Mermaid diagrams?\n\n"
            "Required elements (organize freely):\n"
            "- Business overview explaining WHY this domain exists\n"
            "- Core business flow with Mermaid diagram "
            "(sequenceDiagram or flowchart based on CALLS relationships)\n"
            "- Key services with their responsibilities and interactions\n"
            f"- Related topics using [[wiki-link]] notation for these related domains: {siblings or 'none'}\n"
        ) + tail + self._token_budget_instruction()

    def _build_overview_prompt(self, domain: dict[str, Any], *, max_tokens: int | None = None) -> str:
        name = domain["name"]
        entities = domain.get("biz_entities", [])
        entity_list = "\n".join(f"- {e['name']}: {e.get('summary', '')}" for e in entities)
        snip = self._snippet_block(domain)
        tail = (f"\n{snip}\n" if snip else "") + _OVERVIEW_JSON_SCHEMA_INSTRUCTION
        return (
            f"Generate a domain overview for: **{name}**\n"
            "Write like a technical blog post — motivate WHY this domain exists, "
            "HOW its services fit together, and WHAT overall business capability it provides.\n"
            f"This domain contains {len(entities)} core services:\n{entity_list}\n\n"
            "The JSON \"content\" field must include these sections:\n"
            "1. ## 域概览 (overall business capability description)\n"
            "2. ## 架构关系图 (Mermaid diagram showing service relationships)\n"
            "3. ## 子主题 (list sub-topic pages that will be generated)\n"
        ) + tail + self._token_budget_instruction(max_tokens)

    def _build_sub_page_prompt(self, sub_domain: dict[str, Any], *, max_tokens: int | None = None) -> str:
        name = sub_domain["name"]
        parent = sub_domain.get("parent", "")
        overview = sub_domain.get("overview_summary", "")
        siblings = ", ".join(s["name"] for s in sub_domain.get("sibling_summaries", []))
        entities_desc = "\n".join(
            f"- **{e['name']}**: {e.get('summary', '')} (methods: {', '.join(e.get('methods', [])[:10])})"
            for e in sub_domain.get("biz_entities", [])
        )
        snip = self._snippet_block(sub_domain)
        tail = (f"\n{snip}\n" if snip else "") + _WIKI_PAGE_JSON_SCHEMA_INSTRUCTION
        return (
            f"Generate a wiki sub-page for: **{name}** (part of domain: {parent})\n"
            "Write like a technical blog post — explain WHY this slice matters within the parent domain, "
            "HOW these services collaborate, and WHAT business outcomes they support.\n"
            f"Domain overview: {overview[:300]}\n"
            f"Sibling pages: {siblings or 'none'}\n\n"
            f"Services in this sub-page:\n{entities_desc}\n\n"
            "Before writing, analyze:\n"
            "1. What is each service's primary business role?\n"
            "2. How do these services interact? (callers, shared data)\n"
            "3. Which flows deserve Mermaid diagrams?\n\n"
            "Required elements (organize freely; use Chinese section titles like the main topic page):\n"
            "- Business overview explaining WHY this sub-topic exists and how it fits the parent domain\n"
            "- Core business flow with Mermaid diagram "
            "(sequenceDiagram or flowchart based on CALLS relationships)\n"
            "- Key services with their responsibilities and interactions\n"
            f"- Related topics using [[wiki-link]] notation for these sibling pages: {siblings or 'none'}\n"
        ) + tail + self._token_budget_instruction(max_tokens)

    def _build_grouping_prompt(self, entities: list[dict[str, Any]], *, max_tokens: int | None = None) -> str:
        entity_list = "\n".join(
            f"- {e['name']}: {e.get('summary', '')} (calls: {', '.join(e.get('calls', [])[:5])})"
            for e in entities
        )
        return (
            f"Group these {len(entities)} services into 3-7 logical sub-groups based on business functionality:\n"
            f"{entity_list}\n\n"
            'Return JSON: [{"name": "group-name", "entities": ["ServiceA", "ServiceB"]}, ...]'
        ) + self._token_budget_instruction(max_tokens)

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
