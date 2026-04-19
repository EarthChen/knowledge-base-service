"""Graph-level architecture insights — anomalies and quality signals."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from log import get_logger
from store.falkordb_store import FalkorDBStore, QueryResultWrapper

log = get_logger(__name__)

_REPO_PARAM = "repo"

# Distinctive markers for tests and debugging (stable routing under concurrent queries).
_Q_STATS = "__GRAPH_INSIGHTS_Q_STATS__"
_Q_ISOLATED = "__GRAPH_INSIGHTS_Q_ISOLATED__"
_Q_CYCLES = "__GRAPH_INSIGHTS_Q_CYCLES__"
_Q_CROSS_LAYER = "__GRAPH_INSIGHTS_Q_CROSS_LAYER__"
_Q_COHESION = "__GRAPH_INSIGHTS_Q_COHESION__"
_Q_BRIDGE = "__GRAPH_INSIGHTS_Q_BRIDGE__"

_CYCLE_QUERY_TIMEOUT_SEC = 8.0


@dataclass
class InsightItem:
    category: Literal["isolated", "circular_dep", "cross_layer", "low_cohesion", "bridge"]
    severity: Literal["critical", "warning", "info"]
    title: str
    description: str
    entities: list[str]
    suggestion: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InsightsReport:
    insights: list[InsightItem]
    graph_stats: dict[str, int]
    analyzed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "insights": [i.to_dict() for i in self.insights],
            "graph_stats": dict(self.graph_stats),
            "analyzed_at": self.analyzed_at,
        }


class GraphInsightsService:
    """Detects architecture anomalies for one repository using the FalkorDB graph."""

    def __init__(self, store: FalkorDBStore) -> None:
        self._store = store

    async def analyze(self, repository: str) -> InsightsReport:
        analyzed_at = datetime.now(timezone.utc).isoformat()
        graph_stats = await self._collect_graph_stats(repository)

        isolated_task = self._find_isolated_entities(repository)
        cycles_task = self._find_circular_dependencies(repository)
        cross_task = self._find_cross_layer_violations(repository)
        cohesion_task = self._compute_module_cohesion(repository)
        bridge_task = self._find_bridge_nodes(repository)

        isolated, cycles, cross, cohesion, bridges = await asyncio.gather(
            isolated_task,
            cycles_task,
            cross_task,
            cohesion_task,
            bridge_task,
        )

        insights: list[InsightItem] = []
        insights.extend(isolated)
        insights.extend(cycles)
        insights.extend(cross)
        insights.extend(cohesion)
        insights.extend(bridges)

        return InsightsReport(
            insights=insights,
            graph_stats=graph_stats,
            analyzed_at=analyzed_at,
        )

    async def _collect_graph_stats(self, repository: str) -> dict[str, int]:
        cypher = f"""
// {_Q_STATS}
MATCH (c:Class) WHERE c.repository = ${_REPO_PARAM}
WITH count(c) AS class_count
MATCH (m:Module) WHERE m.repository = ${_REPO_PARAM}
WITH class_count, count(m) AS module_count
OPTIONAL MATCH (a)-[r:CALLS]->(b)
WHERE (a:Class OR a:Function) AND (b:Class OR b:Function)
  AND a.repository = ${_REPO_PARAM} AND b.repository = ${_REPO_PARAM}
WITH class_count, module_count, count(r) AS calls_same_repo
OPTIONAL MATCH (x:Module)-[i:IMPORTS]->(y:Module)
WHERE x.repository = ${_REPO_PARAM} AND y.repository = ${_REPO_PARAM}
RETURN class_count, module_count, calls_same_repo, count(i) AS imports_same_repo
""".strip()
        params = {_REPO_PARAM: repository}
        rows = await self._store.execute_query(cypher, params)
        if not rows.data:
            return {
                "class_count": 0,
                "module_count": 0,
                "calls_same_repo": 0,
                "imports_same_repo": 0,
            }
        r0 = rows.data[0]
        return {
            "class_count": int(r0.get("class_count") or 0),
            "module_count": int(r0.get("module_count") or 0),
            "calls_same_repo": int(r0.get("calls_same_repo") or 0),
            "imports_same_repo": int(r0.get("imports_same_repo") or 0),
        }

    async def _find_isolated_entities(self, repository: str) -> list[InsightItem]:
        cypher = f"""
