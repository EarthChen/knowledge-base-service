"""Canonical path format constants for wiki pages."""

import re

DOMAIN_OVERVIEW_PATH_FMT = "/__domains__/{name}/_overview"
DOMAIN_TOPIC_PATH_FMT = "/__domains__/{domain}/{section}/_topic"


def normalize_slug(raw: str) -> str:
    """Normalize a raw string into a kebab-case ASCII slug."""
    s = raw.strip().lower()
    s = re.sub(r"[^a-z0-9\s\-_]", "", s)
    s = re.sub(r"[\s_]+", "-", s)
    s = re.sub(r"-{2,}", "-", s)
    s = s.strip("-")
    return s or "unnamed"


def domain_overview_path(name: str) -> str:
    return DOMAIN_OVERVIEW_PATH_FMT.format(name=name)


def domain_topic_path(domain: str, section: str) -> str:
    safe_section = section.replace("/", "_").replace(" ", "_")
    return DOMAIN_TOPIC_PATH_FMT.format(domain=domain, section=safe_section)
