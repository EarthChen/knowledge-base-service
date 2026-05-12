"""Canonical path format constants for wiki pages."""

DOMAIN_OVERVIEW_PATH_FMT = "/__domains__/{name}/_overview"
DOMAIN_TOPIC_PATH_FMT = "/__domains__/{domain}/{section}/_topic"


def domain_overview_path(name: str) -> str:
    return DOMAIN_OVERVIEW_PATH_FMT.format(name=name)


def domain_topic_path(domain: str, section: str) -> str:
    safe_section = section.replace("/", "_").replace(" ", "_")
    return DOMAIN_TOPIC_PATH_FMT.format(domain=domain, section=safe_section)
