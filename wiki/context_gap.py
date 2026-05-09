# wiki/context_gap.py
"""Unified CONTEXT_GAP detection and cleanup."""
import re

CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP[\s\S]*?-->")

CONTEXT_GAP_DETECT_RE = re.compile(
    r"<!--\s*CONTEXT_GAP[:\s：]\s*([\s\S]+?)\s*-->",
)

# Non-standard CONTEXT_GAP patterns produced by LLMs (e.g. "⚠️ ** CONTEXT_GAP **：...")
_NONSTANDARD_GAP_RE = re.compile(
    r">\s*⚠️\s*\*{0,2}\s*CONTEXT_GAP\s*\*{0,2}\s*[：:]\s*(.+)",
    re.MULTILINE,
)
_INLINE_GAP_RE = re.compile(
    r"⚠️\s*\*{0,2}\s*CONTEXT_GAP\s*\*{0,2}\s*[：:]\s*(.+)",
)


def cleanup_context_gaps(content: str) -> str:
    """Remove all CONTEXT_GAP markers from wiki content.

    Previously these were converted to visible "此处信息待补充" notices, but that
    leaks internal pipeline artifacts into user-facing content. Now we simply
    strip the markers and any surrounding empty lines.
    """
    result = CONTEXT_GAP_DETECT_RE.sub("", content)
    result = re.sub(r"<!--\s*CONTEXT_GAP\s*-->", "", result)
    result = _NONSTANDARD_GAP_RE.sub("", result)
    result = _INLINE_GAP_RE.sub("", result)
    # Collapse multiple blank lines left by removal
    result = re.sub(r"\n{3,}", "\n\n", result)
    # Removing inline HTML comments often leaves doubled spaces (e.g. "a <!--...--> b").
    # Collapse runs only between non-whitespace so markdown list indentation is preserved.
    result = re.sub(r"(?<=\S)[ \t]{2,}(?=\S)", " ", result)
    return result
