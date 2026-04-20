"""Repository registry — maps git URLs to canonical repository names.

Prevents the same repository from being indexed under multiple names.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from log import get_logger

log = get_logger(__name__)


class RepoRegistry:
    """Persistent mapping of git URL → repository metadata."""

    def __init__(self, data_dir: str = "./data") -> None:
        self._path = Path(data_dir) / "repo_registry.json"
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            log.warning("repo_registry_read_failed", path=str(self._path), error=str(exc))
            return
        if not raw.strip():
            return
        try:
            loaded = json.loads(raw)
        except json.JSONDecodeError as exc:
            log.warning("repo_registry_json_invalid", path=str(self._path), error=str(exc))
            return
        if isinstance(loaded, dict):
            self._data = loaded
        else:
            log.warning("repo_registry_json_not_object", path=str(self._path))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(self._data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    def get_canonical_name(self, git_url: str) -> str | None:
        """Return the repository name previously used for this URL, or None."""
        key = self._normalize_key(git_url)
        entry = self._data.get(key)
        if not entry:
            return None
        repo = entry.get("repository")
        return str(repo) if repo is not None else None

    def register(self, git_url: str, repository: str) -> None:
        """Register or update a URL → repository mapping."""
        key = self._normalize_key(git_url)
        now = datetime.now(UTC).isoformat()
        prev = self._data.get(key, {})
        self._data[key] = {
            "repository": repository,
            "git_url": git_url,
            "last_indexed": now,
            "first_registered": prev.get("first_registered", now),
        }
        self._save()

    def list_all(self) -> list[dict[str, Any]]:
        return list(self._data.values())

    def get_git_url_for_repository(self, repository: str) -> str | None:
        """Return a registered git URL for the canonical graph ``repository`` name, if any."""
        target = repository.strip()
        if not target:
            return None
        for entry in self._data.values():
            if str(entry.get("repository") or "") != target:
                continue
            url = entry.get("git_url")
            if url:
                return str(url).strip()
        return None

    def remove(self, git_url: str) -> None:
        key = self._normalize_key(git_url)
        self._data.pop(key, None)
        self._save()

    @staticmethod
    def _normalize_key(git_url: str) -> str:
        """Strip .git suffix and trailing slashes for consistent matching."""
        url = git_url.strip().rstrip("/")
        if url.endswith(".git"):
            url = url[:-4]
        return url
