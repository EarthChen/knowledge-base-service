"""Centralized prompt management using LangChain ChatPromptTemplate."""
from __future__ import annotations

import hashlib

from langchain_core.prompts import ChatPromptTemplate

# ---------------------------------------------------------------------------
# Shared system prompt constants
# ---------------------------------------------------------------------------

SYSTEM_JSON_ONLY = "Reply with JSON only. No markdown fences."

SYSTEM_WIKI_AUTHOR = (
    "You are a technical wiki author writing business domain documentation. "
    "Write like a technical blog post — explain WHY these services exist, "
    "HOW they collaborate, and WHAT business value they deliver. "
    "Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
    "Do NOT explain frameworks or annotations — focus on business logic and "
    "the story behind the architecture."
)

SYSTEM_WIKI_HEAL = (
    "You are a technical wiki author specializing in business domain documentation. "
    "Output Markdown with Mermaid diagrams. Use Chinese for business descriptions. "
    "Focus on business logic and service interactions. "
    "Do NOT explain frameworks or annotations."
)

def system_wiki_parent_overview(language: str = "简体中文") -> str:
    return (
        "You are a senior technical writer creating a domain overview page. "
        "Your role is to SYNTHESIZE sub-domain information into a coherent narrative "
        "that explains how these sub-domains form a complete business capability.\n\n"
        "Output requirements:\n"
        "1. Title: Use the domain's display name\n"
        "2. Structure your content with these sections:\n"
        "   - ## 业务概述: Domain's purpose and position in the system (2-3 paragraphs)\n"
        "   - ## 子域架构: How sub-domains relate, with a Mermaid flowchart\n"
        "   - ## 数据流: Key data flows between sub-domains (Mermaid sequence diagram)\n"
        "   - ## 核心接口: Key interfaces referenced from code\n"
        f"3. Write in {language} for all business descriptions\n"
        "4. Do NOT just list sub-domains; explain the STORY of how they work together\n"
        "5. Include at least one Mermaid diagram showing sub-domain interactions\n"
        "6. Output valid JSON only."
    )


# Keep backward compatibility
SYSTEM_WIKI_PARENT_OVERVIEW = system_wiki_parent_overview()


def versioned_prompt(
    name: str,
    template: ChatPromptTemplate,
    version: str = "1.0",
) -> ChatPromptTemplate:
    """Attach version metadata for cache invalidation.

    Returns a shallow copy so the original template is not mutated.
    """
    vp = template.model_copy()
    vp.metadata = {"name": name, "version": version}
    return vp


def prompt_hash(template: ChatPromptTemplate, **kwargs: str) -> str:
    """Content hash for cache key derivation."""
    version = (template.metadata or {}).get("version", "1.0")
    rendered = template.format(**kwargs)
    content = f"{version}:{rendered}"
    return hashlib.sha256(content.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# Prompt definitions
# ---------------------------------------------------------------------------

DOMAIN_CLASSIFY_PROMPT = versioned_prompt(
    name="domain_classify",
    version="2.0",
    template=ChatPromptTemplate.from_messages([
        ("system", (
            "You are a software architecture expert. "
            "Classify repository modules into business domains. "
            "Output ONLY valid JSON."
        )),
        ("human", (
            "Classify the following modules into business domains.\n\n"
            "Rules:\n"
            "- Use 5-20 domains, lowercase-kebab-case names, 1-3 words\n"
            "- Each domain must have >=3 modules\n"
            "- Do NOT create domains named after technical concepts: enums, data_structures, utilities, infrastructure, configuration, constants\n"
            "- Domain names must represent business capabilities (e.g., payment, messaging, user-management)\n"
            "- These modules belong to a unified microservice system; group by business function, not by repository\n"
            "- Place shared utilities under '{infrastructure_label}'\n\n"
            "Repository: {repository_id}\n"
            "Modules:\n{modules_json}\n\n"
            "Return ONLY valid JSON: object with domain names as keys "
            "and arrays of module names as values."
        )),
    ]),
)
