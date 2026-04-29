"""Build module-level dependency graph for Wiki domain tree decomposition."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from log import get_logger

if TYPE_CHECKING:
    from store.falkordb_store import FalkorDBGraphStore

log = get_logger(__name__)

_RPC_ENTRY_ROLES = frozenset({"rpc_provider", "http_controller", "message_listener", "scheduled_task"})
_ENTRY_NAME_HINTS = frozenset({"controller", "endpoint", "handler", "main", "gateway"})


@dataclass
class ModuleInfo:
    name: str
    path: str
    uid: str
    summary: str = ""
    docstring: str = ""
    semantic_roles: list[str] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    top_classes: list[str] = field(default_factory=list)
    calls_out: list[str] = field(default_factory=list)
    called_by: list[str] = field(default_factory=list)
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ModuleEdge:
    source: str
    target: str
    edge_type: str
    weight: int = 1


@dataclass
class ModuleGraph:
    modules: list[ModuleInfo] = field(default_factory=list)
    edges: list[ModuleEdge] = field(default_factory=list)
    entry_points: list[str] = field(default_factory=list)


class ModuleDependencyGraph:
    _MODULE_CALLS_CYPHER = (
        "MATCH (m1:Module {repository: $repo})-[:CONTAINS*1..3]->(f1)"
        "-[:CALLS]->(f2)<-[:CONTAINS*1..3]-(m2:Module {repository: $repo}) "
        "WHERE m1 <> m2 "
        "RETURN m1.name AS source, m2.name AS target, count(*) AS weight "
        "ORDER BY weight DESC"
    )

    def __init__(self, store: FalkorDBGraphStore) -> None:
        self._store = store

    async def build(self, repository: str) -> ModuleGraph:
        modules = await self._load_modules(repository)
        edges = await self._load_module_edges(repository)
        # Populate calls_out/called_by on modules
        calls_out_map: dict[str, list[str]] = {}
        called_by_map: dict[str, list[str]] = {}
        for e in edges:
            calls_out_map.setdefault(e.source, []).append(e.target)
            called_by_map.setdefault(e.target, []).append(e.source)
        for m in modules:
            m.calls_out = calls_out_map.get(m.name, [])
            m.called_by = called_by_map.get(m.name, [])
        entry_points = self._identify_entry_points(modules, edges)
        return ModuleGraph(modules=modules, edges=edges, entry_points=entry_points)

    async def _load_modules(self, repository: str) -> list[ModuleInfo]:
        result = await self._store.execute_query(
            "MATCH (m:Module {repository: $repo}) RETURN m.name AS name, m.path AS path, m.uid AS uid, m.summary AS summary, m.docstring AS docstring, m.semantic_roles AS semantic_roles, m.annotations AS annotations, m.rpc_interface AS rpc_interface",
            {"repo": repository},
        )
        modules = []
        for row in result.data:
            roles_raw = row.get("semantic_roles")
            roles = roles_raw if isinstance(roles_raw, list) else []
            anns_raw = row.get("annotations")
            anns = anns_raw if isinstance(anns_raw, list) else []
            props: dict[str, Any] = {}
            rpc = row.get("rpc_interface")
            if rpc:
                props["rpc_interface"] = str(rpc)
            modules.append(
                ModuleInfo(
                    name=str(row.get("name", "")),
                    path=str(row.get("path", "")),
                    uid=str(row.get("uid", "")),
                    summary=str(row.get("summary", "") or ""),
                    docstring=str(row.get("docstring", "") or ""),
                    semantic_roles=roles,
                    annotations=anns,
                    properties=props,
                )
            )
        return modules

    async def _load_module_edges(self, repository: str) -> list[ModuleEdge]:
        result = await self._store.execute_query(
            self._MODULE_CALLS_CYPHER,
            {"repo": repository},
        )
        return [
            ModuleEdge(
                source=str(r.get("source", "")),
                target=str(r.get("target", "")),
                edge_type="CALLS",
                weight=int(r.get("weight", 1)),
            )
            for r in result.data
        ]

    def _identify_entry_points(self, modules: list[ModuleInfo], edges: list[ModuleEdge]) -> list[str]:
        called_modules = {e.target for e in edges}
        calling_modules = {e.source for e in edges}
        entry_points: list[str] = []
        for m in modules:
            is_entry = False
            if m.name in calling_modules and m.name not in called_modules:
                is_entry = True
            if set(m.semantic_roles) & _RPC_ENTRY_ROLES:
                is_entry = True
            if any(hint in m.name.lower() for hint in _ENTRY_NAME_HINTS):
                is_entry = True
            if is_entry:
                entry_points.append(m.name)
        return entry_points


@dataclass
class TokenBudget:
    total: int
    used: int

    def allows_p1(self) -> bool:
        return (self.total - self.used) > 150

    def allows_p2(self) -> bool:
        return (self.total - self.used) > 250


class ModuleReprBuilder:
    MAX_TOKENS_PER_BATCH = 30_000

    def build(self, module: ModuleInfo, budget: TokenBudget) -> str:
        lines = [f"Module: {module.name}"]
        if module.semantic_roles:
            lines.append(f"  Role: {', '.join(module.semantic_roles)}")
        if "rpc_provider" in (module.semantic_roles or []):
            rpc_iface = module.properties.get("rpc_interface", "")
            if rpc_iface:
                lines.append(f"  RPC Interface: {rpc_iface}")
        lines.append(f"  Deps OUT: {module.calls_out[:10]}")
        lines.append(f"  Deps IN: {module.called_by[:10]}")
        if budget.allows_p1():
            summary = module.summary or module.docstring
            if summary:
                lines.append(f"  Summary: {summary[:300]}")
        if budget.allows_p2():
            if module.top_classes:
                lines.append(f"  Key classes: {module.top_classes[:5]}")
            if module.annotations:
                lines.append(f"  Annotations: {module.annotations[:5]}")
        return "\n".join(lines)
