"""Two-tier wiki cache: in-memory LRU plus JSON files on disk."""

from __future__ import annotations

import hashlib
import json
import threading
from pathlib import Path

from wiki.cache import WikiCache
from wiki.models import WikiPage


class WikiPersistentCache:
    """Two-tier cache: Memory LRU (P1) + file-based persistence (P2)."""

    def __init__(
        self,
        memory_cache: WikiCache,
        cache_dir: str = ".wiki_cache",
        max_disk_mb: int = 500,
    ) -> None:
        self._memory = memory_cache
        self._dir = Path(cache_dir)
        self._max_disk_mb = max_disk_mb
        self._dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _key_path(self, repo: str, scope: str, mode: str, version: int) -> Path:
        key = f"{repo}__{scope}__{mode}__{version}"
        digest = hashlib.sha256(key.encode()).hexdigest()[:16]
        return self._dir / f"{digest}.json"

    def get(
        self,
        repository: str,
        scope: str,
        mode: str,
        graph_version: int,
    ) -> list[WikiPage] | None:
        """Return cached pages from memory, else load from disk into memory."""
        with self._lock:
            hit = self._memory.get(repository, scope, mode, graph_version)
            if hit is not None:
                return hit

            path = self._key_path(repository, scope, mode, graph_version)
            if not path.is_file():
                return None

            try:
                raw = path.read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, json.JSONDecodeError):
                path.unlink(missing_ok=True)
                return None

            if payload.get("graph_version") != graph_version:
                path.unlink(missing_ok=True)
                return None

            try:
                pages = [WikiPage.from_dict(p) for p in payload["pages"]]
            except (KeyError, TypeError, ValueError):
                path.unlink(missing_ok=True)
                return None

            self._memory.put(repository, scope, mode, graph_version, pages)
            return list(self._memory.get(repository, scope, mode, graph_version) or pages)

    def put(
        self,
        repository: str,
        scope: str,
        mode: str,
        graph_version: int,
        pages: list[WikiPage],
    ) -> None:
        """Store pages in memory and persist JSON to disk."""
        with self._lock:
            self._memory.put(repository, scope, mode, graph_version, pages)
            payload = {
                "repository": repository,
                "scope": scope,
                "mode": mode,
                "graph_version": graph_version,
                "pages": [p.to_dict() for p in pages],
            }
            path = self._key_path(repository, scope, mode, graph_version)
            path.write_text(json.dumps(payload), encoding="utf-8")
            self._evict_oldest_if_needed()

    def invalidate(self, repository: str) -> int:
        """Drop all cache entries for ``repository`` (memory + disk files)."""
        with self._lock:
            removed_mem = self._memory.invalidate(repository)
            for path in list(self._dir.glob("*.json")):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    path.unlink(missing_ok=True)
                    continue
                if data.get("repository") == repository:
                    path.unlink(missing_ok=True)
            return removed_mem

    def _disk_bytes(self) -> int:
        return sum(p.stat().st_size for p in self._dir.glob("*.json") if p.is_file())

    def _evict_oldest_if_needed(self) -> None:
        """LRU eviction by file mtime when disk exceeds ``max_disk_mb``."""
        max_bytes = self._max_disk_mb * 1024 * 1024
        while self._disk_bytes() > max_bytes:
            files = [p for p in self._dir.glob("*.json") if p.is_file()]
            if not files:
                break
            oldest = min(files, key=lambda p: p.stat().st_mtime)
            oldest.unlink(missing_ok=True)

    def disk_size_mb(self) -> float:
        """Return current disk cache size in MB."""
        return self._disk_bytes() / (1024 * 1024)
