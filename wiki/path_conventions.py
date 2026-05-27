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


_COMMON_ENGLISH_WORDS: frozenset[str] = frozenset({
    "api", "app", "auth", "base", "bulk", "bus", "call", "cash", "chat",
    "code", "core", "crud", "dao", "data", "docs", "enum", "exec",
    "feed", "file", "flow", "form", "gift", "grid", "hook", "http",
    "info", "item", "job", "kit", "lang", "link", "list", "load",
    "lock", "log", "logs", "main", "map", "math", "menu", "mgmt",
    "mock", "mq", "msg", "net", "node", "note", "ops", "orm",
    "page", "path", "perm", "pool", "port", "post", "push", "rank",
    "rate", "rest", "role", "rule", "rpc", "run", "sdk", "send",
    "shop", "sign", "sink", "slot", "sort", "spec", "sql", "stat",
    "step", "sync", "tag", "task", "term", "test", "text", "time",
    "tool", "tree", "type", "unit", "url", "user", "util", "view",
    "vote", "web", "work", "wrap",
})


def is_pinyin_slug(slug: str) -> bool:
    """Detect if a slug looks like pinyin transliteration rather than English semantics.

    Heuristic: 4+ segments where most are 2-4 letter tokens that are NOT common
    English words. Common English words are excluded to avoid false positives
    on slugs like ``user-data-api-core``.
    """
    if not slug or "-" not in slug:
        return False
    segments = slug.split("-")
    if len(segments) < 4:
        return False
    pinyin_like = sum(
        1 for s in segments
        if re.fullmatch(r"[a-z]{2,4}", s) and s not in _COMMON_ENGLISH_WORDS
    )
    return pinyin_like >= 4 and pinyin_like / len(segments) >= 0.8


def domain_topic_path(domain: str, section: str) -> str:
    slug = normalize_slug_strict(domain) or normalize_slug(domain) if domain else "unnamed"
    section_slug = normalize_slug_strict(section)
    if not section_slug:
        section_slug = _pinyin_slug(section)
    if not section_slug:
        section_slug = f"topic-{hashlib.md5(section.encode()).hexdigest()[:8]}"
    return DOMAIN_TOPIC_PATH_FMT.format(domain=slug, section=section_slug)
