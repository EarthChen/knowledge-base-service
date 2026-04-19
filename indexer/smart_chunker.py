"""Smart markdown chunker with break-point scoring and overlap.

Splits markdown documents at natural boundaries (headings, code fences,
horizontal rules) rather than arbitrary character positions, preserving
semantic coherence within each chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

BREAK_SCORES: dict[str, int] = {
    "h1": 100,
    "h2": 90,
    "h3": 80,
    "h4": 70,
    "code_fence": 80,
    "hr": 60,
    "blank_line": 20,
    "list_item": 5,
    "line_break": 1,
}

TARGET_CHARS = 3600  # ~900 tokens × 4 chars/token
OVERLAP_RATIO = 0.15
MIN_CHUNK_CHARS = 200


@dataclass
class Chunk:
    """A chunk of text with metadata."""

    text: str
    start_line: int
    end_line: int
    heading_context: str = ""


def _classify_line(line: str) -> tuple[str, int]:
    """Classify a line and return (break_type, score)."""
    stripped = line.strip()
    if not stripped:
        return "blank_line", BREAK_SCORES["blank_line"]
    if stripped.startswith("# "):
        return "h1", BREAK_SCORES["h1"]
    if stripped.startswith("## "):
        return "h2", BREAK_SCORES["h2"]
    if stripped.startswith("### "):
        return "h3", BREAK_SCORES["h3"]
    if stripped.startswith("#### "):
        return "h4", BREAK_SCORES["h4"]
    if stripped.startswith("```"):
        return "code_fence", BREAK_SCORES["code_fence"]
    if re.match(r"^---+\s*$", stripped):
        return "hr", BREAK_SCORES["hr"]
    if re.match(r"^[-*+]\s", stripped) or re.match(r"^\d+\.\s", stripped):
        return "list_item", BREAK_SCORES["list_item"]
    return "line_break", BREAK_SCORES["line_break"]


def _segment_end_line(segment_text: str, segment_start_line: int) -> int:
    """Last 0-based line index covered by a merged segment."""
    return segment_start_line + segment_text.count("\n")


def smart_chunk_markdown(
    text: str,
    *,
    target_chars: int = TARGET_CHARS,
    overlap_ratio: float = OVERLAP_RATIO,
    min_chunk_chars: int = MIN_CHUNK_CHARS,
) -> list[Chunk]:
    """Chunk markdown with smart break-point scoring and overlap.

    Returns a list of Chunk objects. Code blocks (``` ... ```) are never
    split across chunks.
    """
    if not text or not text.strip():
        return []

    lines = text.split("\n")
    if not lines:
        return []

    # Pre-process: merge code blocks into single "lines" to prevent splitting
    merged_lines: list[tuple[str, int]] = []  # (text, original_start_line)
    i = 0
    while i < len(lines):
        if lines[i].strip().startswith("```"):
            # Find closing fence
            block_lines = [lines[i]]
            start = i
            i += 1
            while i < len(lines):
                block_lines.append(lines[i])
                if lines[i].strip().startswith("```") and i != start:
                    i += 1
                    break
                i += 1
            merged_lines.append(("\n".join(block_lines), start))
        else:
            merged_lines.append((lines[i], i))
            i += 1

    chunks: list[Chunk] = []
    current_indices: list[int] = []
    current_lines: list[str] = []
    current_heading = ""

    def _chunk_char_len(lines_list: list[str]) -> int:
        return len("\n".join(lines_list)) if lines_list else 0

    for seg_idx, (line_text, orig_line_no) in enumerate(merged_lines):
        first_physical = line_text.split("\n")[0] if "\n" in line_text else line_text
        line_type, score = _classify_line(first_physical)

        is_heading = line_type in ("h1", "h2", "h3", "h4")
        next_heading = line_text.strip().lstrip("#").strip() if is_heading else None

        prospective = current_lines + [line_text]
        prospective_chars = _chunk_char_len(prospective)
        current_chars = _chunk_char_len(current_lines)

        if prospective_chars > target_chars and current_chars >= min_chunk_chars:
            if score >= BREAK_SCORES["blank_line"]:
                chunk_text = "\n".join(current_lines)
                if chunk_text.strip():
                    last_idx = current_indices[-1]
                    last_text, last_start = merged_lines[last_idx]
                    end_ln = _segment_end_line(last_text, last_start)
                    first_idx = current_indices[0]
                    start_ln = merged_lines[first_idx][1]
                    chunks.append(
                        Chunk(
                            text=chunk_text,
                            start_line=start_ln,
                            end_line=end_ln,
                            heading_context=current_heading,
                        )
                    )

                if next_heading is not None:
                    current_heading = next_heading

                overlap_chars = int(current_chars * overlap_ratio)
                overlap_lines: list[str] = []
                overlap_indices: list[int] = []
                for prev_idx, prev_line in zip(reversed(current_indices), reversed(current_lines)):
                    trial = [prev_line] + overlap_lines
                    if _chunk_char_len(trial) > overlap_chars and overlap_lines:
                        break
                    overlap_lines.insert(0, prev_line)
                    overlap_indices.insert(0, prev_idx)

                current_lines = overlap_lines + [line_text]
                current_indices = overlap_indices + [seg_idx]
                continue

        if next_heading is not None:
            current_heading = next_heading

        current_lines.append(line_text)
        current_indices.append(seg_idx)

    # Emit remaining content
    if current_lines:
        chunk_text = "\n".join(current_lines)
        if chunk_text.strip():
            first_idx = current_indices[0]
            last_idx = current_indices[-1]
            start_ln = merged_lines[first_idx][1]
            last_text, last_start = merged_lines[last_idx]
            end_ln = _segment_end_line(last_text, last_start)
            chunks.append(
                Chunk(
                    text=chunk_text,
                    start_line=start_ln,
                    end_line=end_ln,
                    heading_context=current_heading,
                )
            )

    return chunks
