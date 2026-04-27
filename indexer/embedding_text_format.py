"""Text formatting for code/doc embeddings (no model / numpy dependencies)."""

from __future__ import annotations

MAX_CODE_SNIPPET_CHARS = 3000


def _smart_truncate(code: str, max_chars: int = MAX_CODE_SNIPPET_CHARS) -> str:
    if len(code) <= max_chars:
        return code
    window_start = max(0, max_chars - 200)
    window = code[window_start:max_chars]
    for pattern in ["\n\n", ";\n", "\n"]:
        idx = window.rfind(pattern)
        if idx >= 0:
            return code[: window_start + idx + len(pattern)]
    return code[:max_chars]


def _format_code_text(
    name: str,
    signature: str,
    docstring: str,
    code_snippet: str,
    business_summary: str = "",
) -> str:
    parts: list[str] = []
    if business_summary:
        parts.append(f"Business: {business_summary}")
    if name:
        parts.append(f"Name: {name}")
    if signature:
        parts.append(f"Signature: {signature}")
    if docstring and not business_summary:
        parts.append(f"Description: {docstring[:500]}")
    if code_snippet:
        parts.append(f"Code: {_smart_truncate(code_snippet)}")
    return "\n".join(parts)


def _format_doc_text(title: str, section: str, content: str, heading_context: str = "") -> str:
    parts = [f"Document: {title}"]
    if section:
        parts.append(f"Section: {section}")
    if heading_context and heading_context != section:
        parts.append(f"Context: {heading_context}")
    parts.append(content)
    return "\n".join(parts)


def doc_dict_for_embedding(
    properties: dict[str, str | int | float | list[str]],
) -> dict[str, str]:
    """Build a ``generate_for_docs`` item dict from a Document node's properties."""
    raw_dt = properties.get("document_title", "")
    if raw_dt:
        title = str(raw_dt)
    else:
        t = properties.get("title", "")
        ts = t if isinstance(t, str) else str(t)
        title = ts.split(" > ", 1)[0] if " > " in ts else ts
    sec = properties.get("section", "")
    body = properties.get("content", "")
    hc = properties.get("heading_context", "")
    return {
        "title": title,
        "section": sec if isinstance(sec, str) else str(sec),
        "content": body if isinstance(body, str) else str(body),
        "heading_context": hc if isinstance(hc, str) else str(hc),
    }
