"""Auto-heal actions for wiki quality maintenance.

Only safe, non-destructive repairs are performed automatically:
- Broken reference cleanup (dangling WIKI_REFERENCES edges)

Page-level operations (stale marking, orphan deprecation) are intentionally
excluded from automatic healing — they should only be triggered manually
during explicit maintenance windows.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _WikiStorePort(Protocol):
    async def delete_broken_wiki_references(self, repository: str) -> int: ...


class AutoHealer:
    def __init__(self, wiki_store: _WikiStorePort) -> None:
        self._store = wiki_store

    async def remove_broken_references(self, repository: str) -> dict[str, Any]:
        try:
            cnt = await self._store.delete_broken_wiki_references(repository)
        except Exception:
            log.warning("auto_heal_broken_refs_failed", repository=repository, exc_info=True)
            cnt = 0
        return {"refs_removed": cnt}

    async def run_all(self, repository: str) -> dict[str, Any]:
        refs = await self.remove_broken_references(repository)
        return {**refs}
