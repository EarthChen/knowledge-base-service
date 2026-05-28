"""Pydantic models for structured LLM output (json_schema + strict)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TopicItem(BaseModel):
    """A single topic within a domain split."""

    title: str
    slug: str
    modules: list[str] = Field(default_factory=list)
    description: str = ""


class TopicPlanOutput(BaseModel):
    """Output schema for topic planning decisions."""

    should_split: bool
    topics: list[TopicItem] = Field(default_factory=list)
    reasoning: str = ""


class DomainMergeOutput(BaseModel):
    """Output schema for domain merge decisions."""

    merge_groups: list[list[str]] = Field(default_factory=list)


class DomainIssue(BaseModel):
    """A single issue found during domain review."""

    domain_slug: str
    issue_type: Literal[
        "misplaced_module",
        "semantic_overlap",
        "naming_unclear",
        "too_broad",
        "too_narrow",
    ]
    description: str
    severity: Literal["critical", "warning", "info"]


class DomainReviewOutput(BaseModel):
    """Output schema for domain decomposition review."""

    overall_quality: Literal["good", "acceptable", "needs_revision"]
    issues: list[DomainIssue] = Field(default_factory=list)



class CorrectorReviewOutput(BaseModel):
    """Structured output for GraphSemanticCorrector global review."""

    merges: list[dict] = Field(
        default_factory=list,
        description="Each: {sources: [...], target: str, new_display_name: str}",
    )
    renames: list[dict] = Field(
        default_factory=list,
        description="Each: {slug: str, new_display_name: str}",
    )
    moves: list[dict] = Field(
        default_factory=list,
        description="Each: {module: str, from: str, to: str}",
    )
    summary: str = ""
