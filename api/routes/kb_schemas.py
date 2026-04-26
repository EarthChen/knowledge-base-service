"""Pydantic request/response models shared by Knowledge Base API routes (formerly in ``main``)."""

from __future__ import annotations

import re
from typing import Any, Self

from pydantic import BaseModel, Field, field_validator, model_validator

from utils.git_utils import looks_like_git_url

_HYBRID_ENTITY_TYPE_TO_LABEL: dict[str, str] = {
    "function": "Function",
    "class": "Class",
    "module": "Module",
    "document": "Document",
    "flow": "BusinessFlow",
    "concept": "BusinessConcept",
}
HYBRID_ENTITY_FILTER_CHOICES = frozenset(_HYBRID_ENTITY_TYPE_TO_LABEL.keys())


class GraphQueryRequest(BaseModel):
    query_type: str
    name: str = ""
    file: str = ""
    depth: int = Field(default=3, ge=1, le=10)
    direction: str = Field(default="downstream", pattern="^(upstream|downstream|children|parents)$")
    cypher: str = ""
    entity_type: str = Field(default="any", pattern="^(function|class|any)$")


class HybridSearchRequest(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=20)
    expand_depth: int = Field(default=2, ge=1, le=5)
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=20, ge=1, le=500)
    sort_by: str = Field(
        default="score",
        pattern="^(score|name|path)$",
        description="Sort merged semantic results: score (RRF, default), name, or file path.",
    )
    entity_type: str | None = Field(
        default=None,
        description=(
            "Optional filter: function, class, module, document, flow (BusinessFlow), "
            "concept (BusinessConcept); omit for all entity kinds."
        ),
    )
    repository: str | None = Field(
        default=None,
        description="Filter results to a specific repository (Cypher-level filtering).",
    )
    repositories: list[str] | None = Field(
        default=None,
        max_length=10,
        description="Search multiple repositories in parallel; fused by score. Max 10. Overrides repository when non-empty.",
    )
    language: str | None = Field(
        default=None,
        description="Filter results by programming language (python, java, go, javascript, typescript).",
    )

    @field_validator("repositories", mode="before")
    @classmethod
    def _normalize_hybrid_repositories(cls, value: Any) -> list[str] | None:
        if value is None:
            return None
        if not isinstance(value, list):
            raise ValueError("repositories must be an array of strings")
        out: list[str] = []
        for item in value:
            if not isinstance(item, str):
                raise ValueError("repositories must contain only strings")
            s = item.strip()
            if s:
                out.append(s)
        return out

    @field_validator("entity_type", mode="before")
    @classmethod
    def _normalize_hybrid_entity_type(cls, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        if not isinstance(value, str):
            raise TypeError("entity_type must be a string or null")
        key = value.strip().lower()
        if key not in HYBRID_ENTITY_FILTER_CHOICES:
            allowed = ", ".join(sorted(HYBRID_ENTITY_FILTER_CHOICES))
            raise ValueError(f"entity_type must be one of: {allowed}, or null")
        return key


class DeepSearchRequest(BaseModel):
    query: str
    max_iterations: int = Field(default=3, ge=1, le=5)
    include_code: bool = True


class IndexRequest(BaseModel):
    directory: str = ""
    git_url: str = ""
    branch: str | None = None
    mode: str = Field(default="full", pattern="^(full|incremental)$")
    base_ref: str = "HEAD~1"
    head_ref: str = "HEAD"
    repository: str | None = None


class ReindexAllRequest(BaseModel):
    """Trigger full re-index for many repositories (background tasks)."""

    base_dir: str | None = Field(
        default=None,
        description="Optional base directory; each repo is indexed from base_dir/repository_name when set.",
    )
    repositories: list[str] = Field(
        default_factory=list,
        description="When empty, all repositories present in the graph are re-indexed.",
    )


class IndexFileRequest(BaseModel):
    file_path: str
    content: str
    repository: str | None = None


class IndexFilesRequest(BaseModel):
    files: list[IndexFileRequest]
    repository: str | None = None


class EnrichRequest(BaseModel):
    """对已索引的 Function/Class 批量补全 business_summary（不重新解析代码）。"""

    repository: str = Field(..., min_length=1, description="仓库名称")
    force: bool = False


class GraphExploreRequest(BaseModel):
    name: str = ""
    depth: int = Field(default=2, ge=1, le=5)
    limit: int = Field(default=100, ge=1, le=500)


class GraphExpandRequest(BaseModel):
    node_name: str = Field(..., min_length=1)
    center_uid: str | None = None
    limit: int = Field(default=20, ge=1, le=100)
    depth: int = Field(default=1, ge=1, le=3)
    exclude_uids: list[str] = Field(default_factory=list, max_length=2000)


class BlastRadiusRequest(BaseModel):
    entity_names: list[str] = Field(..., min_length=1, max_length=20)
    max_depth: int = Field(default=3, ge=1, le=5)
    repository: str | None = None


class ImpactAnalysisRequest(BaseModel):
    changed_functions: list[str] = Field(..., min_length=1)
    max_depth: int = Field(default=5, ge=1, le=50)


class PrFetchRequest(BaseModel):
    """GitHub pull request or GitLab merge request URL for remote file listing."""

    url: str = Field(..., min_length=1)


class ReviewContextRequest(BaseModel):
    diff_text: str | None = Field(
        default=None,
        description="Unified diff text from git diff (optional if branch and repo_path are set)",
    )
    branch: str | None = Field(default=None, description="Branch to compare against base_branch")
    base_branch: str | None = Field(
        default=None,
        description='Base branch for git diff (defaults to "master" when using branch/repo_path)',
    )
    repo_url: str | None = Field(
        default=None,
        description="Remote git URL (reserved for future server-side fetch; validated when set)",
    )
    repo_path: str | None = Field(
        default=None,
        description="Local filesystem path to the git repository root (required with branch when diff_text is omitted)",
    )
    repository: str | None = None
    max_depth: int = Field(default=3, ge=1, le=20)

    @model_validator(mode="after")
    def validate_diff_source(self) -> Self:
        has_diff = self.diff_text is not None and self.diff_text.strip() != ""
        b = (self.branch or "").strip()
        p = (self.repo_path or "").strip()
        has_branch_path = bool(b) and bool(p)
        if not has_diff and not has_branch_path:
            raise ValueError(
                "Provide either non-empty diff_text, or both branch and repo_path",
            )
        ru = (self.repo_url or "").strip()
        if ru and not looks_like_git_url(ru):
            raise ValueError("repo_url does not look like a valid git remote URL")
        return self


class SmartContextRequest(BaseModel):
    entity_name: str = Field(..., min_length=1)
    entity_type: str = Field(default="function", pattern="^(function|class)$")
    repository: str | None = None


class MCPToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?",
)

