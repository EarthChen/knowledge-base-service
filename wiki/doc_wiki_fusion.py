"""Document–wiki fusion: repository docs as wiki context and SOURCE_DOC graph links."""

from __future__ import annotations

from typing import Any

from store.wiki_store import WikiStore


async def find_related_docs(
    wiki_store: WikiStore,
    entity_names: list[str],
    limit: int = 5,
) -> list[dict[str, str]]:
    """Find repository documents that REFERENCE the given entities (name or FQN)."""
    if not entity_names:
        return []
    rows = await wiki_store.find_related_docs_entities(entity_names, limit)
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


async def create_source_doc_edges(
    wiki_store: WikiStore,
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
    await wiki_store.merge_source_doc_edges_batch(repository, wiki_page_path, files)
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
