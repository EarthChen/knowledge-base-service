"""Canonical path format constants for wiki pages."""

from __future__ import annotations

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


_COMMON_ENGLISH_WORDS: frozenset[str] = frozenset(
    {
        "add",
        "all",
        "api",
        "app",
        "auth",
        "avg",
        "base",
        "bulk",
        "bus",
        "call",
        "cash",
        "cfg",
        "chat",
        "cmd",
        "cnt",
        "code",
        "core",
        "crud",
        "dao",
        "data",
        "del",
        "dev",
        "dns",
        "doc",
        "docs",
        "env",
        "enum",
        "err",
        "exec",
        "feed",
        "file",
        "flow",
        "form",
        "get",
        "gift",
        "grid",
        "hook",
        "http",
        "idx",
        "info",
        "item",
        "job",
        "key",
        "kit",
        "lang",
        "len",
        "lib",
        "link",
        "list",
        "load",
        "lock",
        "log",
        "logs",
        "main",
        "map",
        "math",
        "max",
        "menu",
        "mgmt",
        "min",
        "mock",
        "mq",
        "msg",
        "net",
        "new",
        "node",
        "note",
        "old",
        "ops",
        "orm",
        "page",
        "path",
        "perm",
        "pkg",
        "pod",
        "pool",
        "port",
        "post",
        "put",
        "push",
        "rank",
        "rate",
        "req",
        "res",
        "rest",
        "role",
        "rpc",
        "rule",
        "run",
        "sdk",
        "send",
        "set",
        "shop",
        "sign",
        "sink",
        "slot",
        "sort",
        "spec",
        "sql",
        "src",
        "stat",
        "step",
        "sum",
        "svc",
        "sync",
        "tag",
        "task",
        "tcp",
        "term",
        "test",
        "text",
        "time",
        "tool",
        "tree",
        "type",
        "udp",
        "unit",
        "uri",
        "url",
        "user",
        "util",
        "val",
        "view",
        "vote",
        "web",
        "work",
        "wrap",
    }
)


def is_pinyin_slug(slug: str) -> bool:
    """Detect if a slug looks like pinyin transliteration rather than English semantics.

    Heuristic (F2): 5+ all-lowercase hyphen segments with average segment length < 4.5.
    Falls back to legacy token heuristic for shorter slugs with mostly 2-4 letter tokens.
    """
    if not slug or "-" not in slug:
        return False
    segments = slug.split("-")
    if len(segments) >= 5 and all(re.fullmatch(r"[a-z]+", s) for s in segments):
        avg_len = sum(len(s) for s in segments) / len(segments)
        english_ratio = sum(1 for s in segments if s in _COMMON_ENGLISH_WORDS) / len(segments)
        if english_ratio > 0.4:
            return False
        if avg_len < 4.5:
            return True
    if len(segments) < 4:
        return False
    pinyin_like = sum(1 for s in segments if re.fullmatch(r"[a-z]{2,4}", s) and s not in _COMMON_ENGLISH_WORDS)
    return pinyin_like >= 4 and pinyin_like / len(segments) >= 0.8


_MODULE_PATH_NOISE: frozenset[str] = frozenset(
    {
        "basic",
        "common",
        "core",
        "base",
        "main",
        "impl",
        "internal",
        "default",
        "app",
        "api",
        "util",
        "repo",
        "domain",
        "module",
        "v1",
        "v2",
        "v3",
    }
)

_GLUED_SEGMENT_PREFIXES: tuple[str, ...] = (
    "user",
    "basic",
    "abs",
    "app",
    "base",
    "main",
    "core",
    "impl",
    "internal",
    "default",
)

_SPLIT_DICT: frozenset[str] = frozenset(
    w for w in _COMMON_ENGLISH_WORDS if len(w) >= 4
) | frozenset({
    "relation", "family", "member", "proxy", "service", "management",
    "system", "handler", "controller", "consumer", "provider",
    "wrapper", "factory", "builder", "adapter", "listener",
    "filter", "interceptor", "repository", "mapper", "config",
    "manager", "helper", "closed", "friend", "intimacy",
    "activity", "growth", "execution", "distribution",
    "callback", "handling", "authentication", "privilege",
    "statistics", "account", "payment", "search",
    "message", "notification", "session", "token",
    "event", "queue", "cache", "store", "batch",
    "client", "server", "gateway", "router",
    "parser", "render", "scheduler", "worker",
    "monitor", "report", "export",
})
_MIN_SPLIT_WORD = 4


