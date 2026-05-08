"""Verify that code references in wiki content correspond to real entities."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_BACKTICK_REF = re.compile(
    r"`([A-Z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)(?:\(\))?`"
)
_SOURCE_REF = re.compile(r"source://[\w./]+?([A-Z][a-zA-Z0-9_]*)")
_COMMON_NON_ENTITIES = frozenset({
    "String", "Integer", "Boolean", "List", "Map", "Set", "Object",
    "JSON", "HTTP", "HTTPS", "API", "DTO", "CRUD", "SQL", "UUID",
    "Mermaid", "Markdown", "Java", "Python", "Kotlin",
})


def extract_code_references(content: str) -> list[str]:
    """Extract unique code entity references from wiki content."""
    refs: set[str] = set()
    for m in _BACKTICK_REF.finditer(content):
        for part in m.group(1).split("."):
            if (
                len(part) > 1
                and part not in _COMMON_NON_ENTITIES
                and part[0].isupper()
            ):
                refs.add(part)
    for m in _SOURCE_REF.finditer(content):
        name = m.group(1)
        if name not in _COMMON_NON_ENTITIES:
            refs.add(name)
    return sorted(refs)


@dataclass
class CitationResult:
    valid_refs: list[str] = field(default_factory=list)
    invalid_refs: list[str] = field(default_factory=list)

    @property
    def valid_count(self) -> int:
        return len(self.valid_refs)

    @property
    def invalid_count(self) -> int:
        return len(self.invalid_refs)


def verify_citations(content: str, known_entities: set[str]) -> CitationResult:
    """Verify code references against a set of known entity names."""
    refs = extract_code_references(content)
    result = CitationResult()
    for ref in refs:
        if ref in known_entities:
            result.valid_refs.append(ref)
        else:
            result.invalid_refs.append(ref)
    return result
