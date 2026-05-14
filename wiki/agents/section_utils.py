"""Markdown section splitting and context tiering for wiki edit agent."""

from __future__ import annotations

import re
from dataclasses import dataclass

_HEADING = re.compile(r"^(#{2,3})(\s+.*)$")


@dataclass
class Section:
    heading: str
    body: str
    start_line: int
    end_line: int
    level: int


def _heading_level(line: str) -> int | None:
    m = _HEADING.match(line)
    if not m:
        return None
    return len(m.group(1))


def split_page_into_sections(content: str) -> list[Section]:
    """Split markdown by ## and ### headings.

    If there are no ##/### headings, returns one section for the whole page.
    Lines before the first heading use heading=\"\" and level=0.
    """
    if not content:
        return [Section(heading="", body="", start_line=1, end_line=1, level=0)]

    lines = content.split("\n")
    # First heading line (0-based)
    first_h = None
    for j, line in enumerate(lines):
        lev = _heading_level(line)
        if lev is not None:
            first_h = j
            break

    if first_h is None:
        return [
            Section(
                heading="",
                body=content,
                start_line=1,
                end_line=len(lines),
                level=0,
            )
        ]

    sections: list[Section] = []
    if first_h > 0:
        preamble = "\n".join(lines[:first_h])
        sections.append(
            Section(
                heading="",
                body=preamble,
                start_line=1,
                end_line=first_h,
                level=0,
            )
        )

    i = first_h
    while i < len(lines):
        line = lines[i]
        lev = _heading_level(line)
        if lev is None:
            i += 1
            continue
        heading = line
        level = lev
        start_line = i + 1
        i += 1
        body_start = i
        while i < len(lines):
            if _heading_level(lines[i]) is not None:
                break
            i += 1
        body = "\n".join(lines[body_start:i])
        end_line = i if body_start < i else start_line
        sections.append(Section(heading=heading, body=body, start_line=start_line, end_line=end_line, level=level))
    return sections


def _prompt_words(prompt: str) -> set[str]:
    return {w.lower() for w in re.findall(r"[A-Za-z0-9_]+", prompt)}


def locate_edit_sections(sections: list[Section], user_prompt: str) -> list[int]:
    """Return indices whose headings match tokens in ``user_prompt``; else all."""
    pw = _prompt_words(user_prompt)
    if not pw:
        return list(range(len(sections)))

    matched: list[int] = []
    for idx, sec in enumerate(sections):
        heading_words = _prompt_words(sec.heading)
        if pw & heading_words:
            matched.append(idx)
    if not matched:
        return list(range(len(sections)))
    return matched


def reassemble_page(sections: list[Section], edited_sections: dict[int, str]) -> str:
    blocks: list[str] = []
    for i, sec in enumerate(sections):
        body = edited_sections[i] if i in edited_sections else sec.body
        if sec.heading:
            blocks.append(sec.heading if not body else f"{sec.heading}\n{body}")
        elif body:
            blocks.append(body)
    return "\n\n".join(blocks)


def build_context_sections(
    sections: list[Section],
    focus_indices: list[int],
) -> tuple[list[str], list[str], list[str]]:
    focus_set = set(focus_indices)
    adjacent_set: set[int] = set()
    for idx in focus_indices:
        if idx > 0:
            adjacent_set.add(idx - 1)
        if idx + 1 < len(sections):
            adjacent_set.add(idx + 1)
    adjacent_set -= focus_set

    def format_focus(sec: Section) -> str:
        if sec.heading:
            return f"{sec.heading}\n{sec.body}" if sec.body else sec.heading
        return sec.body

    def format_adjacent(sec: Section) -> str:
        snippet = (sec.body or "")[:200]
        if sec.heading:
            return f"{sec.heading}\n{snippet}" if snippet else sec.heading
        return snippet

    focus_texts = [format_focus(sections[i]) for i in sorted(focus_set)]
    adjacent_texts = [format_adjacent(sections[j]) for j in sorted(adjacent_set)]

    outline_texts: list[str] = []
    for i, sec in enumerate(sections):
        if i in focus_set or i in adjacent_set:
            continue
        outline_texts.append(sec.heading)
    return focus_texts, adjacent_texts, outline_texts
