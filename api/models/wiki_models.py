from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WikiQuickBody(BaseModel):
    git_url: str = Field(..., min_length=1)
    branch: str | None = None
    token: str | None = None
    mode: str = Field(default="structure", pattern="^(full|structure)$")
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None


class WikiSearchBody(BaseModel):
    repository: str = Field(..., min_length=1)
    query: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    limit: int = Field(default=10, ge=1, le=100)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    scope: str | None = None


class WikiGlobalSearchBody(BaseModel):
    """Cross-repository wiki search (all indexed repos unless ``repositories`` is set)."""

    query: str = Field(..., min_length=1)
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    limit: int = Field(default=30, ge=1, le=200)
    min_score: float = Field(default=0.0, ge=0.0, le=1.0)
    repositories: list[str] | None = Field(
        default=None,
        description="Optional allow-list of repository names (must be indexed).",
    )


class BusinessWikiGenerateBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    language: str = Field(default="en", pattern="^(en|zh)$")
    llm_provider: str | None = None
    incremental: bool = True
    force_reclassify: bool = False
    mode: str = Field(
        default="full",
        pattern="^(structure|full)$",
        description="Wiki generation mode: 'structure' for fast code-only, 'full' for LLM-enriched content",
    )
    config_overrides: dict[str, Any] = Field(
        default_factory=dict,
        description="Per-run config overrides merged into pipeline config (e.g. concurrency limits, flags).",
    )


class WikiAskBody(BaseModel):
    repository: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    scope: str | None = None
    conversation_id: str | None = None
    mode: str = Field(default="hybrid", pattern="^(hybrid|graph|semantic|keyword)$")
    record_memory: bool = False
    business_id: str | None = Field(
        default=None,
        description="When set with record_memory, persists Q&A under this business id",
    )


class WikiResearchBody(BaseModel):
    question: str = Field(..., min_length=1)
    repository: str = Field(..., min_length=1)
    business_id: str = Field(default="default", min_length=1)


class WikiCrystallizeBody(BaseModel):
    """Save an ask answer as a new wiki page (session crystallization)."""

    repository: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    sources: list[str] = Field(default_factory=list)
    conversation_id: str | None = None
    business_id: str = Field(default="default", min_length=1)


class WikiCrystallizeResponse(BaseModel):
    page_uid: str
    title: str
    path: str
    conversation_id: str | None = None


class WikiQaRecordBody(BaseModel):
    business_id: str = Field(..., min_length=1)
    question: str = Field(..., min_length=1)
    answer: str = Field(..., min_length=1)
    source_pages: list[str] = Field(default_factory=list)


class WikiLintBody(BaseModel):
    scope: str = Field(default="all", description="Lint filter: 'all' or wiki scope (repo, module:..., class:...).")


class WikiPageFeedbackBody(BaseModel):
    rating: str = Field(..., pattern="^(up|down)$")
    business_id: str = Field(default="default", min_length=1)
    comment: str = Field(default="", max_length=2000)
    severity: Literal["normal", "critical"] = "normal"


class WikiPageReviewBody(BaseModel):
    """Human review status for a wiki page (dashboard / QA workflow)."""

    status: str = Field(..., pattern="^(approved|needs_revision|pending_review)$")
    notes: str = ""


class WikiBatchReviewItem(BaseModel):
    page_path: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1)
    notes: str = ""


class WikiBatchReviewBody(BaseModel):
    business_id: str = Field(..., min_length=1)
    reviews: list[WikiBatchReviewItem]


class WikiRegenerateBody(BaseModel):
    heal_hints: str = ""


class WikiExportPreviewBody(BaseModel):
    target_dir: str = Field(..., min_length=1, description="Directory under which wiki markdown files are written.")
    include_auto_generated_marker: bool = True


class WikiExportExecuteBody(BaseModel):
    target_dir: str = Field(..., min_length=1)
    selected_files: list[str] | None = Field(
        default=None,
        description=(
            "If set, only these wiki paths are written (create/update). "
            "If null, all pending create/update from preview."
        ),
    )


class AnalyzeImpactFile(BaseModel):
    path: str
    status: str = Field(pattern="^(added|modified|removed|renamed)$")


class AnalyzeImpactBody(BaseModel):
    changed_files: list[AnalyzeImpactFile]


class ChunkIndexBody(BaseModel):
    repository: str = Field(..., min_length=1)


class IngestRequest(BaseModel):
    repository: str
    files: list[str] = []
    git_ref: str | None = None


class GitPushConfig(BaseModel):
    remote_url: str = Field(..., min_length=1)
    branch: str = Field(default="main")
    commit_message_prefix: str = Field(default="docs(wiki):")


class WikiPageContentBody(BaseModel):
    content: str = Field(..., max_length=500_000)
    edit_reason: str = Field(default="", max_length=1000)
    expected_version: int | None = None


class BusinessWikiExportBody(BaseModel):
    business_id: str = Field(default="default", min_length=1)
    format: str = Field(..., pattern="^(markdown|git|obsidian|mkdocs)$")
    git_config: GitPushConfig | None = None


class McpToolCallBody(BaseModel):
    """MCP HTTP tool invocation body (``name`` + ``arguments``)."""

    model_config = ConfigDict(extra="ignore")

    name: str = Field(..., min_length=1, max_length=256)
    arguments: dict[str, Any] = Field(default_factory=dict)
