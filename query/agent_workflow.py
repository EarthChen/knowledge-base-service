"""P2 Agent workflow service: PR Review context and Smart Context builder.

Provides composite query APIs optimized for AI agent consumption during
code review and feature development tasks.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

from log import get_logger

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)

_MAX_CHANGED_FUNCTIONS = 200
_MAX_CONTEXT_ITEMS = 50


# ─── Data Models ────────────────────────────────────────────────────────

@dataclass
class ChangedEntity:
    file: str
    name: str
    entity_type: str  # "function" | "class"
    start_line: int = 0
    end_line: int = 0


@dataclass
class ReviewImpact:
    """Impact summary for a single changed entity."""
    entity_name: str
    entity_file: str
    direct_callers: list[dict[str, Any]] = field(default_factory=list)
    affected_endpoints: list[dict[str, Any]] = field(default_factory=list)
    cross_repo_impacts: list[dict[str, Any]] = field(default_factory=list)
    affected_layers: list[str] = field(default_factory=list)


@dataclass
class ReviewContext:
    """Structured review context for a PR diff."""
    changed_files: list[str]
    changed_entities: list[dict[str, Any]]
    impacts: list[dict[str, Any]]
    affected_endpoints_summary: list[dict[str, Any]]
    cross_repo_summary: list[dict[str, Any]]
    affected_layers: list[str]
    suggestions: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "changed_files": self.changed_files,
            "changed_entities": self.changed_entities,
            "impacts": self.impacts,
            "affected_endpoints_summary": self.affected_endpoints_summary,
            "cross_repo_summary": self.cross_repo_summary,
            "affected_layers": list(set(self.affected_layers)),
            "suggestions": self.suggestions,
            "summary": {
                "total_changed_files": len(self.changed_files),
                "total_changed_entities": len(self.changed_entities),
                "total_affected_endpoints": len(self.affected_endpoints_summary),
                "total_cross_repo_impacts": len(self.cross_repo_summary),
            },
        }


@dataclass
class SmartContext:
    """Optimal context package for a code entity."""
    target: dict[str, Any]
    callers: list[dict[str, Any]]
    callees: list[dict[str, Any]]
    parent_class: dict[str, Any] | None
    sibling_methods: list[dict[str, Any]]
    cross_repo_deps: list[dict[str, Any]]
    entity_tables: list[dict[str, Any]]
    di_dependencies: list[dict[str, Any]]
    architecture_layer: str
    related_interfaces: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target,
            "callers": self.callers,
            "callees": self.callees,
            "parent_class": self.parent_class,
            "sibling_methods": self.sibling_methods,
            "cross_repo_deps": self.cross_repo_deps,
            "entity_tables": self.entity_tables,
            "di_dependencies": self.di_dependencies,
            "architecture_layer": self.architecture_layer,
            "related_interfaces": self.related_interfaces,
        }


# ─── Diff Parser ────────────────────────────────────────────────────────

def parse_diff_changed_files(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files: list[str] = []
    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
        elif line.startswith("diff --git"):
            m = re.search(r"b/(.+)$", line)
            if m:
                path = m.group(1).strip()
                if path not in files:
                    files.append(path)
    return list(dict.fromkeys(files))


def parse_diff_changed_lines(diff_text: str) -> dict[str, list[tuple[int, int]]]:
    """Extract changed line ranges per file from a unified diff.

    Returns {file_path: [(start_line, end_line), ...]}.
    """
    result: dict[str, list[tuple[int, int]]] = {}
    current_file: str | None = None

    for line in diff_text.splitlines():
        if line.startswith("+++ b/"):
            current_file = line[6:].strip()
            if current_file and current_file != "/dev/null":
                result.setdefault(current_file, [])
            else:
                current_file = None
        elif line.startswith("@@ ") and current_file:
            m = re.search(r"\+(\d+)(?:,(\d+))?", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2)) if m.group(2) else 1
                end = start + count - 1
                result[current_file].append((start, end))
    return result


# ─── Service ────────────────────────────────────────────────────────────

class AgentWorkflowService:
    """Composite queries for AI agent workflows."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    # ─── P2-2: PR Review Context ────────────────────────────────────

    async def build_review_context(
        self,
        diff_text: str,
        repository: str | None = None,
        max_depth: int = 3,
    ) -> ReviewContext:
        """Build a comprehensive review context from a git diff."""
        changed_files = parse_diff_changed_files(diff_text)
        changed_lines = parse_diff_changed_lines(diff_text)

        changed_entities = await self._find_changed_entities(changed_files, changed_lines, repository)

        impacts: list[dict[str, Any]] = []
        all_affected_endpoints: list[dict[str, Any]] = []
        all_cross_repo: list[dict[str, Any]] = []
        all_layers: list[str] = []
        suggestions: list[str] = []

        func_names = [
            e["name"] for e in changed_entities
            if e.get("entity_type") == "function"
        ][:_MAX_CHANGED_FUNCTIONS]

        if func_names:
            impact_data = await self._batch_impact_analysis(func_names, max_depth)
            for item in impact_data:
                impacts.append(item)
                all_affected_endpoints.extend(item.get("affected_endpoints", []))
                all_cross_repo.extend(item.get("cross_repo_impacts", []))
                all_layers.extend(item.get("affected_layers", []))

        endpoint_map: dict[str, dict[str, Any]] = {}
        for ep in all_affected_endpoints:
            key = ep.get("uid") or ep.get("name", "")
            if key and key not in endpoint_map:
                endpoint_map[key] = ep

        cross_repo_map: dict[str, dict[str, Any]] = {}
        for cr in all_cross_repo:
            key = f"{cr.get('source_repo', '')}→{cr.get('target_repo', '')}"
            if key not in cross_repo_map:
                cross_repo_map[key] = cr

        if endpoint_map:
            suggestions.append(
                f"This PR affects {len(endpoint_map)} API endpoint(s). "
                "Consider testing these endpoints."
            )
        if cross_repo_map:
            suggestions.append(
                f"This PR has cross-repository impact on {len(cross_repo_map)} service link(s). "
                "Consider coordinating with the dependent service teams."
            )
        rpc_providers_changed = any(
            "rpc_provider" in (e.get("semantic_roles") or [])
            for e in changed_entities
        )
        if rpc_providers_changed:
            suggestions.append(
                "RPC provider interface changed — this may break downstream consumers. "
                "Check CROSS_REPO_CALLS edges for affected consumers."
            )

        return ReviewContext(
            changed_files=changed_files,
            changed_entities=changed_entities,
            impacts=impacts,
            affected_endpoints_summary=list(endpoint_map.values()),
            cross_repo_summary=list(cross_repo_map.values()),
            affected_layers=all_layers,
            suggestions=suggestions,
        )

    async def _find_changed_entities(
        self,
        changed_files: list[str],
        changed_lines: dict[str, list[tuple[int, int]]],
        repository: str | None,
    ) -> list[dict[str, Any]]:
        """Find graph entities that overlap with changed file regions."""
        if not changed_files:
            return []

        entities: list[dict[str, Any]] = []
        seen_uids: set[str] = set()

        for file_path in changed_files[:50]:
            repo_filter = "AND n.repository = $repo " if repository else ""
            params: dict[str, Any] = {"file_suffix": file_path}
            if repository:
                params["repo"] = repository

            try:
                res = await self._store.execute_query(
                    "MATCH (n) "
                    "WHERE (n:Function OR n:Class) AND n.file ENDS WITH $file_suffix "
                    + repo_filter +
                    "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
                    "n.start_line AS start_line, n.end_line AS end_line, "
                    "labels(n)[0] AS entity_type, "
                    "n.semantic_roles AS semantic_roles, "
                    "n.architecture_layer AS architecture_layer, "
                    "n.signature AS signature",
                    params,
                )
            except Exception as exc:
                log.warning("find_changed_entities_query_failed", file=file_path, error=str(exc))
                continue

            line_ranges = changed_lines.get(file_path, [])

            for row in res.data:
                uid = row.get("uid") or ""
                if uid in seen_uids:
                    continue

                if line_ranges:
                    start = row.get("start_line")
                    end = row.get("end_line")
                    if start is not None and end is not None:
                        try:
                            s = int(start)
                            e = int(end)
                            overlaps = any(
                                s <= lr_end and e >= lr_start
                                for lr_start, lr_end in line_ranges
                            )
                            if not overlaps:
                                continue
                        except (TypeError, ValueError):
                            pass

                seen_uids.add(uid)
                entities.append({
                    "uid": uid,
                    "name": row.get("name"),
                    "file": row.get("file"),
                    "start_line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "entity_type": (row.get("entity_type") or "").lower(),
                    "semantic_roles": row.get("semantic_roles"),
                    "architecture_layer": row.get("architecture_layer"),
                    "signature": row.get("signature"),
                })

        return entities

    async def _batch_impact_analysis(
        self,
        func_names: list[str],
        max_depth: int,
    ) -> list[dict[str, Any]]:
        """Run impact analysis and collect cross-repo impacts."""
        results: list[dict[str, Any]] = []
        depth_cap = max(1, min(max_depth, 20))

        try:
            cypher = (
                f"MATCH p=(target:Function)<-[:CALLS*1..{depth_cap}]-(caller:Function) "
                "WHERE target.name IN $names "
                "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
                "RETURN "
                "target.name AS target_name, "
                "caller.uid AS caller_uid, "
                "caller.name AS caller_name, "
                "caller.file AS caller_file, "
                "caller.semantic_roles AS caller_semantic_roles, "
                "caller.architecture_layer AS caller_architecture_layer, "
                "pc.name AS parent_class_name, "
                "pc.semantic_roles AS parent_class_semantic_roles, "
                "length(p) AS depth "
                "ORDER BY depth LIMIT 1000"
            )
            res = await self._store.execute_query(cypher, {"names": func_names})
        except Exception as exc:
            log.error("batch_impact_analysis_failed", error=str(exc))
            return results

        by_target: dict[str, list[dict[str, Any]]] = {}
        for row in res.data:
            target = row.get("target_name") or ""
            by_target.setdefault(target, []).append(row)

        _ENTRY_FUNC_ROLES = frozenset({"http_endpoint", "rpc_consumer", "message_listener", "scheduled_task"})
        _ENTRY_CLASS_ROLES = frozenset({"http_controller", "rpc_provider"})

        for target_name, rows in by_target.items():
            callers: list[dict[str, Any]] = []
            endpoints: list[dict[str, Any]] = []
            layers: set[str] = set()

            for row in rows:
                layer = row.get("caller_architecture_layer")
                if isinstance(layer, str) and layer.strip():
                    layers.add(layer)

                caller_info = {
                    "uid": row.get("caller_uid"),
                    "name": row.get("caller_name"),
                    "file": row.get("caller_file"),
                    "depth": row.get("depth"),
                    "parent_class": row.get("parent_class_name"),
                }
                callers.append(caller_info)

                func_roles = set(row.get("caller_semantic_roles") or [])
                cls_roles = set(row.get("parent_class_semantic_roles") or [])
                if func_roles & _ENTRY_FUNC_ROLES or cls_roles & _ENTRY_CLASS_ROLES:
                    endpoints.append(caller_info)

            results.append({
                "target_name": target_name,
                "direct_callers": [c for c in callers if (c.get("depth") or 0) == 1],
                "affected_endpoints": endpoints,
                "affected_layers": list(layers),
                "cross_repo_impacts": [],
            })

        try:
            cross_repo_res = await self._store.execute_query(
                "MATCH (f:Function)-[r:CROSS_REPO_CALLS]->(c:Class) "
                "WHERE f.name IN $names "
                "RETURN f.name AS consumer_name, f.repository AS source_repo, "
                "c.name AS provider_name, c.repository AS target_repo, "
                "r.interface AS interface",
                {"names": func_names},
            )
            cross_repo_by_name: dict[str, list[dict[str, Any]]] = {}
            for row in cross_repo_res.data:
                name = row.get("consumer_name") or ""
                cross_repo_by_name.setdefault(name, []).append({
                    "source_repo": row.get("source_repo"),
                    "target_repo": row.get("target_repo"),
                    "provider": row.get("provider_name"),
                    "interface": row.get("interface"),
                })

            for item in results:
                target = item["target_name"]
                if target in cross_repo_by_name:
                    item["cross_repo_impacts"] = cross_repo_by_name[target]

        except Exception as exc:
            log.warning("cross_repo_impact_query_failed", error=str(exc))

        return results

    # ─── P2-3: Smart Context Builder ────────────────────────────────

    async def build_smart_context(
        self,
        entity_name: str,
        entity_type: str = "function",
        repository: str | None = None,
    ) -> SmartContext:
        """Build an optimal context package for a function or class."""

        target = await self._find_target_entity(entity_name, entity_type, repository)
        if not target:
            return SmartContext(
                target={"name": entity_name, "error": "Entity not found"},
                callers=[], callees=[], parent_class=None,
                sibling_methods=[], cross_repo_deps=[], entity_tables=[],
                di_dependencies=[], architecture_layer="unknown",
                related_interfaces=[],
            )

        target_uid = target.get("uid", "")
        target_label = target.get("entity_type", "Function")

        callers = await self._get_callers(target_uid, target_label)
        callees = await self._get_callees(target_uid, target_label)
        parent_class, siblings = await self._get_class_context(target_uid, target_label)
        cross_repo = await self._get_cross_repo_context(target_uid, target_label)
        entity_tables = await self._get_entity_table_context(target_uid, target_label, parent_class)
        di_deps = await self._get_di_dependencies(target_uid, target_label, parent_class)
        interfaces = await self._get_interface_context(target_uid, target_label, parent_class)

        return SmartContext(
            target=target,
            callers=callers,
            callees=callees,
            parent_class=parent_class,
            sibling_methods=siblings,
            cross_repo_deps=cross_repo,
            entity_tables=entity_tables,
            di_dependencies=di_deps,
            architecture_layer=target.get("architecture_layer", "unknown"),
            related_interfaces=interfaces,
        )

    async def _find_target_entity(
        self, name: str, entity_type: str, repository: str | None
    ) -> dict[str, Any] | None:
        label = "Function" if entity_type == "function" else "Class"
        repo_filter = "AND n.repository = $repo " if repository else ""
        params: dict[str, Any] = {"name": name}
        if repository:
            params["repo"] = repository

        try:
            res = await self._store.execute_query(
                f"MATCH (n:{label}) "
                f"WHERE (n.name = $name OR n.fqn ENDS WITH $name) {repo_filter}"
                "RETURN n.uid AS uid, n.name AS name, n.file AS file, "
                "n.start_line AS start_line, n.end_line AS end_line, "
                "n.signature AS signature, n.code_snippet AS code_snippet, "
                "n.docstring AS docstring, n.fqn AS fqn, "
                "n.semantic_roles AS semantic_roles, "
                "n.architecture_layer AS architecture_layer, "
                "n.repository AS repository, "
                "n.annotations AS annotations "
                "LIMIT 1",
                params,
            )
            if res.data:
                row = res.data[0]
                row["entity_type"] = label
                return row
        except Exception as exc:
            log.warning("find_target_entity_failed", name=name, error=str(exc))
        return None

    async def _get_callers(self, uid: str, label: str) -> list[dict[str, Any]]:
        try:
            res = await self._store.execute_query(
                f"MATCH (caller:Function)-[:CALLS]->(target:{label} {{uid: $uid}}) "
                "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(caller) "
                "RETURN caller.uid AS uid, caller.name AS name, caller.file AS file, "
                "caller.signature AS signature, caller.architecture_layer AS layer, "
                "pc.name AS parent_class "
                f"LIMIT {_MAX_CONTEXT_ITEMS}",
                {"uid": uid},
            )
            return res.data
        except Exception as exc:
            log.warning("get_callers_failed", uid=uid, error=str(exc))
            return []

    async def _get_callees(self, uid: str, label: str) -> list[dict[str, Any]]:
        try:
            if label == "Function":
                res = await self._store.execute_query(
                    "MATCH (source:Function {uid: $uid})-[:CALLS]->(callee:Function) "
                    "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(callee) "
                    "RETURN callee.uid AS uid, callee.name AS name, callee.file AS file, "
                    "callee.signature AS signature, callee.architecture_layer AS layer, "
                    "pc.name AS parent_class "
                    f"LIMIT {_MAX_CONTEXT_ITEMS}",
                    {"uid": uid},
                )
            else:
                res = await self._store.execute_query(
                    "MATCH (cls:Class {uid: $uid})-[:CONTAINS]->(m:Function)-[:CALLS]->(callee:Function) "
                    "OPTIONAL MATCH (pc:Class)-[:CONTAINS]->(callee) "
                    "RETURN DISTINCT callee.uid AS uid, callee.name AS name, callee.file AS file, "
                    "callee.signature AS signature, callee.architecture_layer AS layer, "
                    "pc.name AS parent_class "
                    f"LIMIT {_MAX_CONTEXT_ITEMS}",
                    {"uid": uid},
                )
            return res.data
        except Exception as exc:
            log.warning("get_callees_failed", uid=uid, error=str(exc))
            return []

    async def _get_class_context(
        self, uid: str, label: str
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        if label == "Class":
            try:
                methods = await self._store.execute_query(
                    "MATCH (c:Class {uid: $uid})-[:CONTAINS]->(m:Function) "
                    "RETURN m.uid AS uid, m.name AS name, m.signature AS signature, "
                    "m.architecture_layer AS layer "
                    f"LIMIT {_MAX_CONTEXT_ITEMS}",
                    {"uid": uid},
                )
                return None, methods.data
            except Exception as exc:
                log.warning("get_class_methods_failed", uid=uid, error=str(exc))
                return None, []

        try:
            parent_res = await self._store.execute_query(
                "MATCH (c:Class)-[:CONTAINS]->(f:Function {uid: $uid}) "
                "RETURN c.uid AS uid, c.name AS name, c.file AS file, "
                "c.fqn AS fqn, c.signature AS signature, "
                "c.semantic_roles AS semantic_roles, "
                "c.architecture_layer AS architecture_layer, "
                "c.base_classes AS base_classes "
                "LIMIT 1",
                {"uid": uid},
            )
            if not parent_res.data:
                return None, []

            parent = parent_res.data[0]
            parent_uid = parent.get("uid") or ""

            siblings = await self._store.execute_query(
                "MATCH (c:Class {uid: $cls_uid})-[:CONTAINS]->(m:Function) "
                "WHERE m.uid <> $func_uid "
                "RETURN m.uid AS uid, m.name AS name, m.signature AS signature, "
                "m.architecture_layer AS layer "
                f"LIMIT {_MAX_CONTEXT_ITEMS}",
                {"cls_uid": parent_uid, "func_uid": uid},
            )
            return parent, siblings.data

        except Exception as exc:
            log.warning("get_class_context_failed", uid=uid, error=str(exc))
            return None, []

    async def _get_cross_repo_context(self, uid: str, label: str) -> list[dict[str, Any]]:
        try:
            if label == "Function":
                res = await self._store.execute_query(
                    "MATCH (f:Function {uid: $uid})-[r:CROSS_REPO_CALLS]->(c:Class) "
                    "RETURN c.uid AS uid, c.name AS name, c.repository AS repository, "
                    "c.fqn AS fqn, r.interface AS interface, r.target_repo AS target_repo "
                    f"LIMIT {_MAX_CONTEXT_ITEMS}",
                    {"uid": uid},
                )
            else:
                res = await self._store.execute_query(
                    "MATCH (f:Function)-[r:CROSS_REPO_CALLS]->(c:Class {uid: $uid}) "
                    "RETURN f.uid AS uid, f.name AS name, f.repository AS repository, "
                    "f.fqn AS fqn, r.interface AS interface, r.source_repo AS source_repo "
                    f"LIMIT {_MAX_CONTEXT_ITEMS}",
                    {"uid": uid},
                )
            return res.data
        except Exception as exc:
            log.warning("get_cross_repo_context_failed", uid=uid, error=str(exc))
            return []

    async def _get_entity_table_context(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._store.execute_query(
                "MATCH (dao:Class {uid: $uid})-[r:ACCESSES_TABLE]->(entity:Class) "
                "RETURN entity.uid AS uid, entity.name AS name, entity.fqn AS fqn, "
                "entity.table_name AS table_name, r.table_name AS rel_table_name "
                f"LIMIT {_MAX_CONTEXT_ITEMS}",
                {"uid": class_uid},
            )
            return res.data
        except Exception as exc:
            log.warning("get_entity_table_context_failed", uid=class_uid, error=str(exc))
            return []

    async def _get_di_dependencies(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._store.execute_query(
                "MATCH (source:Class {uid: $uid})-[r:DEPENDS_ON]->(target:Class) "
                "RETURN target.uid AS uid, target.name AS name, target.fqn AS fqn, "
                "target.architecture_layer AS layer, r.injection_type AS injection_type, "
                "r.field_name AS field_name "
                f"LIMIT {_MAX_CONTEXT_ITEMS}",
                {"uid": class_uid},
            )
            return res.data
        except Exception as exc:
            log.warning("get_di_dependencies_failed", uid=class_uid, error=str(exc))
            return []

    async def _get_interface_context(
        self, uid: str, label: str, parent_class: dict[str, Any] | None
    ) -> list[dict[str, Any]]:
        class_uid = uid if label == "Class" else (parent_class or {}).get("uid", "")
        if not class_uid:
            return []
        try:
            res = await self._store.execute_query(
                "MATCH (c:Class {uid: $uid})-[:IMPLEMENTS]->(iface:Class) "
                "RETURN iface.uid AS uid, iface.name AS name, iface.fqn AS fqn "
                f"LIMIT {_MAX_CONTEXT_ITEMS}",
                {"uid": class_uid},
            )
            return res.data
        except Exception as exc:
            log.warning("get_interface_context_failed", uid=class_uid, error=str(exc))
            return []
