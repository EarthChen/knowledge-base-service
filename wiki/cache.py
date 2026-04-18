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
            return len(to_remove)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._data)
