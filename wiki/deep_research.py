"""Multi-turn deep research mode for comprehensive wiki Q&A."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from core.log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _LLMDecomposePort(Protocol):
    async def complete(self, messages: list[dict], **kwargs: Any) -> str: ...


class DeepResearchService:
    def __init__(
        self,
        rag_engine: Any,
        llm: _LLMDecomposePort | Any | None = None,
        *,
        agent: Any | None = None,
    ) -> None:
        self._engine = rag_engine
        self._llm = llm
        self._agent = agent
        self._use_agent = agent is not None

    async def decompose_question(self, question: str) -> list[str]:
        """Break a complex question into sub-questions (LLM when configured, else heuristic)."""
        if self._llm is not None and question and question.strip():
            try:
                messages = [
                    {
                        "role": "user",
                        "content": (
                            "Break the following into 2-4 specific sub-questions, one per line. "
                            "Output only the sub-questions, no numbering or bullets.\n\n"
                            f"{question.strip()}"
                        ),
                    }
                ]
                text = await self._llm.complete(messages)
                lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
                if 1 <= len(lines) <= 8:
                    return lines
            except Exception:
                log.warning("deep_research_decompose_llm_failed", exc_info=True)
        parts = question.split(" and ")
        if len(parts) >= 2:
            return [p.strip() for p in parts if p.strip()]
        return [question]

    async def _synthesize(
        self,
        question: str,
        sub_questions: list[str],
        sub_answers: list[str],
    ) -> str:
        if self._llm is None:
            return "\n\n".join(sub_answers)
        combined = "\n\n".join(
            f"### {sq}\n{sa}" for sq, sa in zip(sub_questions, sub_answers)
        )
        messages = [
            {
                "role": "user",
                "content": (
                    f"Original question: {question}\n\n"
                    f"Sub-answers:\n{combined}\n\n"
                    "Synthesize a comprehensive answer."
                ),
            }
        ]
        try:
            return await self._llm.complete(messages)
        except Exception:
            return "\n\n".join(sub_answers)

    async def _research_with_agent(self, question: str) -> dict[str, Any]:
        """Agent-based research using ResearchOrchestrator."""
        from wiki.agents.research_orchestrator import ResearchOrchestrator

        orchestrator = ResearchOrchestrator(agent=self._agent)
        return await orchestrator.research(question)

    async def research(
        self,
        question: str,
        repository: str = "",
        business_id: str = "",
        *,
        max_depth: int = 3,
    ) -> dict[str, Any]:
        """Decompose, run iterative RAG per sub-question, then synthesize."""
        if self._use_agent:
            return await self._research_with_agent(question)
        _ = max_depth  # reserved for future depth-limited decomposition
        sub_questions = await self.decompose_question(question)

        from wiki.rag.protocol import RetrievalScope

        repo = (repository or "").strip()
        biz = (business_id or "").strip()
        if repo:
            scope = RetrievalScope(
                scope_type="repository",
                repository=repo,
                business_id=biz or None,
            )
        elif biz:
            scope = RetrievalScope(
                scope_type="business",
                business_id=biz,
            )
        else:
            scope = RetrievalScope(scope_type="global")

        sub_answers: list[str] = []
        for sq in sub_questions:
            try:
                state = await self._engine.arun(
                    question=sq,
                    scope=scope,
                    max_rounds=5,
                )
                sub_answers.append(str(state.get("current_draft", "")))
            except Exception:
                log.warning("deep_research_sub_question_failed", sub_question=sq, exc_info=True)
                sub_answers.append("")

        synthesis = await self._synthesize(question, sub_questions, sub_answers)
        return {
            "question": question,
            "sub_questions": sub_questions,
            "sub_answers": sub_answers,
            "synthesis": synthesis,
        }
