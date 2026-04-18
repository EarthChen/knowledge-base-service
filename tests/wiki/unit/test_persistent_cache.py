"""Unit tests for wiki.persistent_cache — two-tier LRU + disk cache."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from wiki.cache import WikiCache
from wiki.models import (
    DiagramType,
    PageType,
    SourceLocation,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)
from wiki.persistent_cache import WikiPersistentCache


def _page(path: str = "p.md", title: str = "T") -> WikiPage:
    return WikiPage(
        path=path,
        title=title,
        page_type=PageType.MODULE_OVERVIEW,
        content="body",
        diagrams=[WikiDiagram(diagram_type=DiagramType.FLOWCHART, content="a", title="")],
        source_locations=[
            SourceLocation(
                file_path="f.py",
                start_line=1,
                end_line=2,
                fqn="m.f",
                repository="myrepo",
            )
        ],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )


class TestWikiPersistentCache:
    def test_file_cache_put_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            pages = [_page()]
            pc.put("myrepo", "repo", "structure", 1, pages)
            out = pc.get("myrepo", "repo", "structure", 1)
            assert out is not None
            assert len(out) == 1
            assert out[0].title == "T"
            assert out[0].source_locations[0].repository == "myrepo"

    def test_file_cache_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            assert pc.get("x", "repo", "structure", 99) is None

    def test_file_cache_version_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            key_path = pc._key_path("r", "repo", "structure", 2)
            key_path.write_text(
                json.dumps(
                    {
                        "repository": "r",
                        "scope": "repo",
                        "mode": "structure",
                        "graph_version": 1,
                        "pages": [_page().to_dict()],
                    }
                ),
                encoding="utf-8",
            )
            assert key_path.exists()
            assert pc.get("r", "repo", "structure", 2) is None
            assert not key_path.exists()

    def test_file_cache_invalidate_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            pc.put("r1", "repo", "structure", 1, [_page()])
            pc.put("r2", "repo", "structure", 1, [_page(title="U")])
            removed = pc.invalidate("r1")
            assert removed >= 1
            assert pc.get("r1", "repo", "structure", 1) is None
            hit = pc.get("r2", "repo", "structure", 1)
            assert hit is not None
            json_files = list(Path(tmp).glob("*.json"))
            assert len(json_files) == 1

    def test_two_tier_memory_then_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            pages = [_page()]
            pc.put("r", "repo", "structure", 1, pages)
            mem.clear()
            out = pc.get("r", "repo", "structure", 1)
            assert out is not None
            assert out[0].title == "T"
            again = mem.get("r", "repo", "structure", 1)
            assert again is not None

    def test_two_tier_memory_first(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            pc.put("r", "repo", "structure", 1, [_page()])
            disk_files = list(Path(tmp).glob("*.json"))

            def boom_loads(*_a: object, **_k: object) -> object:
                raise AssertionError("disk JSON should not load on memory hit")

            monkeypatch.setattr("wiki.persistent_cache.json.loads", boom_loads)
            out = pc.get("r", "repo", "structure", 1)
            assert out is not None
            assert out[0].title == "T"
            assert len(disk_files) == 1

    def test_disk_eviction_by_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=500)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=1)
            fat = "x" * (600 * 1024)
            big_page = WikiPage(
                path="big.md",
                title="Big",
                page_type=PageType.MODULE_OVERVIEW,
                content=fat,
                diagrams=[],
                source_locations=[],
                metadata=WikiPageMetadata(node_count=1, edge_count=0),
            )
            pc.put("a", "repo", "structure", 1, [big_page])
            pc.put("b", "repo", "structure", 1, [big_page])
            assert pc.disk_size_mb() <= 1.0 + 0.05

    def test_disk_size_mb(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            Path(tmp, "manual.json").write_text("{}" * 5000, encoding="utf-8")
            sz = pc.disk_size_mb()
            assert sz > 0

    def test_from_dict_roundtrip(self) -> None:
        page = _page()
        back = WikiPage.from_dict(page.to_dict())
        assert back == page

    def test_disk_corrupt_json_removed_on_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            path = pc._key_path("r", "repo", "structure", 1)
            path.write_text("not-json{{{", encoding="utf-8")
            assert pc.get("r", "repo", "structure", 1) is None
            assert not path.exists()

    def test_disk_invalid_payload_removed_on_get(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            path = pc._key_path("r", "repo", "structure", 1)
            path.write_text(
                json.dumps(
                    {
                        "repository": "r",
                        "scope": "repo",
                        "mode": "structure",
                        "graph_version": 1,
                        "pages": [{"oops": True}],
                    }
                ),
                encoding="utf-8",
            )
            assert pc.get("r", "repo", "structure", 1) is None
            assert not path.exists()

    def test_invalidate_removes_corrupt_disk_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = WikiCache(max_size=100)
            pc = WikiPersistentCache(mem, cache_dir=tmp, max_disk_mb=500)
            junk = Path(tmp) / "junk.json"
            junk.write_text("bad", encoding="utf-8")
            pc.invalidate("any")
            assert not junk.exists()

