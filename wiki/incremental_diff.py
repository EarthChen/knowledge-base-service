"""Graph diff computation for incremental wiki updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from log import get_logger

log = get_logger(__name__)


def _first_column_values(result: Any) -> list[Any]:
    """Extract first column from FalkorDB ``QueryResultWrapper`` or test mocks.

    Real results use ``raw`` (positional rows). ``data`` may be dict rows or
    list rows depending on the caller.
    """
    raw = getattr(result, "raw", None) or getattr(result, "result_set", None)
    if raw:
        return [row[0] for row in raw if row]
    rows = getattr(result, "data", None) or []
    out: list[Any] = []
    for row in rows:
        if isinstance(row, dict):
            if row:
                out.append(next(iter(row.values())))
        elif row:
            out.append(row[0])
    return out


@dataclass
class WikiDiff:
    changed_uids: set[str]
    affected_parents: set[str]
    affected_communities: set[int] = field(default_factory=set)

    @property
    def is_empty(self) -> bool:
        return not self.changed_uids and not self.affected_parents

    @property
    def total_affected(self) -> int:
        return len(self.changed_uids) + len(self.affected_parents)


async def compute_wiki_diff(store: Any, repository: str, since_version: int) -> WikiDiff:
    """Compare current graph state with last wiki generation to find affected entities."""
    _ = since_version  # reserved for changelog / version-scoped diff (Phase 3+)

    changed_result = await store.execute_query(
        "MATCH (n {repository: $repo}) "
        "WHERE n.code_hash IS NOT NULL AND "
        "      (n.wiki_code_hash IS NULL OR n.code_hash <> n.wiki_code_hash) "
        "RETURN n.uid",
        {"repo": repository},
    )
    changed_uids = {v for v in _first_column_values(changed_result) if v}

    if not changed_uids:
        log.info("incremental_diff_no_changes", repository=repository)
        return WikiDiff(set(), set())

    ancestors_result = await store.execute_query(
        "MATCH (parent)-[:CONTAINS*1..10]->(child) "
        "WHERE child.uid IN $uids AND parent.repository = $repo "
        "RETURN DISTINCT parent.uid",
        {"repo": repository, "uids": list(changed_uids)},
    )
    affected_parents = {v for v in _first_column_values(ancestors_result) if v}

    community_result = await store.execute_query(
        "MATCH (n)-[:BELONGS_TO]->(c:Community) "
        "WHERE n.uid IN $uids AND n.repository = $repo "
        "RETURN DISTINCT c.community_id",
        {"repo": repository, "uids": list(changed_uids)},
    )
    affected_communities = {
        int(v) for v in _first_column_values(community_result) if v is not None
    }

    log.info(
        "incremental_diff_computed",
        repository=repository,
        changed=len(changed_uids),
        parents=len(affected_parents),
        communities=len(affected_communities),
    )
    return WikiDiff(changed_uids, affected_parents, affected_communities)
