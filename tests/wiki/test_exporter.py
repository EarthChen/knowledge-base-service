"""P6 Wiki Export — user-triggered export to repository docs (WikiDocsExporter)."""

from __future__ import annotations

from pathlib import Path

import pytest

from wiki.cache import WikiCache
from wiki.models import PageType, WikiPage, WikiPageMetadata
from wiki.wiki_docs_exporter import WikiDocsExporter


def _page(path: str, content: str = "Body") -> WikiPage:
    return WikiPage(
        path=path,
        title="T",
        page_type=PageType.MODULE_OVERVIEW,
        content=content,
        diagrams=[],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )


@pytest.mark.asyncio
async def test_preview_export_does_not_write_files(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    cache.put(repo, "repo", "structure", 1, [_page("a.md", "Hello")])
    target = tmp_path / "docs"
    target.mkdir()
    out_file = target / "a.md"
    out_file.write_text("SHOULD NOT CHANGE", encoding="utf-8")

    exp = WikiDocsExporter(wiki_cache=cache)
    await exp.preview_export(repo, str(target))

    assert out_file.read_text(encoding="utf-8") == "SHOULD NOT CHANGE"


@pytest.mark.asyncio
async def test_execute_export_writes_only_selected_files(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    cache.put(
        repo,
        "repo",
        "structure",
        1,
        [_page("one.md", "A"), _page("two.md", "B")],
    )
    target = str(tmp_path / "out")
    Path(target).mkdir(parents=True)

    exp = WikiDocsExporter(wiki_cache=cache)
    await exp.execute_export(repo, target, selected_files=["one.md"])

    assert (tmp_path / "out" / "one.md").exists()
    assert not (tmp_path / "out" / "two.md").exists()


@pytest.mark.asyncio
async def test_auto_generated_marker_present(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    cache.put(repo, "repo", "structure", 1, [_page("x.md", "Z")])
    target = str(tmp_path / "d")
    Path(target).mkdir()

    exp = WikiDocsExporter(wiki_cache=cache)
    await exp.execute_export(repo, target, selected_files=["x.md"])
    text = (Path(target) / "x.md").read_text(encoding="utf-8")
    assert WikiDocsExporter.AUTO_GENERATED_MARKER in text


@pytest.mark.asyncio
async def test_human_written_file_skipped(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    cache.put(repo, "repo", "structure", 1, [_page("human.md", "Wiki body")])
    target = str(tmp_path / "docs")
    Path(target).mkdir()
    (Path(target) / "human.md").write_text("# Human\n\nNo marker here.\n", encoding="utf-8")

    exp = WikiDocsExporter(wiki_cache=cache)
    prev = await exp.preview_export(repo, target)
    assert any(d.file_path == "human.md" and d.action == "skip" for d in prev.diffs)
    assert prev.skipped >= 1

    await exp.execute_export(repo, target, selected_files=["human.md"])
    assert "No marker here" in (Path(target) / "human.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_diff_summary_describes_changes(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    cache.put(repo, "repo", "structure", 1, [_page("new.md", "N")])
    target = str(tmp_path / "t")
    Path(target).mkdir()

    exp = WikiDocsExporter(wiki_cache=cache)
    prev = await exp.preview_export(repo, target)
    create = next(d for d in prev.diffs if d.file_path == "new.md")
    assert create.action == "create"
    assert "New" in create.diff_summary or "new" in create.diff_summary.lower()

    marker = WikiDocsExporter.AUTO_GENERATED_MARKER
    wiki_body = _page("upd.md", "V2").to_markdown()
    full_auto = f"{marker}\n\n{wiki_body}"
    (Path(target) / "upd.md").write_text(f"{marker}\n\n{_page('upd.md', 'V1').to_markdown()}", encoding="utf-8")
    cache.put(repo, "repo", "structure", 2, [_page("upd.md", "V2")])

    prev2 = await exp.preview_export(repo, str(target))
    upd = next(d for d in prev2.diffs if d.file_path == "upd.md")
    assert upd.action == "update"
    assert "chang" in upd.diff_summary.lower() or "Content" in upd.diff_summary


@pytest.mark.asyncio
async def test_empty_wiki_returns_empty_result(tmp_path: Path) -> None:
    cache = WikiCache()
    target = str(tmp_path / "e")
    Path(target).mkdir()
    exp = WikiDocsExporter(wiki_cache=cache)
    r = await exp.preview_export("empty-repo", target)
    assert r.total_files == 0
    assert r.diffs == []
    assert r.created == r.updated == r.skipped == 0


@pytest.mark.asyncio
async def test_identical_auto_generated_file_skipped_no_diff_row(tmp_path: Path) -> None:
    cache = WikiCache()
    repo = "r1"
    page = _page("same.md", "Same")
    marker = WikiDocsExporter.AUTO_GENERATED_MARKER
    wiki_content = f"{marker}\n\n{page.to_markdown()}"
    target = str(tmp_path / "s")
    Path(target).mkdir()
    (Path(target) / "same.md").write_text(wiki_content, encoding="utf-8")
    cache.put(repo, "repo", "structure", 1, [page])

    exp = WikiDocsExporter(wiki_cache=cache)
    prev = await exp.preview_export(repo, target)
    assert all(d.file_path != "same.md" for d in prev.diffs)
    assert prev.skipped == 1
    assert prev.created == prev.updated == 0


@pytest.mark.asyncio
async def test_preview_export_runs(tmp_path: Path) -> None:
    cache = WikiCache()
    cache.put("z", "repo", "structure", 1, [_page("p.md")])
    exp = WikiDocsExporter(wiki_cache=cache)
    r = await exp.preview_export("z", str(tmp_path), include_auto_generated_marker=True)
    assert r.total_files == 1
