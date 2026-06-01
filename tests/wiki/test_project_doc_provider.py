from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_repo(tmp_path: Path) -> Path:
    """Create a fake repo with AGENTS.md."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text("# Project\n\n## Tech Stack\n\nPython, FastAPI\n\n## Modules\n\n- auth\n- user\n")
    return tmp_path


@pytest.fixture
def tmp_repo_with_links(tmp_path: Path) -> Path:
    """Create a fake repo with AGENTS.md that links to sub-docs."""
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "# Project\n\nSee [arch](docs/ARCHITECTURE.md) for details.\n"
    )
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ARCHITECTURE.md").write_text("# Architecture\n\n## Layers\n\nService layer\n")
    return tmp_path


def test_discover_finds_agents_md(tmp_repo: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_repo)})
    assert len(result) == 1
    assert result[0]["repo"] == "test-repo"
    assert result[0]["path"] == "AGENTS.md"
    assert "# Project" in result[0]["lines"][0]
    assert result[0]["total_lines"] >= 5


def test_discover_follows_markdown_links(tmp_repo_with_links: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_repo_with_links)})
    assert len(result) == 2
    paths = [r["path"] for r in result]
    assert "AGENTS.md" in paths
    assert "docs/ARCHITECTURE.md" in paths


def test_discover_empty_repo(tmp_path: Path):
    from wiki.project_doc_provider import discover_project_docs

    result = discover_project_docs({"test-repo": str(tmp_path)})
    assert result == []


def test_discover_respects_line_limit(tmp_path: Path):
    from wiki.project_doc_provider import MAX_MAIN_DOC_LINES, discover_project_docs

    big_file = tmp_path / "AGENTS.md"
    big_file.write_text("\n".join([f"line {i}" for i in range(500)]))
    result = discover_project_docs({"test-repo": str(tmp_path)})
    assert len(result[0]["lines"]) == MAX_MAIN_DOC_LINES


def test_format_for_namer():
    from wiki.project_doc_provider import format_for_namer

    docs = [
        {
            "repo": "r",
            "path": "AGENTS.md",
            "lines": ["# Project", "", "## Modules", "- auth", "- user"],
            "total_lines": 5,
            "priority": 0,
        }
    ]
    result = format_for_namer(docs)
    assert "auth" in result
    assert "user" in result
    assert isinstance(result, str)


def test_format_for_page_agent():
    from wiki.project_doc_provider import format_for_page_agent

    docs = [
        {
            "repo": "r",
            "path": "AGENTS.md",
            "lines": ["# Project", "", "## Modules"],
            "total_lines": 3,
            "priority": 0,
        }
    ]
    result = format_for_page_agent(docs)
    assert "Project Background" in result
    assert isinstance(result, str)


def test_discover_blocks_path_traversal(tmp_path: Path):
    """Linked paths with ../ must not escape repo root."""
    from wiki.project_doc_provider import discover_project_docs

    outside = tmp_path / "outside_secret.md"
    outside.write_text("SECRET DATA")
    repo = tmp_path / "repo"
    repo.mkdir()
    agents = repo / "AGENTS.md"
    agents.write_text("# Proj\n\nSee [leak](../outside_secret.md)\n")
    result = discover_project_docs({"test-repo": str(repo)})
    assert len(result) == 1
    assert result[0]["path"] == "AGENTS.md"
    for doc in result:
        for line in doc.get("lines", []):
            assert "SECRET" not in line


def test_discover_blocks_absolute_path_links(tmp_path: Path):
    """Absolute path links should not be followed."""
    from wiki.project_doc_provider import discover_project_docs

    repo = tmp_path / "repo"
    repo.mkdir()
    agents = repo / "AGENTS.md"
    agents.write_text(f"# Proj\n\nSee [abs]({tmp_path / 'etc.md'})\n")
    (tmp_path / "etc.md").write_text("SENSITIVE")
    result = discover_project_docs({"test-repo": str(repo)})
    assert len(result) == 1
