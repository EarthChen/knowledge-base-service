"""AskOrchestrator: tool-based Q&A using CodeAgent exploration."""

from __future__ import annotations

from typing import Any

from core.log import get_logger

log = get_logger(__name__)

ASK_EXPLORE_SYSTEM = (
    "You are a code intelligence assistant. Use the available tools to find "
    "information relevant to answering the user's question. Search for modules, "
    "read source code, trace call chains, and gather concrete evidence."
)

ASK_ANSWER_SYSTEM = (
    "You are a technical assistant. Based on the code intelligence findings provided, "
    "give a clear, accurate, and concise answer to the user's question. "
    "Reference specific modules, functions, and files when possible. "
    "If the findings are insufficient, say so honestly."
)


class AskOrchestrator:
    """Tool-based Q&A: explore code graph, then generate answer."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def ask(self, question: str) -> dict[str, Any]:
        """Explore code via tools, then generate a grounded answer.

        Returns: {answer: str, sources: list[str]}
        """
        memory = self._agent.create_memory()
        memory = await self._agent.run_tool_loop(
            ASK_EXPLORE_SYSTEM, question, memory
        )

        memory_text = self._agent.memory_to_prompt(memory)
        user_prompt = (
            f"Question: {question}\n\nCode intelligence findings:\n{memory_text}"
        )
        answer = await self._agent.run_generation(ASK_ANSWER_SYSTEM, user_prompt)

        sources = self._extract_sources(memory)
        return {"answer": answer, "sources": sources}

    def _extract_sources(self, memory: Any) -> list[str]:
        """Extract source references from memory entries."""
        sources = []
        if hasattr(memory, "entries"):
            for _, values in memory.entries.items():
                for val in values:
                    if len(val) > 10:
                        sources.append(val[:200])
        return sources[:10]
