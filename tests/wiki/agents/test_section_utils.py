from wiki.agents.section_utils import (
    build_context_sections,
    locate_edit_sections,
    reassemble_page,
    split_page_into_sections,
)


def test_split_page_no_headings():
    content = "hello\nworld"
    sections = split_page_into_sections(content)
    assert len(sections) == 1
    assert sections[0].heading == ""
    assert sections[0].body == "hello\nworld"
    assert sections[0].level == 0
    assert sections[0].start_line == 1
    assert sections[0].end_line == 2


def test_split_page_multiple_headings():
    content = "intro line\n\n## First\na\n\n## Second\nb\n"
    sections = split_page_into_sections(content)
    assert len(sections) == 3
    assert sections[0].heading == ""
    assert "intro" in sections[0].body
    assert sections[1].heading == "## First"
    assert sections[1].body.strip() == "a"
    assert sections[2].heading == "## Second"
    assert sections[2].body.strip() == "b"


def test_split_page_heading_levels():
    content = "## L2\nx\n\n### L3\ny\n\n## L2b\nz"
    sections = split_page_into_sections(content)
    assert len(sections) == 3
    assert sections[0].heading == "## L2"
    assert sections[0].level == 2
    assert sections[1].heading == "### L3"
    assert sections[1].level == 3
    assert sections[2].heading == "## L2b"
    assert sections[2].level == 2


def test_locate_edit_sections_keyword_match():
    content = "## Alpha\na\n\n## Module Details\nb\n"
    sections = split_page_into_sections(content)
    idx = locate_edit_sections(sections, "Please expand Module Details")
    assert idx == [1]


def test_locate_edit_sections_no_match_returns_all():
    content = "## Alpha\na\n\n## Beta\nb\n"
    sections = split_page_into_sections(content)
    idx = locate_edit_sections(sections, "zzzxy unmatched")
    assert idx == [0, 1]


def test_reassemble_page():
    content = "preamble\n\n## One\nold1\n\n## Two\nold2\n"
    sections = split_page_into_sections(content)
    out = reassemble_page(sections, {1: "new1"})
    assert "## One" in out
    assert "new1" in out
    assert "old1" not in out
    assert "old2" in out
    assert "preamble" in out


def test_build_context_sections():
    content = "## A\nbody a\n\n## B\nbody b long\n\n## C\nbody c\n\n## D\nd\n"
    sections = split_page_into_sections(content)
    focus = [2]
    focus_texts, adjacent_texts, outline_texts = build_context_sections(
        sections, focus
    )
    assert any("## C" in f and "body c" in f for f in focus_texts)
    assert len(adjacent_texts) == 2
    assert any("## B" in a for a in adjacent_texts)
    assert any("## D" in a for a in adjacent_texts)
    assert "## A" in outline_texts
    assert "## B" not in outline_texts
    assert "## C" not in outline_texts
    assert "## D" not in outline_texts
