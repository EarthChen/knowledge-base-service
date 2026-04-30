"""Centralized prompt management using LangChain ChatPromptTemplate."""
from __future__ import annotations

import hashlib

from langchain_core.prompts import ChatPromptTemplate


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
            "- Place shared utilities under '{infrastructure_label}'\n\n"
            "Repository: {repository_id}\n"
            "Modules:\n{modules_json}\n\n"
            "Return ONLY valid JSON: object with domain names as keys "
            "and arrays of module names as values."
        )),
    ]),
)

TOPIC_STRUCTURE_PROMPT = versioned_prompt(
    name="topic_structure",
    version="1.0",
    template=ChatPromptTemplate.from_messages([
        ("system", "You are a technical documentation planner. Output ONLY valid JSON."),
        ("human", (
            "Based on the following business domain classification, plan a Wiki structure.\n\n"
            "Rules:\n"
            "1. Generate {min_pages}-{max_pages} topic pages total\n"
            "2. Each top-level topic = one business domain or a merge of related domains\n"
            "3. Each topic can have 3-5 sub-pages\n"
            "4. Assign every module to exactly one page\n\n"
            "Domains:\n{domain_mapping_json}\n\n"
            "Output JSON: array of objects with title, description, modules, sub_topics"
        )),
    ]),
)
