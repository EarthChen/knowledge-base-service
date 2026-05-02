"""Detect affected wiki pages from source code changes."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from core.log import get_logger

log = get_logger(__name__)


@dataclass
class AffectedPageSet:
    page_uids: list[str] = field(default_factory=list)
    affected_entities: list[str] = field(default_factory=list)
    trigger: str = "manual"
    files_changed: list[str] = field(default_factory=list)
    impact_radius: int = 1
    new_files: list[str] = field(default_factory=list)
    deleted_files: list[str] = field(default_factory=list)


@runtime_checkable
class _GraphPort(Protocol):
    async def execute_query(self, cypher: str, params: dict | None = None) -> Any: ...


class ChangeDetector:
    def __init__(self, graph: _GraphPort) -> None:
        self._graph = graph

    @staticmethod
    def _parse_diff_output(diff_output: str) -> list[str]:
        files: list[str] = []
        for line in diff_output.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t", 1)
            if len(parts) == 2:
                files.append(parts[1].strip())
            elif line and not line[0].isalpha():
                files.append(line)
        return files

    async def detect_from_file_list(
        self,
        repository: str,
        changed_files: list[str],
        *,
        trigger: str = "manual",
    ) -> AffectedPageSet:
        if not changed_files:
            return AffectedPageSet(trigger=trigger)

        direct_q = (
            "MATCH (e) WHERE e.file IN $files AND e.repository = $repo "
            "RETURN e.uid AS uid"
        )
        result = await self._graph.execute_query(direct_q, {"files": changed_files, "repo": repository})
        direct_uids = [str(row[0]) for row in (getattr(result, "raw", []) or [])]

        neighbor_uids: list[str] = []
        if direct_uids:
            hop_q = (
                "MATCH (e)-[:CALLS|IMPORTS|CONTAINS*1]-(neighbor) "
                "WHERE e.uid IN $uids RETURN DISTINCT neighbor.uid AS uid"
            )
            hop_result = await self._graph.execute_query(hop_q, {"uids": direct_uids})
            neighbor_uids = [str(row[0]) for row in (getattr(hop_result, "raw", []) or [])]

        all_entity_uids = list(set(direct_uids + neighbor_uids))

        page_uids: list[str] = []
        if all_entity_uids:
            page_q = (
                "MATCH (wp:WikiPage)-[:SOURCE_ENTITY]->(e) "
                "WHERE e.uid IN $uids RETURN DISTINCT wp.uid AS uid"
            )
            page_result = await self._graph.execute_query(page_q, {"uids": all_entity_uids})
            page_uids = [str(row[0]) for row in (getattr(page_result, "raw", []) or [])]

        return AffectedPageSet(
            page_uids=page_uids,
            affected_entities=all_entity_uids,
            trigger=trigger,
            files_changed=changed_files,
        )

    async def detect_from_git_diff(
        self,
        repository: str,
        diff_output: str,
        *,
        trigger: str = "git_push",
    ) -> AffectedPageSet:
        files = self._parse_diff_output(diff_output)
        return await self.detect_from_file_list(repository, files, trigger=trigger)
