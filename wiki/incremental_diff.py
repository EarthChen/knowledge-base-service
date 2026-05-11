"""Graph diff computation for incremental wiki updates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)


def _query_dict_rows(result: Any) -> list[dict[str, Any]]:
    """Named rows from FalkorDB ``QueryResultWrapper`` or test mocks.

    Prefer ``data`` (dict rows); fall back to ``result_set`` / ``raw`` positional rows.
    """
    rows = getattr(result, "data", None)
    if rows is None:
        raw = getattr(result, "result_set", None) or getattr(result, "raw", None)
        rows = list(raw) if raw else []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(row)
        elif row:
            out.append(
                {
                    "uid": row[0],
                    "name": row[1] if len(row) > 1 else "",
                    "domain": row[2] if len(row) > 2 else "",
                },
            )
    return out


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
    # NOTE: affected_communities is computed for future use in
    # business flow page regeneration (Phase 4+). Currently only
    # changed_uids and affected_parents drive incremental composition.

    @property
    def is_empty(self) -> bool:
        return not self.changed_uids and not self.affected_parents

    @property
    def total_affected(self) -> int:
        return len(self.changed_uids) + len(self.affected_parents)


@dataclass(frozen=True)
class DomainDiff:
    """Result of domain-level diff: which domains need wiki regeneration."""

    affected_domains: list[str]
    changed_module_uids: list[str]
    total_changed: int

    @property
    def is_empty(self) -> bool:
        return self.total_changed == 0


async def compute_domain_diff(
    store: Any,
    business_id: str,
    repositories: list[str] | None = None,
) -> DomainDiff:
    """Identify domains affected by code changes since last wiki generation.

    Finds Module nodes in the given repositories where ``code_hash`` differs from
    ``wiki_code_hash`` (set by persistence after successful wiki generation),
    then maps each changed module to its ``business_domain`` property.
    """
    repos = list(repositories) if repositories else []
    if not repos:
        log.info("domain_diff_no_repos", business_id=business_id)
        return DomainDiff(affected_domains=[], changed_module_uids=[], total_changed=0)

    changed_result = await store.execute_query(
        "MATCH (n:Module) "
        "WHERE n.repository IN $repos "
        "AND n.code_hash IS NOT NULL "
        "AND (n.wiki_code_hash IS NULL OR n.code_hash <> n.wiki_code_hash) "
        "RETURN n.uid AS uid, n.name AS name, "
        "       coalesce(n.business_domain, '') AS domain",
        {"repos": repos},
    )

    rows = _query_dict_rows(changed_result)
    affected_domains: set[str] = set()
    changed_modules: list[str] = []
    for row in rows:
        domain = row.get("domain", "")
        if domain:
            affected_domains.add(domain)
        changed_modules.append(row["uid"])

    log.info(
        "domain_diff_computed",
        business_id=business_id,
        changed_modules=len(changed_modules),
        affected_domains=len(affected_domains),
    )

    return DomainDiff(
        affected_domains=sorted(affected_domains),
        changed_module_uids=changed_modules,
        total_changed=len(changed_modules),
    )


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
