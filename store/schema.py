"""Graph schema definitions for the code knowledge base.

Node types:
  - Function(name, file, start_line, end_line, docstring, code_snippet, language, signature,
             annotations, semantic_roles; optional indexed_at, repository, commit_sha)
  - Class(name, file, start_line, end_line, docstring, language, base_classes,
          annotations, semantic_roles; optional indexed_at, repository, commit_sha)
  - Module(name, path, language, description; optional indexed_at, repository, commit_sha)
  - Document(title, path, content_hash, section; optional indexed_at, repository, commit_sha)
  - BusinessFlow, BusinessConcept (business semantics)
  - WikiPage(uid, repository, path, title, content, page_type, generated_at; optional embedding,
             source_origin for user-crystallized Q&A pages)
  - WikiSpace(uid, business_id, title, description)
  - WikiSection(uid, title, description, section_type, sort_order)
  - WikiQA(uid, business_id, question, answer, source_pages, quality_score, created_at; embedding)
  - Chunk(text, parent_uid, parent_label, parent_name, chunk_index, file, start_line,
          end_line, content_hash, repository, indexed_at; embedding)

Edge types:
  - CALLS(caller → callee)
  - INHERITS(child → parent)
  - IMPORTS(importer → imported)
  - CONTAINS(parent → child)  e.g. class → method, module → function
  - USES_TYPE(function → type)
  - REFERENCES(doc → code_entity)
  - SOURCE_DOC(wiki page → document used as wiki context)
  - HAS_CHILD(parent → child, for tree structure)
  - WIKI_REFERENCES(source_page → target_page, cross-reference)
  - SOURCE_ENTITY(wiki_page → code_entity)
  - IMPLEMENTS, RELATES_TO, PART_OF, CONCEPT_IN (business semantics; PART_OF also Chunk→parent)
  - PROVIDES_RPC(provider class → module)
  - CONSUMES_RPC(consumer function → module)
  - CROSS_REPO_CALLS(consumer → provider across repositories)
  - DEPENDS_ON(bean → injected bean via Spring DI)
  - ACCESSES_TABLE(repository/DAO class → entity class)
  - EVENT_PRODUCES(function → Kafka topic module)
  - EVENT_CONSUMES(function → Kafka topic module)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum


def utc_indexed_at_iso() -> str:
    """UTC ISO-8601 timestamp recorded on nodes when they are indexed."""
    return datetime.now(timezone.utc).isoformat()


class NodeLabel(StrEnum):
    FUNCTION = "Function"
    CLASS = "Class"
    MODULE = "Module"
    DOCUMENT = "Document"
    BUSINESS_FLOW = "BusinessFlow"
    BUSINESS_CONCEPT = "BusinessConcept"
    WIKI_PAGE = "WikiPage"
    WIKI_SPACE = "WikiSpace"
    WIKI_SECTION = "WikiSection"
    WIKI_QA = "WikiQA"
    CHUNK = "Chunk"


class EdgeType(StrEnum):
    CALLS = "CALLS"
    INHERITS = "INHERITS"
    IMPORTS = "IMPORTS"
    CONTAINS = "CONTAINS"
    USES_TYPE = "USES_TYPE"
    REFERENCES = "REFERENCES"
    IMPLEMENTS = "IMPLEMENTS"
    RELATES_TO = "RELATES_TO"
    PART_OF = "PART_OF"
    CONCEPT_IN = "CONCEPT_IN"
    PROVIDES_RPC = "PROVIDES_RPC"
    CONSUMES_RPC = "CONSUMES_RPC"
    CROSS_REPO_CALLS = "CROSS_REPO_CALLS"
    DEPENDS_ON = "DEPENDS_ON"
    ACCESSES_TABLE = "ACCESSES_TABLE"
    EVENT_PRODUCES = "EVENT_PRODUCES"
    EVENT_CONSUMES = "EVENT_CONSUMES"
    SOURCE_DOC = "SOURCE_DOC"
    HAS_CHILD = "HAS_CHILD"
    WIKI_REFERENCES = "WIKI_REFERENCES"
    SOURCE_ENTITY = "SOURCE_ENTITY"


@dataclass
class GraphNode:
    label: NodeLabel
    properties: dict[str, str | int | float | list[str]]
    uid: str = ""

    def __post_init__(self) -> None:
        if not self.uid:
            name = self.properties.get("name", "")
            file_path = self.properties.get("file", "")
            line = self.properties.get("start_line", 0)
            self.uid = f"{self.label}:{file_path}:{name}:{line}"


@dataclass
class GraphEdge:
    edge_type: EdgeType
    source_uid: str
    target_uid: str
    properties: dict[str, str | int | float] = field(default_factory=dict)


VECTOR_INDEX_CONFIGS = [
    {"label": NodeLabel.FUNCTION, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.CLASS, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.DOCUMENT, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.BUSINESS_FLOW, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.BUSINESS_CONCEPT, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.MODULE, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.WIKI_PAGE, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.WIKI_QA, "attribute": "embedding", "similarity": "cosine"},
    {"label": NodeLabel.CHUNK, "attribute": "embedding", "similarity": "cosine"},
]
