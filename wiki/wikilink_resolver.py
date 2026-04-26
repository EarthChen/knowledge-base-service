"""Post-process [[wikilinks]] in generated wiki content."""
from __future__ import annotations

import re

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def resolve_wikilinks(content: str, entity_index: dict[str, str]) -> str:
    """Replace [[EntityName]] with markdown links if entity is known, else plain text."""
    if not content:
        return content

    def _replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        path = entity_index.get(name)
        if path:
            return f"[{name}]({path})"
        return name  # Remove brackets, keep name

    return _WIKILINK_RE.sub(_replace, content)
