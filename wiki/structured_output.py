"""Structured output model for wiki page generation.

Defines the WikiPageOutput Pydantic model that constrains LLM output
to a predictable JSON structure, and a renderer to convert it to Markdown.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class WikiSection(BaseModel):
    heading: str
    content: str
    code_refs: list[str] = Field(default_factory=list)


class WikiPageOutput(BaseModel):
    title: str
    summary: str
    sections: list[WikiSection]
    modules_covered: list[str]
    dependencies_mentioned: list[str] = Field(default_factory=list)


def render_wiki_page(output: WikiPageOutput) -> str:
    """Convert structured output to Markdown page."""
    parts: list[str] = [f"# {output.title}", "", output.summary, ""]

    for section in output.sections:
        parts.append(f"## {section.heading}")
        parts.append("")
        parts.append(section.content)
        if section.code_refs:
            parts.append("")
            parts.append("**Related code:** " + ", ".join(f"`{ref}`" for ref in section.code_refs))
        parts.append("")

    return "\n".join(parts)
