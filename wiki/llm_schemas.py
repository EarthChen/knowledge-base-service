"""Pydantic models for structured LLM output (json_schema + strict)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TopicItem(BaseModel):
    """A single topic within a domain split."""

    title: str
    slug: str
    module_keys: list[str] = Field(default_factory=list)


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