ARCHITECTURE_LAYERS = frozenset({
    "presentation",
    "business",
    "data_access",
    "rpc",
    "messaging",
    "infrastructure",
    "model",
    "unknown",
})


class CreateBusinessRequest(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,62}$")
    name: str
    description: str = ""


class SyncRepoRequest(BaseModel):
    """Request to git pull and incrementally re-index a repository."""
    repository: str = Field(..., description="Repository name (must already be indexed)")
    directory: str | None = Field(
        default=None,
        description="Repository root directory (required when using relative paths)",
    )
    git_url: str = Field(default="", description="Git clone URL for remote repos (auto-clones if not yet local)")
    branch: str | None = Field(default=None, description="Branch to checkout")
    base_ref: str = Field(default="HEAD~1", description="Git diff base reference")
    head_ref: str = Field(default="HEAD", description="Git diff head reference")


class SyncAllRequest(BaseModel):
    """Request to sync all indexed repositories."""
    repo_dirs: dict[str, str] | None = Field(
        default=None,
        description=(
            "Mapping of repo name → local directory path "
            "(required for relative-path indexed repos)"
        ),
    )
    base_ref: str = Field(default="HEAD~1", description="Git diff base reference")
    head_ref: str = Field(default="HEAD", description="Git diff head reference")


class SyncScheduleRequest(BaseModel):
    """Create or update a periodic git pull + incremental re-index schedule."""

    repo_name: str = Field(..., min_length=1)
    git_url: str = Field(..., min_length=1)
    branch: str | None = None
    interval_minutes: int = Field(default=60, ge=5, le=1440)
    enabled: bool = True


class SyncScheduleResponse(BaseModel):
    """One persisted schedule row returned to clients."""

    repo_name: str
    git_url: str
    branch: str | None
    interval_minutes: int
    enabled: bool
    last_sync_at: str | None
    last_sync_status: str
    last_sync_detail: str
    created_at: str


# ---- Backward compatibility for tests that referenced private names on main ----
_HYBRID_ENTITY_FILTER_CHOICES = HYBRID_ENTITY_FILTER_CHOICES
_HYBRID_ENTITY_TYPE_TO_LABEL = _HYBRID_ENTITY_TYPE_TO_LABEL
_FQN_RE = FQN_RE
_ARCHITECTURE_LAYERS = ARCHITECTURE_LAYERS
