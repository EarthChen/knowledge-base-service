"""Graph schema definitions for the code knowledge base.

Node types:
  - Function(name, file, start_line, end_line, docstring, code_snippet, language, signature,
             annotations, semantic_roles)
  - Class(name, file, start_line, end_line, docstring, language, base_classes,
          annotations, semantic_roles)
  - Module(name, path, language, description)
  - Document(title, path, content_hash, section)
  - BusinessFlow, BusinessConcept (business semantics)

Edge types:
  - CALLS(caller → callee)
  - INHERITS(child → parent)
  - IMPORTS(importer → imported)
  - CONTAINS(parent → child)  e.g. class → method, module → function
  - USES_TYPE(function → type)
  - REFERENCES(doc → code_entity)
  - IMPLEMENTS, RELATES_TO, PART_OF, CONCEPT_IN (business semantics)
  - PROVIDES_RPC(provider class → module)
  - CONSUMES_RPC(consumer function → module)
  - CROSS_REPO_CALLS(consumer → provider across repositories)
  - DEPENDS_ON(bean → injected bean via Spring DI)
  - ACCESSES_TABLE(repository/DAO class → entity class)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class NodeLabel(StrEnum):
    FUNCTION = "Function"
    CLASS = "Class"
    MODULE = "Module"
    DOCUMENT = "Document"
    BUSINESS_FLOW = "BusinessFlow"
    BUSINESS_CONCEPT = "BusinessConcept"


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
]
