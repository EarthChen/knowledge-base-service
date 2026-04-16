"""Change-impact analysis and index vs. filesystem consistency checks."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config import get_settings
from log import get_logger
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_DEFAULT_EXTENSIONS: frozenset[str] = frozenset({
    ".py", ".java", ".go", ".js", ".ts", ".tsx", ".jsx",
})

# Align with indexer/business_flow_inferencer entry-point semantics.
_FUNCTION_ENTRY_ROLES: frozenset[str] = frozenset({
    "http_endpoint",
    "rpc_consumer",
    "message_listener",
    "scheduled_task",
})
_CLASS_ENTRY_ROLES: frozenset[str] = frozenset({
    "http_controller",
    "rpc_provider",
})


@dataclass
class ImpactReport:
    changed_functions: list[str]
    direct_callers: list[dict[str, Any]]
    transitive_callers: list[dict[str, Any]]
    affected_classes: list[str]
    affected_layers: list[str]
    affected_entry_points: list[dict[str, Any]]
    max_depth_reached: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_functions": self.changed_functions,
            "direct_callers": self.direct_callers,
            "transitive_callers": self.transitive_callers,
            "affected_classes": list(set(self.affected_classes)),
            "affected_layers": list(set(self.affected_layers)),
            "affected_entry_points": self.affected_entry_points,
            "max_depth_reached": self.max_depth_reached,
            "total_affected": len(self.direct_callers) + len(self.transitive_callers),
        }


@dataclass
class ConsistencyReport:
    total_graph_files: int
    total_repo_files: int
    ghost_files: list[str]
    missing_files: list[str]
    stale_files: list[str]
    is_consistent: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_graph_files": self.total_graph_files,
            "total_repo_files": self.total_repo_files,
            "ghost_files": self.ghost_files[:100],
            "missing_files": self.missing_files[:100],
            "stale_files": self.stale_files[:100],
            "is_consistent": self.is_consistent,
        }


def _coerce_unix_ts(value: Any) -> float | None:
    """Interpret graph timestamp as Unix seconds (handles ms-scale floats)."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v > 1e12:
        v /= 1000.0
    return v


def _is_entry_point(
    func_roles: list[str] | None,
    class_roles: list[str] | None,
) -> bool:
    fr = set(func_roles or [])
    cr = set(class_roles or [])
    return bool(fr & _FUNCTION_ENTRY_ROLES or cr & _CLASS_ENTRY_ROLES)


def _norm_repo_relative_key(repo_root: Path, file_path: str) -> str | None:
    """Map a graph or disk path to a repo-relative posix key for set comparison."""
    if not file_path or not file_path.strip():
        return None
    p = Path(file_path)
    try:
        if p.is_absolute():
            rel = p.resolve().relative_to(repo_root.resolve())
        else:
            rel = (repo_root / p).resolve().relative_to(repo_root.resolve())
    except (ValueError, OSError):
        try:
            return p.as_posix()
        except Exception:
            return None
    return rel.as_posix()


def _collect_repo_files_sync(
    repo_root: Path,
    extensions: set[str],
    exclude_dirs: set[str],
) -> set[str]:
    """Blocking walk of repo_root; returns repo-relative posix paths."""
    found: set[str] = set()
    if not repo_root.is_dir():
        return found

    for dirpath, dirnames, filenames in os.walk(repo_root, topdown=True):
        dirnames[:] = [d for d in dirnames if d not in exclude_dirs]
        parts = Path(dirpath).parts
        if any(part in exclude_dirs for part in parts):
            continue
        for name in filenames:
            suf = Path(name).suffix.lower()
            if suf not in extensions:
                continue
            full = Path(dirpath) / name
            try:
                key = full.resolve().relative_to(repo_root.resolve()).as_posix()
            except ValueError:
                key = full.as_posix()
            found.add(key)
    return found


