from __future__ import annotations

import asyncio
import concurrent.futures
import os
from typing import Any

_POOL_SIZE = int(os.environ.get("FALKORDB__THREAD_POOL_SIZE", "4"))
_graph_executor = concurrent.futures.ThreadPoolExecutor(max_workers=_POOL_SIZE, thread_name_prefix="falkordb")
_xref_lock = asyncio.Lock()

_PARSING_EDGE_TYPES: tuple[str, ...] = (
    "CALLS",
    "CONTAINS",
    "INHERITS",
    "IMPLEMENTS",
    "IMPORTS",
    "PART_OF",
    "PROVIDES_RPC",
    "CONSUMES_RPC",
)


def _cypher_escape(value: str) -> str:
    """Escape single quotes in a string for safe Cypher literal interpolation."""
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _wiki_structure_path_case_cypher(var: str) -> str:
    """OpenCypher CASE for wiki layout path aligned with WikiStructurePlanner._structure_path."""

    return (
        f"CASE "
        f"WHEN {var}:Module THEN coalesce({var}.path, toString({var}.name), {var}.uid) "
        f"WHEN {var}:Class THEN coalesce({var}.fqn, toString({var}.name), {var}.uid) "
        f"WHEN {var}.file IS NOT NULL AND {var}.name IS NOT NULL "
        f"AND toString({var}.file) <> '' AND toString({var}.name) <> '' "
        f"THEN toString({var}.file) + '#' + toString({var}.name) "
        f"ELSE coalesce(toString({var}.fqn), toString({var}.name), {var}.uid) END"
    )


REFERENCES_CROSS_FILE_CYPHER = """
MATCH (d:Document)
WHERE d.code_references IS NOT NULL AND size(d.code_references) > 0
UNWIND d.code_references AS ref
WITH d, ref, split(d.file, '/') AS segs
WITH d, ref,
  CASE WHEN size(segs) < 2 THEN NULL
       ELSE reduce(s = segs[0], i IN range(1, size(segs)-1) | s + '/' + segs[i]) + '/' END AS doc_dir
OPTIONAL MATCH (f1:Function)
WHERE f1.fqn = ref
OPTIONAL MATCH (c1:Class)
WHERE c1.fqn = ref
WITH d, ref, doc_dir, collect(DISTINCT f1) + collect(DISTINCT c1) AS fqn_hits
OPTIONAL MATCH (f2:Function)
WHERE size(fqn_hits) = 0 AND f2.name = ref AND doc_dir IS NOT NULL AND f2.file STARTS WITH doc_dir
OPTIONAL MATCH (c2:Class)
WHERE size(fqn_hits) = 0 AND c2.name = ref AND doc_dir IS NOT NULL AND c2.file STARTS WITH doc_dir
WITH d, ref, fqn_hits, collect(DISTINCT f2) + collect(DISTINCT c2) AS dir_hits
OPTIONAL MATCH (f3:Function)
WHERE size(fqn_hits) = 0 AND size(dir_hits) = 0 AND f3.name = ref
OPTIONAL MATCH (c3:Class)
WHERE size(fqn_hits) = 0 AND size(dir_hits) = 0 AND c3.name = ref
WITH d, ref,
  CASE WHEN size(fqn_hits) > 0 THEN fqn_hits
       WHEN size(dir_hits) > 0 THEN dir_hits
       ELSE collect(DISTINCT f3) + collect(DISTINCT c3) END AS targets
UNWIND targets AS t
WITH d, t
WHERE t IS NOT NULL
MERGE (d)-[:REFERENCES]->(t)
RETURN count(*) AS cnt
""".strip()


class QueryResultWrapper:
    """Lightweight wrapper around FalkorDB query results.

    Provides both dict-based access via ``.data`` and raw positional access via subscript
    to maintain backward compatibility with callers that use ``result[row][col]``.
    """

    __slots__ = ("data", "raw")

    def __init__(self, data: list[dict[str, Any]], raw: list[list[Any]] | None = None):
        self.data = data
        self.raw = raw or []

    def __getitem__(self, idx: int) -> list[Any]:
        return self.raw[idx]

    def __len__(self) -> int:
        return len(self.raw)

    def __bool__(self) -> bool:
        return bool(self.raw)

    @property
    def result_set(self) -> list[list[Any]]:
        """Alias for ``raw`` (FalkorDB positional rows); older callers use this name."""
        return self.raw
