"""Graph-level architecture insights — anomalies and quality signals."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from core.log import get_logger
from store.analysis_store import AnalysisStore
from store.falkordb_store import FalkorDBStore, QueryResultWrapper

log = get_logger(__name__)

_CYCLE_QUERY_TIMEOUT_SEC = 8.0

_EMPTY_STATS: dict[str, int] = {
    "class_count": 0,
    "module_count": 0,
    "calls_same_repo": 0,
    "imports_same_repo": 0,
}


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

    def __init__(
        self,
        store: FalkorDBStore,
        analysis_store: AnalysisStore | None = None,
    ) -> None:
        self._analysis = analysis_store or AnalysisStore(store)

    async def _resolve_repositories(self, repository: str, business_id: str | None) -> list[str]:
        """Resolve the actual code repositories to query.

        If ``business_id`` is set, WikiSpace → WikiPage yields distinct code ``repository``
        values. Otherwise ``repository`` path is used as a single-repo filter.
        """
        if business_id:
            wrapped = await self._analysis.resolve_code_repositories_from_business_wiki(
                business_id,
            )
            if not wrapped.data:
                return []
            r0 = wrapped.data[0]
            raw = r0.get("repos")
            if raw is None or not isinstance(raw, list):
                return []
            return [str(x) for x in raw if x is not None and str(x).strip() != ""]
        if repository.strip():
            return [repository]
        return []

    async def analyze(self, repository: str, business_id: str | None = None) -> InsightsReport:
        analyzed_at = datetime.now(timezone.utc).isoformat()
        repos = await self._resolve_repositories(repository, business_id)
        if not repos:
            return InsightsReport(
                insights=[],
                graph_stats=dict(_EMPTY_STATS),
                analyzed_at=analyzed_at,
            )

        graph_stats = await self._collect_graph_stats(repos)

        isolated_task = self._find_isolated_entities(repos)
        cycles_task = self._find_circular_dependencies(repos)
        cross_task = self._find_cross_layer_violations(repos)
        cohesion_task = self._compute_module_cohesion(repos)
        bridge_task = self._find_bridge_nodes(repos)

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

    async def _collect_graph_stats(self, repositories: list[str]) -> dict[str, int]:
        rows = await self._analysis.collect_graph_stats(repositories)
        if not rows.data:
            return dict(_EMPTY_STATS)
        r0 = rows.data[0]
        return {
            "class_count": int(r0.get("class_count") or 0),
            "module_count": int(r0.get("module_count") or 0),
            "calls_same_repo": int(r0.get("calls_same_repo") or 0),
            "imports_same_repo": int(r0.get("imports_same_repo") or 0),
        }

    async def _find_isolated_entities(self, repositories: list[str]) -> list[InsightItem]:
        rows = await self._analysis.find_isolated_entities(repositories)
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

    async def _find_circular_dependencies(self, repositories: list[str]) -> list[InsightItem]:
        scope_label = ",".join(repositories)
        try:
            rows: QueryResultWrapper = await asyncio.wait_for(
                self._analysis.find_circular_dependencies(repositories),
                timeout=_CYCLE_QUERY_TIMEOUT_SEC,
            )
        except TimeoutError:
            log.warning("graph_insights_cycle_query_timeout", repositories=scope_label)
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
            log.warning("graph_insights_cycle_query_error", repositories=scope_label, error=str(exc))
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

    async def _find_cross_layer_violations(self, repositories: list[str]) -> list[InsightItem]:
        rows = await self._analysis.find_cross_layer_violations(repositories)
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

    async def _compute_module_cohesion(self, repositories: list[str]) -> list[InsightItem]:
        rows = await self._analysis.compute_module_cohesion_insights(repositories)
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

    async def _find_bridge_nodes(self, repositories: list[str]) -> list[InsightItem]:
        rows = await self._analysis.find_bridge_nodes(repositories)
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