class AnalysisService:
    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def analyze_impact(
        self,
        changed_functions: list[str],
        max_depth: int = 5,
    ) -> ImpactReport:
        if not changed_functions:
            return ImpactReport(
                changed_functions=[],
                direct_callers=[],
                transitive_callers=[],
                affected_classes=[],
                affected_layers=[],
                affected_entry_points=[],
                max_depth_reached=False,
            )

        try:
            depth_cap = max(1, min(int(max_depth), 50))
        except (TypeError, ValueError):
            depth_cap = 5
        cypher = (
            f"MATCH p=(target:Function)<-[:CALLS*1..{depth_cap}]-(caller:Function) "
            "WHERE target.name IN $names "
            "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
            "RETURN "
            "caller.uid AS caller_uid, "
            "caller.name AS caller_name, "
            "caller.file AS caller_file, "
            "caller.fqn AS caller_fqn, "
            "caller.semantic_roles AS caller_semantic_roles, "
            "caller.architecture_layer AS caller_architecture_layer, "
            "pc.name AS parent_class_name, "
            "pc.semantic_roles AS parent_class_semantic_roles, "
            "length(p) AS depth, "
            "target.name AS target_name "
            "ORDER BY depth "
            "LIMIT 2000"
        )

        try:
            result = await self._store.execute_query(
                cypher,
                params={"names": changed_functions},
            )
        except Exception as exc:
            log.error("analyze_impact_query_failed", error=str(exc))
            raise

        rows = result.data
        # Best depth per caller (minimum hops).
        best: dict[str, dict[str, Any]] = {}
        max_depth_reached = False

        for row in rows:
            uid = row.get("caller_uid") or ""
            if not uid:
                continue
            d = row.get("depth")
            try:
                depth_val = int(d) if d is not None else 0
            except (TypeError, ValueError):
                depth_val = 0
            if depth_val >= depth_cap:
                max_depth_reached = True

            prev = best.get(uid)
            if prev is None or depth_val < prev["depth"]:
                best[uid] = {
                    "depth": depth_val,
                    "caller_name": row.get("caller_name"),
                    "caller_file": row.get("caller_file"),
                    "caller_fqn": row.get("caller_fqn"),
                    "caller_semantic_roles": row.get("caller_semantic_roles"),
                    "caller_architecture_layer": row.get("caller_architecture_layer"),
                    "parent_class_name": row.get("parent_class_name"),
                    "parent_class_semantic_roles": row.get("parent_class_semantic_roles"),
                    "target_name": row.get("target_name"),
                }
            elif prev is not None and depth_val == prev["depth"]:
                if not prev.get("parent_class_name") and row.get("parent_class_name"):
                    prev["parent_class_name"] = row.get("parent_class_name")
                    prev["parent_class_semantic_roles"] = row.get("parent_class_semantic_roles")

        direct_callers: list[dict[str, Any]] = []
        transitive_callers: list[dict[str, Any]] = []
        affected_classes: list[str] = []
        affected_layers: list[str] = []
        affected_entry_points: list[dict[str, Any]] = []

        for uid, info in best.items():
            depth_val = info["depth"]
            func_roles = info.get("caller_semantic_roles")
            if not isinstance(func_roles, list):
                func_roles = None
            pcls_roles = info.get("parent_class_semantic_roles")
            if not isinstance(pcls_roles, list):
                pcls_roles = None

            cls_name = info.get("parent_class_name")
            if isinstance(cls_name, str) and cls_name.strip():
                affected_classes.append(cls_name)

            layer = info.get("caller_architecture_layer")
            if isinstance(layer, str) and layer.strip():
                affected_layers.append(layer)

            entry = {
                "uid": uid,
                "name": info.get("caller_name"),
                "file": info.get("caller_file"),
                "fqn": info.get("caller_fqn"),
                "depth": depth_val,
                "target_name": info.get("target_name"),
                "semantic_roles": func_roles,
                "parent_class": cls_name if isinstance(cls_name, str) else None,
            }

            if _is_entry_point(func_roles, pcls_roles):
                affected_entry_points.append(dict(entry))

            if depth_val == 1:
                direct_callers.append(entry)
            elif depth_val > 1:
                transitive_callers.append(entry)

        return ImpactReport(
            changed_functions=list(changed_functions),
            direct_callers=direct_callers,
            transitive_callers=transitive_callers,
            affected_classes=affected_classes,
            affected_layers=affected_layers,
            affected_entry_points=affected_entry_points,
            max_depth_reached=max_depth_reached,
        )

    async def verify_consistency(
        self,
        repo_path: str,
        supported_extensions: set[str] | None = None,
        repository: str | None = None,
    ) -> ConsistencyReport:
        ext = set(supported_extensions) if supported_extensions else set(_DEFAULT_EXTENSIONS)
        exclude_dirs = set(get_settings().exclude_dirs)

        if repository:
            cypher = (
                "MATCH (n) WHERE n.file IS NOT NULL AND n.repository = $repo "
                "RETURN DISTINCT n.file AS file_path"
            )
        else:
            cypher = (
                "MATCH (n) WHERE n.file IS NOT NULL "
                "RETURN DISTINCT n.file AS file_path"
            )
        params: dict[str, Any] = {"repo": repository} if repository else {}
        try:
            gres = await self._store.execute_query(cypher, params)
        except Exception as exc:
            log.error("verify_consistency_graph_query_failed", error=str(exc))
            raise

        graph_paths_raw = [row.get("file_path") for row in gres.data if row.get("file_path")]
        graph_keys: set[str] = set()
        for p in graph_paths_raw:
            if isinstance(p, str) and p.strip():
                graph_keys.add(p.strip())

        repo_root = Path(repo_path)
        if not repo_root.is_dir():
            log.warning("verify_consistency_repo_not_a_directory", repo_path=repo_path)
            ghost_sorted = sorted(graph_keys)
            return ConsistencyReport(
                total_graph_files=len(graph_keys),
                total_repo_files=0,
                ghost_files=ghost_sorted,
                missing_files=[],
                stale_files=[],
                is_consistent=len(graph_keys) == 0,
            )

        loop = asyncio.get_running_loop()
        repo_keys = await loop.run_in_executor(
            None,
            lambda: _collect_repo_files_sync(repo_root.resolve(), ext, exclude_dirs),
        )

        normalized_graph: set[str] = set()
        for g in graph_keys:
            k = _norm_repo_relative_key(repo_root, g)
            if k:
                normalized_graph.add(k)

        ghost_files = sorted(normalized_graph - repo_keys)
        missing_files = sorted(repo_keys - normalized_graph)
        stale_files: list[str] = []

        # Stale detection when nodes expose last_indexed_at (optional property).
        stale_row_data: list[dict[str, Any]] = []
        try:
            if repository:
                stale_cypher = (
                    "MATCH (n) WHERE n.file IS NOT NULL AND n.last_indexed_at IS NOT NULL "
                    "AND n.repository = $repo "
                    "RETURN DISTINCT n.file AS file_path, n.last_indexed_at AS last_indexed_at"
                )
            else:
                stale_cypher = (
                    "MATCH (n) WHERE n.file IS NOT NULL AND n.last_indexed_at IS NOT NULL "
                    "RETURN DISTINCT n.file AS file_path, n.last_indexed_at AS last_indexed_at"
                )
            stale_rows = await self._store.execute_query(stale_cypher, params)
            stale_row_data = stale_rows.data
        except Exception as exc:
            log.warning("verify_consistency_stale_query_skipped", error=str(exc))

        for row in stale_row_data:
            fp = row.get("file_path")
            ts = row.get("last_indexed_at")
            if not fp or ts is None:
                continue
            key = _norm_repo_relative_key(repo_root, fp) if isinstance(fp, str) else None
            if not key:
                continue
            full = repo_root / key
            if not full.is_file():
                continue
            try:
                mtime = await loop.run_in_executor(None, lambda p=full: p.stat().st_mtime)
            except OSError:
                continue
            indexed_ts = _coerce_unix_ts(ts)
            if indexed_ts is None:
                continue
            if mtime > indexed_ts:
                stale_files.append(key)

        stale_files = sorted(set(stale_files))

        is_consistent = len(ghost_files) == 0 and len(missing_files) == 0

        return ConsistencyReport(
            total_graph_files=len(normalized_graph),
            total_repo_files=len(repo_keys),
            ghost_files=ghost_files,
            missing_files=missing_files,
            stale_files=stale_files,
            is_consistent=is_consistent,
        )
