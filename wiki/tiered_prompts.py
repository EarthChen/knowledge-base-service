"""Tiered LLM prompt templates for wiki enrichment (Round 1) and encyclopedia (Round 2)."""

from __future__ import annotations

_ENRICHMENT_SYSTEM_EN = (
    "You are a senior software architect helping expand technical documentation. "
    "Produce clear, accurate Markdown sections grounded in the supplied page context."
)

_ENRICHMENT_SYSTEM_ZH = (
    "你是一位资深软件架构师，负责扩展技术文档。请基于提供的页面上下文，"
    "输出清晰、准确的 Markdown 章节。"
)

_ENCYCLOPEDIA_SYSTEM_EN = (
    "You are a technical writer creating encyclopedia-style documentation. "
    "Add practical reader-facing sections using only the facts implied by the page content."
)

_ENCYCLOPEDIA_SYSTEM_ZH = (
    "你是一位技术文档作者，正在编写百科风格的说明。请仅依据页面内容所暗示的事实，"
    "补充面向读者的实用章节。"
)

_ENRICHMENT_USER_EN = """\
You are enriching a wiki page for the following entity.

- **Name:** {entity_name}
- **Label:** {entity_label}

## Existing page (context only; do not repeat verbatim)

{page_content}

## Task (Round 1 — enrichment)

Generate **only** the following **new** Markdown sections. Do not restate the existing overview or duplicate content from the context. Use `##` headings exactly as named below.

1. **Business Flow Analysis** — describe how this unit participates in end-to-end flows.
2. **Design Patterns** — name applicable patterns and how they appear here.
3. **Call Chain Analysis** — summarize important inbound/outbound calls and dependencies.
4. **Key Design Decisions** — bullet notable tradeoffs and rationale.

Output nothing outside these four sections.
"""

_ENRICHMENT_USER_ZH = """\
请为以下实体丰富 Wiki 页面。

- **名称：** {entity_name}
- **类型：** {entity_label}

## 现有页面（仅供上下文；请勿逐字重复）

{page_content}

## 任务（第一轮：丰富）

请**仅**输出以下**新增** Markdown 章节。不要重复已有概述或上下文中的原文。请严格使用下方所示的 `##` 标题。

1. **业务流程分析** — 说明该单元如何参与端到端业务流程。
2. **设计模式** — 列出相关模式及其在本处的体现。
3. **调用链分析** — 概括重要的入站/出站调用与依赖。
4. **关键设计决策** — 以列表说明重要权衡与理由。

除上述四节外不要输出任何其他内容。
"""

_ENCYCLOPEDIA_USER_EN = """\
You are expanding a wiki page into encyclopedia-style documentation for:

- **Name:** {entity_name}
- **Label:** {entity_label}

## Existing page (context only; do not repeat verbatim)

{page_content}

## Task (Round 2 — encyclopedia)

Generate **only** the following **new** Markdown sections. Do not duplicate Round 1 or prior content. Use `##` headings exactly as named below.

1. **Usage Examples** — concrete scenarios and how callers use this unit.
2. **Frequently Asked Questions (FAQ)** — short Q&A a new reader would ask.
3. **Change History Notes** — what to watch when this area evolves (placeholders OK if unknown).
4. **Performance Considerations** — scaling, hotspots, or cost notes grounded in the context.

Output nothing outside these four sections.
"""

_ENCYCLOPEDIA_USER_ZH = """\
请将以下实体的 Wiki 扩展为百科式文档。

- **名称：** {entity_name}
- **类型：** {entity_label}

## 现有页面（仅供上下文；请勿逐字重复）

{page_content}

## 任务（第二轮：百科）

请**仅**输出以下**新增** Markdown 章节。不要重复第一轮或既有内容。请严格使用下方所示的 `##` 标题。

1. **使用示例** — 具体场景及调用方如何使用该单元。
2. **常见问题（FAQ）** — 新读者可能提出的简短问答。
3. **变更历史说明** — 该区域演进时需关注的内容（未知处可用占位说明）。
4. **性能考量** — 基于上下文的可扩展性、热点或成本提示。

除上述四节外不要输出任何其他内容。
"""


def _effective_language(language: str) -> str:
    """Normalize language code; unknown values fall back to English."""
    return "zh" if language == "zh" else "en"


class TieredPromptBuilder:
    """Builds user and system prompts for two-stage wiki LLM enrichment."""

    def build_enrichment_prompt(
        self,
        page_content: str,
        entity_name: str,
        entity_label: str,
        language: str,
    ) -> str:
        lang = _effective_language(language)
        template = _ENRICHMENT_USER_ZH if lang == "zh" else _ENRICHMENT_USER_EN
        return template.format(
            entity_name=entity_name,
            entity_label=entity_label,
            page_content=page_content,
        )

    def build_encyclopedia_prompt(
        self,
        page_content: str,
        entity_name: str,
        entity_label: str,
        language: str,
    ) -> str:
        lang = _effective_language(language)
        template = _ENCYCLOPEDIA_USER_ZH if lang == "zh" else _ENCYCLOPEDIA_USER_EN
        return template.format(
            entity_name=entity_name,
            entity_label=entity_label,
            page_content=page_content,
        )

    def enrichment_system_prompt(self, language: str) -> str:
        lang = _effective_language(language)
        return _ENRICHMENT_SYSTEM_ZH if lang == "zh" else _ENRICHMENT_SYSTEM_EN

    def encyclopedia_system_prompt(self, language: str) -> str:
        lang = _effective_language(language)
        return _ENCYCLOPEDIA_SYSTEM_ZH if lang == "zh" else _ENCYCLOPEDIA_SYSTEM_EN
