"""Shared FQN (Fully Qualified Name) regex and parsing utilities.

Consolidates duplicate _FQN_RE definitions from traversal_store.py and hybrid_query.py.
"""
from __future__ import annotations

import re

FQN_RE = re.compile(
    r"[a-zA-Z_][\w]*(?:\.[a-zA-Z_][\w]*){2,}"
    r"(?:#[a-zA-Z_][\w]*(?:\([^)]*\))?)?"
)


def is_fqn(text: str) -> bool:
    """Return True if *text* is a valid fully-qualified name."""
    return bool(FQN_RE.fullmatch(text.strip()))


def parse_fqn(raw: str) -> tuple[str, str | None]:
    """Parse user input which may be a simple name or FQN.

    Returns (cleaned_input, simple_name_or_None).
    """
    text = raw.strip()
    if not FQN_RE.fullmatch(text):
        return text, None
    if "#" in text:
        return text, text.rsplit("#", 1)[1].split("(")[0]
    return text, text.rsplit(".", 1)[-1]


def extract_fqns(text: str) -> list[str]:
    """Extract all FQN occurrences from free text, stripping method params."""
    return [m.split("(")[0].strip() for m in FQN_RE.findall(text)]
