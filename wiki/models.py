"""Wiki generation data models.

Defines the core types used across the wiki generation pipeline:
WikiPage, WikiStructure, WikiConfig, ScopeParam, SourceLocation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class PageType(StrEnum):
    MODULE_OVERVIEW = "module_overview"
    CLASS_DETAIL = "class_detail"
    REPO_OVERVIEW = "repo_overview"
    ARCHITECTURE = "architecture"
    API_REFERENCE = "api_reference"
    DATA_FLOW = "data_flow"
    DOMAIN_OVERVIEW = "domain_overview"
    BUSINESS_FLOW = "business_flow"
    INDEX = "index"
    # Saved from Q&A session crystallization
    CRYSTALLIZED = "crystallized"


class DiagramType(StrEnum):
    CLASS_DIAGRAM = "classDiagram"
    FLOWCHART = "flowchart"
    DEPENDENCY_GRAPH = "dependencyGraph"


class ImportanceTier(StrEnum):
    CORE = "core"
    STANDARD = "standard"
    SKELETON = "skeleton"


class WikiQualityDimension(StrEnum):
    COMPLETENESS = "completeness"
    HELPFULNESS = "helpfulness"
    TRUTHFULNESS = "truthfulness"


@dataclass
class WikiPageQualityScore:
    page_path: str
    completeness: float
    helpfulness: float
    truthfulness: float
    overall: float
    issues: list[str] = field(default_factory=list)


class EnrichmentLevel(StrEnum):
    BASE = "base"
    ENRICHED = "enriched"
    ENCYCLOPEDIA = "encyclopedia"


class SkeletonStrategy(StrEnum):
    TEMPLATE = "template"
    LIGHT_MODEL = "light_model"
    SKIP = "skip"


@dataclass
class WikiPageSummary:
    """Short summary extracted from a composed WikiPage for parent aggregation."""

    entity_uid: str
    title: str
    path: str
    summary: str
    importance_tier: ImportanceTier | None
    page_type: PageType


@dataclass
class NavigationContext:
    """Contextual navigation metadata for wiki page rendering."""

    parent_path: str | None = None
    parent_title: str | None = None
    sibling_paths: list[str] = field(default_factory=list)
    child_paths: list[str] = field(default_factory=list)
    related_flow_paths: list[str] = field(default_factory=list)
    breadcrumbs: list[tuple[str, str]] = field(default_factory=list)

    def to_api_dict(self) -> dict[str, Any]:
        """JSON-serializable shape for APIs (breadcrumbs as list pairs)."""
        return {
            "parent_path": self.parent_path,
            "parent_title": self.parent_title,
            "sibling_paths": list(self.sibling_paths),
            "child_paths": list(self.child_paths),
            "related_flow_paths": list(self.related_flow_paths),
            "breadcrumbs": [[t, p] for t, p in self.breadcrumbs],
        }

    @classmethod
    def from_api_dict(cls, data: dict[str, Any]) -> NavigationContext:
        crumbs_raw = data.get("breadcrumbs") or []
        breadcrumbs: list[tuple[str, str]] = []
        for item in crumbs_raw:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                breadcrumbs.append((str(item[0]), str(item[1])))
        return cls(
            parent_path=data.get("parent_path"),
            parent_title=data.get("parent_title"),
            sibling_paths=[str(x) for x in (data.get("sibling_paths") or [])],
            child_paths=[str(x) for x in (data.get("child_paths") or [])],
            related_flow_paths=[str(x) for x in (data.get("related_flow_paths") or [])],
            breadcrumbs=breadcrumbs,
        )


def navigation_context_api_from_stored_json(raw: str | None) -> dict[str, Any]:
    """Parse ``navigation_json`` from graph; invalid or empty → empty defaults."""
    empty = NavigationContext().to_api_dict()
    if raw is None or not str(raw).strip():
        return empty
    try:
        data = json.loads(str(raw))
    except json.JSONDecodeError:
        return empty
    if not isinstance(data, dict):
        return empty
    try:
        return NavigationContext.from_api_dict(data).to_api_dict()
    except (TypeError, ValueError):
        return empty


@dataclass
class CodeSnippet:
    source: str
    file_path: str
    start_line: int
    end_line: int
    origin: str  # "chunk" | "file" | "signature"


@dataclass
class ChunkSnippet:
    """A semantically retrieved code chunk for RAG context enrichment."""

    text: str
    file_path: str
    score: float
    parent_name: str
    parent_uid: str = ""
    start_line: int = 0
    end_line: int = 0


_VALID_SCOPE_TYPES = frozenset({"repo", "module", "class", "business"})


@dataclass(frozen=True)
class ScopeParam:
    scope_type: str
    value: str | None = None


def parse_scope(raw: str) -> ScopeParam:
    """Parse a scope string into a ScopeParam.

    Supported formats:
      - "repo"
      - "business"
      - "module:<path>"
      - "class:<fqn>"

    Raises ValueError on invalid input.
    """
    if not raw:
        raise ValueError("Invalid scope: empty string")

    if raw == "repo":
        return ScopeParam(scope_type="repo")

    if raw == "business":
        return ScopeParam(scope_type="business")

    if ":" not in raw:
        raise ValueError(
            f"Invalid scope '{raw}': must be 'repo', 'business', 'module:<path>', or 'class:<fqn>'"
        )

    scope_type, _, value = raw.partition(":")
    if scope_type not in _VALID_SCOPE_TYPES:
        raise ValueError(
            f"Invalid scope type '{scope_type}': must be one of {sorted(_VALID_SCOPE_TYPES)}"
        )
    if not value:
        raise ValueError(f"Invalid scope '{raw}': value cannot be empty after '{scope_type}:'")

    return ScopeParam(scope_type=scope_type, value=value)


@dataclass
class SourceLocation:
    file_path: str
    start_line: int
    end_line: int
    fqn: str
    repository: str

    def to_source_link(self) -> str:
        return f"[`{self.file_path}:{self.start_line}-{self.end_line}`](source://{self.repository}/{self.file_path}#L{self.start_line})"

    def to_ide_link(self, editor: str, repo_path: str) -> str:
        full_path = f"{repo_path}/{self.file_path}"
        if editor == "vscode":
            return f"vscode://file/{full_path}:{self.start_line}"
        if editor == "cursor":
            return f"cursor://file/{full_path}:{self.start_line}"
        if editor == "idea":
            return f"idea://open?file={full_path}&line={self.start_line}"
        raise ValueError(f"Unsupported editor '{editor}': use 'vscode', 'cursor', or 'idea'")

    def to_dict(self) -> dict[str, Any]:
        return {
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "fqn": self.fqn,
            "repository": self.repository,
        }


@dataclass
class WikiConfig:
    repository: str
    mode: str = "structure"
    format: str = "json"
    language: str = "en"
    comment_injection_tier: int = 2
    comment_max_chars: int = 500

    def __post_init__(self) -> None:
        if self.mode not in ("full", "structure"):
            raise ValueError(f"Invalid mode '{self.mode}': must be 'full' or 'structure'")
        if self.format not in ("json", "markdown"):
            raise ValueError(f"Invalid format '{self.format}': must be 'json' or 'markdown'")
        if self.language not in ("en", "zh"):
            raise ValueError(f"Invalid language '{self.language}': must be 'en' or 'zh'")


@dataclass
class WikiSpaceNode:
    uid: str
    business_id: str
    title: str
    description: str
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()
        if not self.updated_at:
            self.updated_at = self.created_at


@dataclass
class WikiSectionNode:
    uid: str
    title: str
    description: str
    section_type: str  # "business_domain" | "code_module" | "topic"
    sort_order: int
    icon: str | None = None
    auto_generated: bool = True


@dataclass
class WikiDiagram:
    diagram_type: DiagramType
    content: str
    title: str = ""


@dataclass
class WikiPageMetadata:
    node_count: int
    edge_count: int
    generation_mode: str = "structure"
    fallback_tier: int | None = None
    generated_at: str | None = None
    enrichment_level: str | None = None


@dataclass
class WikiPage:
    path: str
    title: str
    page_type: PageType
    content: str
    diagrams: list[WikiDiagram]
    source_locations: list[SourceLocation]
    metadata: WikiPageMetadata
    method_locations: list[SourceLocation] = field(default_factory=list)
    navigation: NavigationContext | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "page_type": self.page_type.value,
            "content": self.content,
            "diagrams": [
                {"type": d.diagram_type.value, "content": d.content, "title": d.title}
                for d in self.diagrams
            ],
            "source_locations": [loc.to_dict() for loc in self.source_locations],
            "method_locations": [loc.to_dict() for loc in self.method_locations],
            "metadata": {
                "node_count": self.metadata.node_count,
                "edge_count": self.metadata.edge_count,
                "generation_mode": self.metadata.generation_mode,
                "fallback_tier": self.metadata.fallback_tier,
                "generated_at": self.metadata.generated_at,
                "enrichment_level": self.metadata.enrichment_level,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WikiPage:
        repo_fallback = data.get("repository", "")
        return WikiPage(
            path=data["path"],
            title=data["title"],
            page_type=PageType(data["page_type"]),
            content=data["content"],
            diagrams=[
                WikiDiagram(
                    diagram_type=DiagramType(d["type"]),
                    content=d["content"],
                    title=d.get("title", ""),
                )
                for d in data.get("diagrams", [])
            ],
            source_locations=[
                SourceLocation(
                    file_path=s["file_path"],
                    start_line=s["start_line"],
                    end_line=s["end_line"],
                    fqn=s["fqn"],
                    repository=s.get("repository", repo_fallback),
                )
                for s in data.get("source_locations", [])
            ],
            metadata=WikiPageMetadata(
                node_count=data["metadata"]["node_count"],
                edge_count=data["metadata"]["edge_count"],
                generation_mode=data["metadata"].get("generation_mode", "structure"),
                fallback_tier=data["metadata"].get("fallback_tier"),
                generated_at=data["metadata"].get("generated_at"),
                enrichment_level=data["metadata"].get("enrichment_level"),
            ),
            method_locations=[
                SourceLocation(
                    file_path=s["file_path"],
                    start_line=s["start_line"],
                    end_line=s["end_line"],
                    fqn=s["fqn"],
                    repository=s.get("repository", repo_fallback),
                )
                for s in data.get("method_locations", [])
            ],
        )

    def to_markdown(self) -> str:
        parts = [self.content]
        for diagram in self.diagrams:
            if diagram.title:
                parts.append(f"\n## {diagram.title}\n")
            parts.append(f"\n```mermaid\n{diagram.content}\n```\n")
        return "\n".join(parts)


@dataclass
class WikiStructureNode:
    path: str
    title: str
    page_type: PageType
    children: list[WikiStructureNode] = field(default_factory=list)

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0

    def sorted_children(self) -> list[WikiStructureNode]:
        return sorted(self.children, key=lambda c: c.title)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "title": self.title,
            "page_type": self.page_type.value,
            "children": [c.to_dict() for c in self.children],
        }


@dataclass
class WikiStructure:
    repository: str
    root: WikiStructureNode
    total_pages: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "repository": self.repository,
            "root": self.root.to_dict(),
            "total_pages": self.total_pages,
        }
