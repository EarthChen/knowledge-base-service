# wiki/context_gap.py
"""Unified CONTEXT_GAP detection and cleanup."""
import re

CONTEXT_GAP_RE = re.compile(r"<!--\s*CONTEXT_GAP[\s\S]*?-->")

CONTEXT_GAP_DETECT_RE = re.compile(
    r"<!--\s*CONTEXT_GAP[:\s：]\s*([\s\S]+?)\s*-->",
)


def cleanup_context_gaps(content: str) -> str:
    """Replace all CONTEXT_GAP HTML comments with user-visible info notices."""
    result = CONTEXT_GAP_DETECT_RE.sub(r"> ℹ️ 此处信息待补充: \1", content)
    result = re.sub(r"<!--\s*CONTEXT_GAP\s*-->", "> ℹ️ 此处信息待补充", result)
    return result