// {_Q_ISOLATED}
MATCH (n:Class)
WHERE n.repository = ${_REPO_PARAM}
  AND NOT (n)-[:CALLS|INHERITS|IMPORTS|CONTAINS]-()
RETURN n.name AS name, coalesce(n.fqn, '') AS fqn
""".strip()
        rows = await self._store.execute_query(cypher, {_REPO_PARAM: repository})
        out: list[InsightItem] = []
        for row in rows.data:
            name = str(row.get("name") or "")
            fqn = str(row.get("fqn") or "")
            label = fqn if fqn else name
            out.append(
                InsightItem(
                    category="isolated",
                    severity="warning",
                    title=f"Isolated class: {name or label}",
                    description=(
                        "This class has no CALLS, INHERITS, IMPORTS, or CONTAINS relationships "
                        "in either direction — it may be dead code, a data holder, or missing edges."
                    ),
                    entities=[label],
                    suggestion=(
                        "Verify the class is still used; if it is, ensure callers and module "
                        "structure are indexed so relationships appear in the graph."
                    ),
                ),
            )
        return out

    async def _find_circular_dependencies(self, repository: str) -> list[InsightItem]:
        cypher = f"""
// {_Q_CYCLES}
MATCH p = (a:Module)-[:IMPORTS*2..5]->(a)
WHERE a.repository = ${_REPO_PARAM}
WITH nodes(p) AS ns
RETURN [x IN ns | coalesce(x.name, x.path, '')] AS module_path
LIMIT 50
""".strip()
        params = {_REPO_PARAM: repository}
        try:
            rows: QueryResultWrapper = await asyncio.wait_for(
                self._store.execute_query(cypher, params),
                timeout=_CYCLE_QUERY_TIMEOUT_SEC,
            )
        except TimeoutError:
            log.warning("graph_insights_cycle_query_timeout", repository=repository)
            return [
                InsightItem(
                    category="circular_dep",
                    severity="warning",
                    title="Module import cycle detection timed out",
                    description=(
                        f"Cycle detection exceeded {_CYCLE_QUERY_TIMEOUT_SEC:.0f}s — "
                        "the graph may be very dense; try narrowing the repository scope."
                    ),
                    entities=[],
                    suggestion="Re-run analysis after indexing completes, or increase graph resources.",
                ),
            ]
        except Exception as exc:
            log.warning("graph_insights_cycle_query_error", repository=repository, error=str(exc))
            return [
                InsightItem(
                    category="circular_dep",
                    severity="info",
                    title="Module import cycle detection failed",
                    description=f"Cycle detection query encountered an error: {type(exc).__name__}",
                    entities=[],
                    suggestion="Check FalkorDB connectivity and retry.",
                ),
            ]

        seen: set[tuple[str, ...]] = set()
        out: list[InsightItem] = []
        for row in rows.data:
            path = row.get("module_path")
            if not isinstance(path, list):
                continue
            parts = [str(p) for p in path if p]
            if len(parts) < 2:
                continue
            key = tuple(parts)
            if key in seen:
                continue
            seen.add(key)
            desc = " → ".join(parts)
            out.append(
                InsightItem(
                    category="circular_dep",
                    severity="critical",
                    title="Module import cycle",
                    description=f"Cyclic IMPORTS among modules: {desc}",
                    entities=parts,
                    suggestion=(
                        "Break the cycle by introducing an abstraction module, "
                        "moving shared types to a lower layer, or using dependency inversion."
                    ),
                ),
            )
        return out

    async def _find_cross_layer_violations(self, repository: str) -> list[InsightItem]:
        cypher = f"""
// {_Q_CROSS_LAYER}
MATCH (ctrl:Class)-[:CALLS]->(repo:Class)
WHERE ctrl.repository = ${_REPO_PARAM}
  AND 'http_controller' IN coalesce(ctrl.semantic_roles, [])
  AND 'repository' IN coalesce(repo.semantic_roles, [])
RETURN ctrl.name AS ctrl_name, repo.name AS repo_name,
       coalesce(ctrl.fqn, '') AS ctrl_fqn, coalesce(repo.fqn, '') AS repo_fqn
