"""Sliding-window child chunker for parent-child RAG strategy.

Splits large code entities (functions, classes) and document sections
into smaller overlapping chunks.  Each child chunk is prefixed with
the parent's signature so the embedding carries entity context.

Window / stride / threshold are configurable and default to values
that produce ~200-token chunks with 25 % overlap.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_WINDOW_CHARS = 800   # ~200 tokens
DEFAULT_STRIDE_CHARS = 600   # ~150 tokens → 25% overlap
DEFAULT_MIN_PARENT_CHARS = 400  # skip entities smaller than ~100 tokens


@dataclass(frozen=True, slots=True)
class ChildChunk:
    """Immutable representation of a child chunk before graph ingestion."""

    text: str
    chunk_index: int
    start_line: int
    end_line: int


def chunk_code_entity(
    code_snippet: str,
    signature: str,
    entity_name: str,
    start_line: int,
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    stride_chars: int = DEFAULT_STRIDE_CHARS,
    min_parent_chars: int = DEFAULT_MIN_PARENT_CHARS,
) -> list[ChildChunk]:
    """Create overlapping child chunks from a code entity.

    Returns an empty list when the entity is too small to benefit from
    sub-chunking.
    """
    if len(code_snippet) < min_parent_chars:
        return []

    prefix = f"// In {entity_name}: {signature}\n"
    return _sliding_window(
        text=code_snippet,
        prefix=prefix,
        base_start_line=start_line,
        window_chars=window_chars,
        stride_chars=stride_chars,
    )


def chunk_document_section(
    content: str,
    section_title: str,
    doc_title: str,
    start_line: int,
    *,
    window_chars: int = DEFAULT_WINDOW_CHARS,
    stride_chars: int = DEFAULT_STRIDE_CHARS,
    min_parent_chars: int = DEFAULT_MIN_PARENT_CHARS,
) -> list[ChildChunk]:
    """Create overlapping child chunks from a document section."""
    if len(content) < min_parent_chars:
        return []

    prefix = f"// In {doc_title} > {section_title}\n"
    return _sliding_window(
        text=content,
        prefix=prefix,
        base_start_line=start_line,
        window_chars=window_chars,
        stride_chars=stride_chars,
    )


def _sliding_window(
    text: str,
    prefix: str,
    base_start_line: int,
    window_chars: int,
    stride_chars: int,
) -> list[ChildChunk]:
    """Line-boundary-aware sliding window over *text*.

    Each emitted chunk is ``prefix + window_lines``.
    The window advances by *stride_chars* worth of lines.
    """
    lines = text.split("\n")

    line_char_offsets: list[int] = []
    offset = 0
    for line in lines:
        line_char_offsets.append(offset)
        offset += len(line) + 1  # +1 for the newline

    total_chars = offset - 1 if lines else 0
    if total_chars <= 0:
        return []

    chunks: list[ChildChunk] = []
    chunk_index = 0
    win_start_char = 0

    while win_start_char < total_chars:
        win_end_char = min(win_start_char + window_chars, total_chars)

        first_line_idx = _find_line_at_offset(line_char_offsets, win_start_char)
        last_line_idx = _find_line_at_offset(line_char_offsets, win_end_char - 1) if win_end_char > win_start_char else first_line_idx
        last_line_idx = min(last_line_idx, len(lines) - 1)

        window_lines = lines[first_line_idx : last_line_idx + 1]
        chunk_text = prefix + "\n".join(window_lines)

        chunks.append(ChildChunk(
            text=chunk_text,
            chunk_index=chunk_index,
            start_line=base_start_line + first_line_idx,
            end_line=base_start_line + last_line_idx,
        ))
        chunk_index += 1

        next_start = win_start_char + stride_chars
        if next_start >= total_chars:
            break
        if next_start <= win_start_char:
            break
        win_start_char = next_start

    return chunks


def _find_line_at_offset(line_char_offsets: list[int], char_offset: int) -> int:
    """Binary-search for the line index containing *char_offset*."""
    lo, hi = 0, len(line_char_offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_char_offsets[mid] <= char_offset:
            lo = mid
        else:
            hi = mid - 1
    return lo
