"""TopicDocAgent: deep-dive documentation for a specific topic within a domain."""

from __future__ import annotations

from typing import Any

from core.log import get_logger
from wiki.agents.doc_orchestrator import DocOrchestrator, QualityResult
from wiki.quality_report import evaluate_quality

log = get_logger(__name__)


class TopicDocAgent(DocOrchestrator):
    """Focused, deep-dive documentation for one topic within a domain."""

    def __init__(
        self,
        topic_name: str,
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
            max_rounds=12,
            max_tool_calls=60,
            repo_path=repo_path,
            search_service=search_service,
        )
        super().__init__(
            agent=page_agent,
            name=f"{domain_name}/{topic_name}",
            max_iterations=max_iterations,
            explore_system_prompt=AGENT_EXPLORE_SYSTEM.format(max_rounds=12),
            write_system_prompt=AGENT_WRITE_SYSTEM,
        )
        self.topic_name = topic_name
        self.domain_name = domain_name
        self._page_agent = page_agent

    async def pre_fill(self, memory: Any, module_names: list[str]) -> None:
        """Seed code snippets for the topic's module subset."""
        graph = self._page_agent._graph
        if not graph or not module_names:
            return
        try:
            from wiki.cypher_queries import SNIPPETS_CY

            result = await graph.execute_query(
                SNIPPETS_CY, {"names": module_names, "valid_pairs": []},
            )
            for row in (getattr(result, "data", None) or []):
                func_name = str(row.get("func_name", ""))
                snippet = str(row.get("snippet", "")).strip()
                file_path = str(row.get("file_path", ""))
                if snippet and hasattr(memory, "code_snippets"):
                    memory.code_snippets.append(f"[{func_name} @ {file_path}]\n{snippet}")
        except Exception:
            log.warning("topic_pre_fill_failed", topic=self.topic_name, exc_info=True)

    async def evaluate(self, content: str, module_names: list[str]) -> QualityResult:
        qr = evaluate_quality(content, module_names)
        return QualityResult(
            coverage=qr.coverage,
            citation_density=qr.citation_density,
            context_gap_count=qr.context_gap_count,
            uncovered_modules=qr.uncovered_modules,
        )

    def is_acceptable(self, quality: QualityResult, iteration: int) -> bool:
        """Stricter: require 0.95 coverage or 0.9 after 2 iterations."""
        if (
            quality.coverage >= 0.95
            and quality.citation_density >= 0.5
            and quality.context_gap_count == 0
        ):
            return True
        if iteration >= 2 and quality.coverage >= 0.9:
            return True
        if iteration >= 3:
            if quality.coverage >= 0.7:
                self._last_accept_was_forced = True
                log.warning(
                    "quality_forced_accept",
                    coverage=quality.coverage,
                    iteration=iteration,
                )
                return True
            return False
        return False

    def post_process(
        self, content: str, module_names: list[str], memory: Any
    ) -> list[dict[str, Any]]:
        """Return a single topic page (no splitting)."""
        from wiki.path_conventions import domain_topic_path

        if not content:
            content = f"# {self.topic_name}\n\n<!-- CONTEXT_GAP: Topic generation incomplete -->"
        return [{
            "page_type": "topic",
            "title": self.topic_name,
            "path": domain_topic_path(self.domain_name, self.topic_name),
            "content": content,
            "diagrams": [],
            "source_locations": [],
            "metadata": {
                "node_count": 0,
                "edge_count": 0,
                "generation_mode": "agent",
                "domain": self.domain_name,
            },
        }]