""".strip()
        rows = await self._store.execute_query(cypher, {_REPO_PARAM: repository})
        out: list[InsightItem] = []
        for row in rows.data:
            cn = str(row.get("ctrl_name") or "")
            rn = str(row.get("repo_name") or "")
            cf = str(row.get("ctrl_fqn") or "")
            rf = str(row.get("repo_fqn") or "")
            out.append(
                InsightItem(
                    category="cross_layer",
                    severity="warning",
                    title=f"Controller calls repository directly: {cn} → {rn}",
                    description=(
                        "An HTTP controller class calls a repository class without going through "
                        "a service layer, which often couples web handling to persistence."
                    ),
                    entities=[cf or cn, rf or rn],
                    suggestion=(
                        "Route persistence access through a service or use-case class "
                        "so controllers stay thin and transactional boundaries stay explicit."
                    ),
                ),
            )
        return out

    async def _compute_module_cohesion(self, repository: str) -> list[InsightItem]:
        cypher = f"""
// {_Q_COHESION}
MATCH (m:Module) WHERE m.repository = ${_REPO_PARAM}
MATCH (m)-[:CONTAINS]->(c1:Class)
MATCH (m)-[:CONTAINS]->(c2:Class)
WHERE id(c1) <> id(c2) AND (c1)-[:CALLS]->(c2)
WITH m, count(*) AS internal_calls
MATCH (m)-[:CONTAINS]->(all:Class)
WITH m, internal_calls, count(DISTINCT all) AS class_count
WHERE class_count > 1
WITH m, internal_calls, class_count,
  toFloat(internal_calls) / toFloat(class_count * (class_count - 1)) AS cohesion
WHERE cohesion < 0.15
RETURN coalesce(m.name, '') AS module_name, coalesce(m.path, '') AS module_path,
       internal_calls, class_count, cohesion
""".strip()
        rows = await self._store.execute_query(cypher, {_REPO_PARAM: repository})
        out: list[InsightItem] = []
        for row in rows.data:
            mn = str(row.get("module_name") or "")
            mp = str(row.get("module_path") or "")
            ic = int(row.get("internal_calls") or 0)
            cc = int(row.get("class_count") or 0)
            coh = float(row.get("cohesion") or 0.0)
            label = mp or mn or "module"
            out.append(
                InsightItem(
                    category="low_cohesion",
                    severity="info",
                    title=f"Low intra-module cohesion: {label}",
                    description=(
                        f"Module cohesion {coh:.3f} (internal class-to-class CALLS / "
                        f"(n·(n−1))) is below 0.15 with {cc} classes and {ic} internal call edges."
                    ),
                    entities=[label],
                    suggestion=(
                        "Consider splitting the module, colocating highly coupled classes, "
                        "or clarifying boundaries so related behavior clusters together."
                    ),
                ),
            )
        return out

    async def _find_bridge_nodes(self, repository: str) -> list[InsightItem]:
        cypher = f"""
// {_Q_BRIDGE}
MATCH (c:Class)
WHERE c.repository = ${_REPO_PARAM}
MATCH (c)-[:CALLS|INHERITS]-(other:Class)
WHERE other.repository = ${_REPO_PARAM} AND other.architecture_layer IS NOT NULL
WITH c, collect(DISTINCT other.architecture_layer) AS layers
WHERE size(layers) >= 3
RETURN c.name AS name, coalesce(c.fqn, '') AS fqn, layers
""".strip()
        rows = await self._store.execute_query(cypher, {_REPO_PARAM: repository})
        out: list[InsightItem] = []
        for row in rows.data:
            name = str(row.get("name") or "")
            fqn = str(row.get("fqn") or "")
            layers = row.get("layers") or []
            layer_strs = [str(x) for x in layers] if isinstance(layers, list) else []
            ent = fqn if fqn else name
            out.append(
                InsightItem(
                    category="bridge",
                    severity="info",
                    title=f"Multi-layer bridge class: {name}",
                    description=(
                        "This class is connected via CALLS or INHERITS to classes in "
                        f"{len(layer_strs)} architecture layers: {', '.join(layer_strs)}."
                    ),
                    entities=[ent],
                    suggestion=(
                        "Review whether this class should be split or whether layering rules "
                        "need updating so cross-cutting concerns stay maintainable."
                    ),
                ),
            )
        return out
