"""Auto-heal actions for wiki quality maintenance.

Automatic repairs:
- Broken reference cleanup (dangling WIKI_REFERENCES edges)
- Orphan page deprecation (pages with no SOURCE_ENTITY link)

Stale page marking is excluded — stable, rarely-updated documentation
should not be auto-flagged.
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _WikiStorePort(Protocol):
    async def delete_broken_wiki_references(self, repository: str) -> int: ...
    async def deprecate_orphan_wiki_pages(self, repository: str) -> int: ...


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

    async def deprecate_orphan_pages(self, repository: str) -> dict[str, Any]:
        """Mark pages with no source entity link as deprecated."""
        try:
            cnt = await self._store.deprecate_orphan_wiki_pages(repository)
        except Exception:
            log.warning("auto_heal_orphan_deprecation_failed", repository=repository, exc_info=True)
            cnt = 0
        return {"pages_deprecated": cnt}

    async def run_all(self, repository: str) -> dict[str, Any]:
        refs = await self.remove_broken_references(repository)
        orphans = await self.deprecate_orphan_pages(repository)
        return {**refs, **orphans}

    async def heal(self, repository: str) -> dict[str, Any]:
        """Run all auto-heal steps (alias for run_all)."""
        return await self.run_all(repository)
