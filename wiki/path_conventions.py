"""Canonical path format constants for wiki pages."""

import hashlib
import re

DOMAIN_OVERVIEW_PATH_FMT = "/__domains__/{name}/_overview"
DOMAIN_TOPIC_PATH_FMT = "/__domains__/{domain}/{section}/_topic"


def _split_camel_case(s: str) -> str:
    """Split camelCase/PascalCase into kebab-case segments.

    Examples:
        MemberStatisticsAccount → Member-Statistics-Account
        IMOneLink → IM-One-Link
        getUserById → get-User-By-Id
    """
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s)
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1-\2", s)
    return s


def _normalize_slug_core(raw: str) -> str:
    s = raw.strip()
    s = _split_camel_case(s)
    s = s.lower()
    s = re.sub(r"[^a-z0-9\s\-_]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    return s.strip("-")


def normalize_slug(raw: str) -> str:
    """Normalize a raw string into a kebab-case ASCII slug."""
    return _normalize_slug_core(raw) or "unnamed"


def normalize_slug_strict(raw: str) -> str | None:
    """Like normalize_slug but returns None instead of 'unnamed' for empty results."""
    return _normalize_slug_core(raw) or None


def domain_overview_path(name: str) -> str:
    slug = normalize_slug(name) if name else "unnamed"
    return DOMAIN_OVERVIEW_PATH_FMT.format(name=slug)


def _pinyin_slug(text: str) -> str:
    """Convert Chinese text to pinyin-based kebab-case slug."""
    if not re.search(r"[\u4e00-\u9fff]", text):
        return ""
    try:
        from pypinyin import Style, lazy_pinyin

        syllables = lazy_pinyin(text, style=Style.NORMAL)
        raw = "-".join(syllables)
        slug = re.sub(r"[^a-z0-9-]", "", raw.lower())
        slug = re.sub(r"-{2,}", "-", slug).strip("-")
        if len(slug) > 60:
            slug = slug[:60].rsplit("-", 1)[0]
        return slug if len(slug) >= 3 else ""
    except ImportError:
        return ""


def domain_topic_path(domain: str, section: str) -> str:
    slug = normalize_slug_strict(domain) or normalize_slug(domain) if domain else "unnamed"
    section_slug = normalize_slug_strict(section)
    if not section_slug:
        section_slug = _pinyin_slug(section)
    if not section_slug:
        section_slug = f"topic-{hashlib.md5(section.encode()).hexdigest()[:8]}"
    return DOMAIN_TOPIC_PATH_FMT.format(domain=slug, section=section_slug)