def _split_glued_segment(segment: str) -> list[str]:
    """Split a glued lowercase segment using greedy longest-match dictionary lookup.

    Only splits segments >= 8 chars that aren't already known words.
    Uses minimum word length 4 to avoid short-word ambiguity.
    """
    if len(segment) < 8 or not segment.isalpha():
        return [segment]
    seg = segment.lower()
    if seg in _SPLIT_DICT:
        return [segment]

    remaining = seg
    parts: list[str] = []
    while remaining:
        matched = False
        for length in range(min(len(remaining), 15), _MIN_SPLIT_WORD - 1, -1):
            prefix = remaining[:length]
            if prefix in _SPLIT_DICT:
                parts.append(prefix)
                remaining = remaining[length:]
                matched = True
                break
        if not matched:
            parts.append(remaining)
            break

    return parts if len(parts) > 1 else [segment]


def _desegment_glued_slug(slug: str) -> str:
    """Apply glued-segment splitting to all segments in a slug."""
    parts: list[str] = []
    for seg in slug.split("-"):
        parts.extend(_split_glued_segment(seg))
    result = "-".join(p for p in parts if p)
    return result if result != slug else slug


def _detect_doubled_repo_prefix(slug: str) -> str | None:
    """Return repo name when slug starts with a doubled prefix (e.g. ``foofoo-...``)."""
    head, _, _ = slug.partition("-")
    candidate = head.lower()
    if len(candidate) < 6:
        return None
    for size in range(3, len(candidate) // 2 + 1):
        prefix = candidate[:size]
        if candidate.startswith(prefix + prefix):
            return prefix
    return None


def _is_module_path_slug(slug: str) -> bool:
    """Detect module-path slugs with duplicated repo prefix and excessive length (F1)."""
    return len(slug) > 30 and _detect_doubled_repo_prefix(slug) is not None


def _expand_glued_segment(segment: str) -> list[str]:
    """Split glued lowercase segments like ``userclosed`` into meaningful parts."""
    seg = segment.lower()
    for prefix in _GLUED_SEGMENT_PREFIXES:
        if seg.startswith(prefix) and len(seg) > len(prefix):
            rest = seg[len(prefix) :]
            if rest and rest.isalpha():
                return [rest]
    return [seg] if seg else []


def _sanitize_module_path_slug(
    slug: str,
    *,
    domain_slug: str = "",
    title: str = "",
    part_index: int = 1,
) -> str:
    """Strip duplicated repo prefix and extract meaningful trailing segments (F1)."""
    prefix = _detect_doubled_repo_prefix(slug)
    if prefix:
        doubled = prefix + prefix
        if slug.lower().startswith(doubled + "-"):
            slug = slug[len(doubled) + 1 :]
        elif slug.lower().startswith(doubled):
            slug = slug[len(doubled) :].lstrip("-")

    expanded: list[str] = []
    for segment in slug.split("-"):
        expanded.extend(_expand_glued_segment(segment))

    meaningful = [s for s in expanded if s and s not in _MODULE_PATH_NOISE]
    if meaningful:
        cleaned = "-".join(meaningful)
        if len(cleaned) >= 8 and not _is_module_path_slug(cleaned):
            return cleaned

    if domain_slug:
        return f"{normalize_slug(domain_slug)}-part-{part_index}"
    if title:
        mapped = _title_to_slug(title, fallback="")
        if mapped:
            return mapped
    return f"part-{part_index}"


def is_slug_too_generic(slug: str, domain_slug: str) -> bool:
    """Return True when slug equals the domain slug or its root word (F4)."""
    slug_norm = normalize_slug(slug)
    domain_norm = normalize_slug(domain_slug)
    if not slug_norm or not domain_norm:
        return False
    if slug_norm == domain_norm:
        return True
    domain_root = domain_norm.split("-")[0]
    return bool(domain_root) and len(domain_root) >= 4 and slug_norm == domain_root


def resolve_slug_collision(slug: str, domain_slug: str, used_slugs: set[str]) -> str:
    """Disambiguate slug collisions by prefixing with domain slug (F3)."""
    if slug not in used_slugs:
        return slug
    domain_prefix = normalize_slug(domain_slug) if domain_slug else ""
    candidate = f"{domain_prefix}-{slug}" if domain_prefix else f"{slug}-2"
    if candidate not in used_slugs:
        return candidate
    counter = 2
    while f"{candidate}-{counter}" in used_slugs:
        counter += 1
    return f"{candidate}-{counter}"


def resolve_topic_slug(
    slug: str,
    title: str,
    *,
    domain_slug: str = "",
    used_slugs: set[str] | None = None,
    part_index: int = 1,
    topic_index: int = 1,
) -> str:
    """Apply F1-F4 slug pipeline fixes and optionally register in *used_slugs*."""
    resolved = normalize_slug_strict(slug) or normalize_slug(slug)

    if _is_module_path_slug(resolved):
        resolved = _sanitize_module_path_slug(
            resolved,
            domain_slug=domain_slug,
            title=title,
            part_index=part_index,
        )
    else:
        resolved = _desegment_glued_slug(resolved)

    if is_pinyin_slug(resolved):
        mapped = _title_to_slug(title, fallback="")
        if mapped and mapped != resolved and not is_pinyin_slug(mapped):
            resolved = mapped
        elif domain_slug:
            resolved = f"{normalize_slug(domain_slug)}-topic-{topic_index}"
        else:
            resolved = f"topic-{topic_index}"

    if domain_slug and is_slug_too_generic(resolved, domain_slug):
        mapped = _title_to_slug(title, fallback="")
        if mapped and not is_slug_too_generic(mapped, domain_slug):
            resolved = mapped
        else:
            domain_part = normalize_slug(domain_slug)
            resolved = f"{domain_part}-topic-{topic_index}"

    if used_slugs is not None:
        resolved = resolve_slug_collision(resolved, domain_slug, used_slugs)
        used_slugs.add(resolved)

    return resolved


_TOPIC_SLUG_MAPPINGS: dict[str, str] = {
    "家族": "family",
    "关系": "relation",
    "任务": "task",
    "消息": "message",
    "用户": "user",
    "管理": "management",
    "系统": "system",
    "执行": "execution",
    "奖励": "reward",
    "亲密": "intimacy",
    "广场": "square",
    "推荐": "recommendation",
    "成员": "member",
    "权益": "privilege",
    "等级": "level",
    "资料": "profile",
    "运营": "operation",
    "活跃": "activity",
    "同步": "sync",
    "处理": "handler",
    "体系": "system",
}

def _title_to_slug(title: str, *, fallback: str = "unnamed") -> str:
    """Convert Chinese title to English slug using dictionary mapping."""
    title = re.sub(r"\s*-\s*Part\s+\d+$", "", title, flags=re.IGNORECASE)
    parts: list[str] = []
    remaining = title
    ordered_terms = sorted(_TOPIC_SLUG_MAPPINGS, key=len, reverse=True)
    while remaining and len(parts) < 4:
        matched = False
        for zh in ordered_terms:
            if not remaining.startswith(zh):
                continue
            en = _TOPIC_SLUG_MAPPINGS[zh]
            if en not in parts:
                parts.append(en)
            remaining = remaining[len(zh) :]
            matched = True
            break
        if not matched:
            remaining = remaining[1:]
    if parts:
        return "-".join(parts[:4])
    return fallback


def _normalize_topic_slug(slug: str, title: str, *, domain_slug: str = "") -> str:
    """Convert pinyin/module-path slugs to semantic English slugs."""
    return resolve_topic_slug(
        slug,
        title,
        domain_slug=domain_slug,
        part_index=1,
        topic_index=1,
    )


def domain_topic_path(domain: str, section: str) -> str:
    slug = normalize_slug_strict(domain) or normalize_slug(domain) if domain else "unnamed"
    section_slug = normalize_slug_strict(section)
    if not section_slug:
        section_slug = _pinyin_slug(section)
    if not section_slug:
        section_slug = f"topic-{hashlib.md5(section.encode()).hexdigest()[:8]}"
    section_slug = _normalize_topic_slug(section_slug, section, domain_slug=slug)
    return DOMAIN_TOPIC_PATH_FMT.format(domain=slug, section=section_slug)
