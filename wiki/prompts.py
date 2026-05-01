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

SYSTEM_WIKI_PARENT_OVERVIEW = (
    "You are a senior technical writer creating a domain overview page that "
    "synthesizes information from its sub-domains. Write like a technical blog post "
    "— explain HOW sub-domains relate and WHY they exist together. "
    "Output valid JSON only."
)


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
