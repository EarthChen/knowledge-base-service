"""P1 in-memory LRU wiki generation cache — Spec §4.17."""

from __future__ import annotations

import threading
from collections import OrderedDict

from wiki.models import WikiPage

CacheKey = tuple[str, str, str, int]


class WikiCache:
    """LRU cache keyed by (repository, scope, mode, graph_version).

    TTL is implicit: callers bump ``graph_version`` when the graph is re-indexed so
    keys naturally miss; ``invalidate(repository)`` clears all entries for a repo.
    """

    def __init__(self, max_size: int = 100) -> None:
        self._max_size = max_size
        self._data: OrderedDict[CacheKey, list[WikiPage]] = OrderedDict()
        self._lock = threading.Lock()
        self._glossary_by_repo: dict[str, dict[str, str]] = {}
        self._aux_pages_by_repo: dict[str, dict[str, WikiPage]] = {}
        self._update_logs_by_repo: dict[str, list[str]] = {}

    @staticmethod
    def _key(repository: str, scope: str, mode: str, graph_version: int) -> CacheKey:
        return (repository, scope, mode, graph_version)

    def get(self, repository: str, scope: str, mode: str, graph_version: int) -> list[WikiPage] | None:
        key = self._key(repository, scope, mode, graph_version)
        with self._lock:
            if key not in self._data:
                return None
            self._data.move_to_end(key)
            # Return a shallow copy so callers cannot mutate stored lists in place.
            return list(self._data[key])

    def put(self, repository: str, scope: str, mode: str, graph_version: int, pages: list[WikiPage]) -> None:
        key = self._key(repository, scope, mode, graph_version)
        with self._lock:
            if key in self._data:
                del self._data[key]
            self._data[key] = pages
            self._data.move_to_end(key)
            while len(self._data) > self._max_size:
                self._data.popitem(last=False)

    def invalidate(self, repository: str) -> int:
        with self._lock:
            to_remove = [k for k in self._data if k[0] == repository]
            for k in to_remove:
                del self._data[k]
            self._aux_pages_by_repo.pop(repository, None)
            return len(to_remove)

    def get_glossary(self, repository: str) -> dict[str, str] | None:
        """Return last stored glossary for drift checks on the next incremental run."""
        with self._lock:
            g = self._glossary_by_repo.get(repository)
            if g is None:
                return None
            return dict(g)

    def set_glossary(self, repository: str, glossary: dict[str, str]) -> None:
        """Persist glossary snapshot (survives ``invalidate`` for page LRU entries)."""
        with self._lock:
            self._glossary_by_repo[repository] = dict(glossary)

    def set_auxiliary_pages(self, repository: str, pages: list[WikiPage]) -> None:
        """Store repo-level wiki pages such as ``index.md`` / ``overview.md``."""
        with self._lock:
            bucket = self._aux_pages_by_repo.setdefault(repository, {})
            for p in pages:
                bucket[p.path] = p

    def get_auxiliary_pages(self, repository: str) -> list[WikiPage]:
        with self._lock:
            bucket = self._aux_pages_by_repo.get(repository)
            if not bucket:
                return []
            return list(bucket.values())

    _MAX_LOG_LINES = 500

    def append_wiki_update_log(self, repository: str, line: str) -> None:
        with self._lock:
            logs = self._update_logs_by_repo.setdefault(repository, [])
            logs.append(line.rstrip("\n"))
            if len(logs) > self._MAX_LOG_LINES:
                del logs[: len(logs) - self._MAX_LOG_LINES]

    def get_wiki_update_log(self, repository: str) -> str:
        with self._lock:
            lines = self._update_logs_by_repo.get(repository, [])
            return "\n".join(lines) + ("\n" if lines else "")

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)

    def list_pages_for_repository(self, repository: str) -> list[WikiPage]:
        """All cached wiki pages for a repository (latest entry wins per path)."""
        merged: dict[str, WikiPage] = {}
        with self._lock:
            for key, pages in self._data.items():
                if key[0] != repository:
                    continue
                for p in pages:
                    merged[p.path] = p
        return list(merged.values())
