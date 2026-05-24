"""FlowDocAgent: business flow documentation with call chain tracing."""
from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
from wiki.quality_report import evaluate_quality

log = get_logger(__name__)

FLOW_CALL_CHAIN_CY = """
MATCH (caller)-[r:CALLS]->(callee)
WHERE caller.canonical_key IN $names OR callee.canonical_key IN $names
RETURN caller.canonical_key AS caller, callee.canonical_key AS callee,
       caller.file_path AS file_path
LIMIT 30
"""


class FlowDocAgent(DocOrchestrator):
    """Generates business flow documentation with call chain tracing.

    Focuses on step-by-step flow description, cross-module interactions,
    and data flow paths. Produces Mermaid sequence diagrams when possible.
    """

    def __init__(
        self,
        flow_name: str,
        domain_name: str,
        llm: Any,
        graph_store: Any,
        *,
        max_iterations: int = 3,
        repo_path: str | None = None,
        search_service: Any | None = None,
    ) -> None:
        from wiki.agent_prompts import AGENT_EXPLORE_SYSTEM, AGENT_WRITE_SYSTEM
        from wiki.page_agent import WikiPageAgent

        page_agent = WikiPageAgent(
            llm,
            graph_store,
            max_rounds=10,
            max_tool_calls=50,
            repo_path=repo_path,
            search_service=search_service,
        )
        super().__init__(
            agent=page_agent,
            name=f"{domain_name}/{flow_name}",
            max_iterations=max_iterations,
            explore_system_prompt=AGENT_EXPLORE_SYSTEM.format(max_rounds=10),
            write_system_prompt=AGENT_WRITE_SYSTEM,
        )
        self.flow_name = flow_name
        self.domain_name = domain_name
        self._page_agent = page_agent

    async def pre_fill(self, memory: Any, module_names: list[str]) -> None:
        """Seed call chain relationships from graph."""
        graph = self._page_agent._graph
        if not graph or not module_names:
            return
        try:
            result = await graph.execute_query(FLOW_CALL_CHAIN_CY, {"names": module_names})
            for row in (getattr(result, "data", None) or []):
                caller = str(row.get("caller", ""))
                callee = str(row.get("callee", ""))
                if caller and callee and hasattr(memory, "discovered_call_chains"):
                    memory.discovered_call_chains.append(f"{caller} → {callee}")
                elif caller and callee and hasattr(memory, "add"):
                    memory.add("call_chains", f"{caller} → {callee}")
        except Exception:
            log.warning("flow_pre_fill_failed", flow=self.flow_name, exc_info=True)

    async def evaluate(self, content: str, module_names: list[str]) -> QualityResult:
        qr = evaluate_quality(content, module_names)
        return QualityResult(
            coverage=qr.coverage,
            citation_density=qr.citation_density,
            context_gap_count=qr.context_gap_count,
            uncovered_modules=qr.uncovered_modules,
        )

    def is_acceptable(self, quality: QualityResult, iteration: int) -> bool:
        """Flow docs accept slightly lower coverage since they focus on paths."""
        if (
            quality.coverage >= 0.9
            and quality.citation_density >= 0.4
            and quality.context_gap_count == 0
        ):
            return True
        if iteration >= 2 and quality.coverage >= 0.8:
            return True
        if iteration >= 3:
            return True
        return False

    def post_process(
        self, content: str, module_names: list[str], memory: Any
    ) -> list[dict[str, Any]]:
        """Return a single flow page."""
        from wiki.path_conventions import domain_topic_path

        if not content:
            content = (
                f"# {self.flow_name}\n\n"
                "<!-- CONTEXT_GAP: Flow generation incomplete -->"
            )
        return [{
            "page_type": "business_flow",
            "title": self.flow_name,
            "path": domain_topic_path(self.domain_name, self.flow_name),
            "content": content,
            "diagrams": [],
            "source_locations": [],
            "metadata": {
                "node_count": 0,
                "edge_count": 0,
                "generation_mode": "agent",
                "domain": self.domain_name,
                "flow_name": self.flow_name,
            },
        }]
