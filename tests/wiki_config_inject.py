"""Reusable app config slices for constructing wiki services in tests."""

from __future__ import annotations

from core.config import AppWikiFlags, EmbeddingConfig, Settings


def inject_wiki_embedding() -> tuple[AppWikiFlags, EmbeddingConfig]:
    from core.config import get_settings

    s: Settings = get_settings()
    return s.wiki, s.embedding


def wiki_service_injection() -> dict[str, object]:
    w, e = inject_wiki_embedding()
    return {"wiki_config": w, "embedding_config": e}
