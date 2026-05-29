from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_SOURCE_REF_PATTERN = re.compile(
    r"`source://([^`#]+?)(?:#L(\d+)(?:-L?(\d+))?)?`"
)


@dataclass
class CitationResult:
    total_count: int = 0
    valid_count: int = 0
    invalid_count: int = 0
    skipped_count: int = 0
    invalid_refs: list[dict] = field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        return self.valid_count / self.total_count if self.total_count > 0 else 1.0


class CitationVerifier:
    """Verify source:// citations in wiki content against the knowledge graph."""

    def extract_citations(self, content: str) -> list[dict]:
        """Extract all source:// references from content."""
        refs = []
        for match in _SOURCE_REF_PATTERN.finditer(content):
            path = match.group(1).strip()
            start_line = int(match.group(2)) if match.group(2) else None
            end_line = int(match.group(3)) if match.group(3) else start_line
            if path:
                refs.append({
                    "path": path,
                    "start_line": start_line,
                    "end_line": end_line,
                    "raw": match.group(0),
                })
        return refs

    async def verify(self, content: str, *, graph_store: Any | None = None) -> CitationResult:
        """Verify all citations in content against graph store."""
        refs = self.extract_citations(content)
        result = CitationResult(total_count=len(refs))

        if not graph_store:
            result.skipped_count = len(refs)
            return result

        for ref in refs:
            try:
                # Query graph store for the file path
                query_result = await graph_store.query(
                    f"MATCH (n) WHERE n.path CONTAINS '{ref['path']}' "
                    "RETURN n.path AS path, n.end_line AS lines LIMIT 1"
                )
                if query_result and query_result[0]:
                    result.valid_count += 1
                else:
                    result.invalid_count += 1
                    result.invalid_refs.append({
                        "path": ref["path"],
                        "reason": "path not found in graph",
                        "raw": ref["raw"],
                    })
            except Exception as e:
                log.warning("citation_verify_error", path=ref["path"], error=str(e))
                result.skipped_count += 1

        return result
