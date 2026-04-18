"""Unit tests for wiki.cache.WikiCache — P1 LRU cache."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from wiki.cache import WikiCache
from wiki.models import (
    DiagramType,
    PageType,
    WikiDiagram,
    WikiPage,
    WikiPageMetadata,
)


def _sample_page(_repository: str, suffix: str = "") -> WikiPage:
    return WikiPage(
        path=f"p{suffix}.md",
        title=f"T{suffix}",
        page_type=PageType.MODULE_OVERVIEW,
        content="x",
        diagrams=[WikiDiagram(diagram_type=DiagramType.FLOWCHART, content="a", title="")],
        source_locations=[],
        metadata=WikiPageMetadata(node_count=1, edge_count=0),
    )


class TestWikiCache:
    def test_cache_hit(self) -> None:
        c = WikiCache(max_size=100)
        pages = [_sample_page("r")]
        c.put("r", "repo", "structure", 1, pages)
        out = c.get("r", "repo", "structure", 1)
        assert out is not None
        assert len(out) == 1
        assert out[0].title == "T"
        again = c.get("r", "repo", "structure", 1)
        assert again is not None
        assert again[0].title == "T"

    def test_cache_put_overwrites_same_key(self) -> None:
        c = WikiCache(max_size=100)
        c.put("r", "repo", "structure", 1, [_sample_page("r", "a")])
        c.put("r", "repo", "structure", 1, [_sample_page("r", "b")])
        assert c.size == 1
        assert c.get("r", "repo", "structure", 1) is not None
        assert c.get("r", "repo", "structure", 1)[0].title == "Tb"

    def test_cache_miss_different_scope(self) -> None:
        c = WikiCache(max_size=100)
        c.put("r", "repo", "structure", 1, [_sample_page("r")])
        assert c.get("r", "module:x", "structure", 1) is None

    def test_cache_miss_different_mode(self) -> None:
        c = WikiCache(max_size=100)
        c.put("r", "repo", "structure", 1, [_sample_page("r")])
        assert c.get("r", "repo", "full", 1) is None

    def test_cache_invalidation_on_reindex(self) -> None:
        c = WikiCache(max_size=100)
        c.put("r1", "repo", "structure", 1, [_sample_page("r1", "a")])
        c.put("r2", "repo", "structure", 1, [_sample_page("r2", "b")])
        removed = c.invalidate("r1")
        assert removed == 1
        assert c.get("r1", "repo", "structure", 1) is None
        assert c.get("r2", "repo", "structure", 1) is not None

    def test_cache_lru_eviction(self) -> None:
        c = WikiCache(max_size=100)
        for i in range(101):
            c.put("r", f"k{i}", "structure", 1, [_sample_page("r", str(i))])
        assert c.size == 100
        assert c.get("r", "k0", "structure", 1) is None
        assert c.get("r", "k100", "structure", 1) is not None

    def test_cache_key_composition(self) -> None:
        """Changing any of repository / scope / mode / graph_version must miss."""
        c = WikiCache(max_size=100)
        c.put("repo-a", "repo", "structure", 7, [_sample_page("x")])
        assert c.get("repo-b", "repo", "structure", 7) is None
        assert c.get("repo-a", "module:x", "structure", 7) is None
        assert c.get("repo-a", "repo", "full", 7) is None
        assert c.get("repo-a", "repo", "structure", 8) is None
        hit = c.get("repo-a", "repo", "structure", 7)
        assert hit is not None

    def test_cache_concurrent_access(self) -> None:
        c = WikiCache(max_size=200)
        errors: list[BaseException] = []
        barrier = threading.Barrier(20)

        def worker(i: int) -> None:
            try:
                barrier.wait()
                for _ in range(50):
                    c.put(f"r{i % 5}", "repo", "structure", i % 3, [_sample_page("r")])
                    c.get(f"r{i % 5}", "repo", "structure", i % 3)
                    c.invalidate(f"r{i % 5}")
                c.clear()
            except BaseException as exc:  # noqa: BLE001
                errors.append(exc)

        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(worker, i) for i in range(20)]
            for f in as_completed(futures):
                f.result()
        assert not errors
