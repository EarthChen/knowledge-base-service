"""Persist Q&A answers as wiki pages (crystallization) with backlinks to source pages."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from log import get_logger
from store.wiki_store import WikiStore

log = get_logger(__name__)

_SOURCE_ORIGIN_CRYSTALLIZED = "crystallized"


def title_from_question(question: str, *, max_len: int = 120) -> str:
    """Derive a readable page title from the user question."""
    text = (question or "").strip()
    if not text:
        return "Q&A note"
    line = text.split("\n", 1)[0].strip()
    if len(line) > max_len:
        return line[: max_len - 1].rstrip() + "…"
    return line


def _slug_fragment(text: str, *, max_len: int = 48) -> str:
    """ASCII/CJK-safe path segment; empty input becomes ``qa``."""
    raw = (text or "").strip().lower()
    raw = re.sub(r"[\s/\\]+", "-", raw)
    raw = re.sub(r"[^a-z0-9._\-\u4e00-\u9fff]+", "-", raw)
    raw = re.sub(r"-+", "-", raw).strip("-")[:max_len]
    return raw or "qa"


def _build_page_path(title: str) -> str:
    slug = _slug_fragment(title)
    short = uuid.uuid4().hex[:8]
    return f"crystallized/{slug}-{short}.md"


def _build_content(question: str, answer: str, source_paths: list[str]) -> str:
    parts: list[str] = []
    q = (question or "").strip()
    if q:
        parts.append(f"> **Q:** {q}\n")
    parts.append((answer or "").strip())
    parts.append("\n\n---\n\n*This page was crystallized from a wiki Q&A session.*")
    cleaned = [p.strip() for p in source_paths if p and str(p).strip()]
    seen: set[str] = set()
    uniq: list[str] = []
    for p in cleaned:
        if p in seen:
            continue
        seen.add(p)
        uniq.append(p)
    if uniq:
        parts.append("\n\n## Related wiki pages\n")
        for p in uniq:
            parts.append(f"- `{p}`\n")
    return "".join(parts).strip()


async def crystallize(
    wiki_store: WikiStore,
    repository: str,
    question: str,
    answer: str,
    sources: list[str],
    business_id: str,
) -> dict[str, str]:
    """Create a wiki page from Q&A content, tag it as crystallized, and add reference edges to sources.

    ``sources`` are wiki page paths (``AskSource.wiki_page`` values).

    Returns ``page_uid``, ``title``, and ``path``.
    """
    base = wiki_store._store  # noqa: SLF001 — graph store with ``persist_wiki_pages``
    if not hasattr(base, "persist_wiki_pages"):
        msg = "Graph store does not support persist_wiki_pages"
        raise RuntimeError(msg)

    title = title_from_question(question)
    path = _build_page_path(title)
    content = _build_content(question, answer, list(sources))
    generated_at = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    page_dict: dict[str, object] = {
        "path": path,
        "title": title,
        "content": content,
        "page_type": _SOURCE_ORIGIN_CRYSTALLIZED,
        "generated_at": generated_at,
        "source_origin": _SOURCE_ORIGIN_CRYSTALLIZED,
    }

    await base.persist_wiki_pages(repository, [page_dict])

    page_uid = f"WikiPage:{repository}:{path}"
    source_paths = [str(s).strip() for s in sources if s and str(s).strip()]
    for tgt_path in source_paths:
        if tgt_path == path:
            continue
        target_uid = f"WikiPage:{repository}:{tgt_path}"
        try:
            await wiki_store.add_wiki_reference_edge(
                page_uid,
                target_uid,
                relation_type="crystallized_from",
                context="Q&A crystallization backlink",
                auto_generated=True,
                confidence=1.0,
            )
        except Exception:
            log.warning(
                "crystallize_backlink_skipped",
                repository=repository,
                target_path=tgt_path,
                business_id=business_id,
                exc_info=True,
            )

    log.info(
        "wiki_crystallized",
        repository=repository,
        path=path,
        business_id=business_id,
        source_count=len(source_paths),
    )

    return {"page_uid": page_uid, "title": title, "path": path}
