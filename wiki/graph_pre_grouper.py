"""Graph-based pre-grouping for domain classification using connected components."""
from __future__ import annotations

import os
from dataclasses import dataclass

from core.log import get_logger

log = get_logger(__name__)


@dataclass
class PreGroup:
    group_id: int
    module_names: list[str]
    directory_prefix: str


class _UnionFind:
    def __init__(self) -> None:
        self._parent: dict[str, str] = {}
        self._rank: dict[str, int] = {}

    def find(self, x: str) -> str:
        self._parent.setdefault(x, x)
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        self._rank.setdefault(ra, 0)
        self._rank.setdefault(rb, 0)
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1

    def components(self) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = {}
        for node in self._parent:
            root = self.find(node)
            groups.setdefault(root, []).append(node)
        return groups


def _longest_common_prefix(paths: list[str]) -> str:
    if not paths:
        return ""
    dirs = [os.path.dirname(p) for p in paths]
    if not dirs:
        return ""
    prefix = dirs[0]
    for d in dirs[1:]:
        while not d.startswith(prefix):
            prefix = os.path.dirname(prefix)
            if not prefix:
                return ""
    return prefix


_MODULE_CALLS_CYPHER = (
    "MATCH (m1:Module {repository: $repo})-[:CONTAINS*1..3]->(f1)"
    "-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module {repository: $repo}) "
    "WHERE m1 <> m2 "
    "RETURN m1.name AS source, m2.name AS target, count(*) AS weight "
    "ORDER BY weight DESC"
)


async def compute_pre_groups(
    graph_store,
    repositories: list[str],
    module_paths: dict[str, str],
) -> list[PreGroup]:
    """Compute connected components of module CALLS graph for domain classification hints.

    Args:
        graph_store: FalkorDB graph store
        repositories: list of repository identifiers to query
        module_paths: mapping of module_name -> file path

    Returns:
        List of PreGroups (only components with >= 2 modules)
    """
    uf = _UnionFind()

    for repo in repositories:
        try:
            result = await graph_store.execute_query(_MODULE_CALLS_CYPHER, {"repo": repo})
            for row in result.data:
                source = str(row.get("source", ""))
                target = str(row.get("target", ""))
                if source and target and source in module_paths and target in module_paths:
                    uf.union(source, target)
        except Exception:
            log.warning("pre_grouper_query_failed", repo=repo, exc_info=True)

    components = uf.components()

    groups: list[PreGroup] = []
    gid = 0
    for members in components.values():
        if len(members) < 2:
            continue
        paths = [module_paths[m] for m in members if m in module_paths]
        prefix = _longest_common_prefix(paths)
        groups.append(PreGroup(group_id=gid, module_names=sorted(members), directory_prefix=prefix))
        gid += 1

    log.info("pre_groups_computed", total_groups=len(groups), total_modules=sum(len(g.module_names) for g in groups))
    return groups
