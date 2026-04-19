"""Document–wiki fusion: repository docs as wiki context and SOURCE_DOC graph links."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from store.schema import EdgeType


@runtime_checkable
class _GraphExecutePort(Protocol):
    async def execute_query(self, cypher: str, params: dict[str, Any] | None = None) -> Any: ...


_RELATED_DOCS_CYPHER = (
    "MATCH (d:Document)-[:REFERENCES]->(e) "
    "WHERE e.name IN $entities OR e.fqn IN $entities "
    "RETURN DISTINCT d.file AS file, d.content AS content "
    "LIMIT $limit"
)


async def find_related_docs(
    store: _GraphExecutePort,
    entity_names: list[str],
    limit: int = 5,
) -> list[dict[str, str]]:
    """Find repository documents that REFERENCE the given entities (name or FQN)."""
    if not entity_names:
        return []
    rows = await store.execute_query(
        _RELATED_DOCS_CYPHER,
        {"entities": entity_names, "limit": limit},
    )
    data = getattr(rows, "data", None) or []
    out: list[dict[str, str]] = []
    for r in data:
        if not isinstance(r, dict):
            continue
        file_val = r.get("file")
        file_s = str(file_val) if file_val is not None else ""
        if not file_s:
            continue
        raw_content = r.get("content", "")
        content_s = str(raw_content) if raw_content is not None else ""
        out.append({"file": file_s, "content": content_s})
    return out


_SOURCE_DOC_EDGE = EdgeType.SOURCE_DOC.value

_BATCH_SOURCE_DOC_CYPHER = (
    "UNWIND $docs AS doc_file "
    f"MATCH (wp:WikiPage {{repository: $repository, path: $path}}) "
    "MATCH (d:Document) "
    "WHERE d.file = doc_file AND d.repository = $repository "
    f"MERGE (wp)-[:{_SOURCE_DOC_EDGE}]->(d) "
    "RETURN count(*) AS cnt"
)


async def create_source_doc_edges(
    store: _GraphExecutePort,
    *,
    repository: str,
    wiki_page_path: str,
    docs: list[dict[str, str]],
) -> int:
    """Link a persisted WikiPage to Document nodes used as context (WikiPage -[SOURCE_DOC]-> Document)."""
    files = [str(d.get("file") or "").strip() for d in docs]
    files = [f for f in files if f]
    if not files:
        return 0
    await store.execute_query(
        _BATCH_SOURCE_DOC_CYPHER,
        {"repository": repository, "path": wiki_page_path, "docs": files},
    )
    return len(files)


def format_related_docs_for_prompt(docs: list[dict[str, str]], *, max_chars_per_doc: int = 4000) -> str:
    """Build a markdown block for LLM context from ``find_related_docs`` results."""
    if not docs:
        return ""
    parts = ["## Repository documents (referenced scope)", ""]
    for d in docs:
        body = (d.get("content") or "").strip()
        if len(body) > max_chars_per_doc:
            body = body[:max_chars_per_doc].rstrip() + "\n\n_(truncated)_"
        parts.append(f"### File: `{d.get('file', '')}`")
        parts.append(body or "_(no body)_")
        parts.append("")
    return "\n".join(parts).strip()
