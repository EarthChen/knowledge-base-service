"""Multi-turn deep research mode for comprehensive wiki Q&A."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from log import get_logger

log = get_logger(__name__)


@runtime_checkable
class _LLMDecomposePort(Protocol):
    async def complete(self, messages: list[dict], **kwargs: Any) -> str: ...


class DeepResearchService:
    def __init__(
        self,
        ask_service: Any,
        llm: _LLMDecomposePort | Any | None = None,
        rag_engine: Any | None = None,
        use_iterative_rag: bool = False,
    ) -> None:
        self._ask = ask_service
        self._llm = llm
        self._rag_engine = rag_engine
        self._use_iterative_rag = use_iterative_rag

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
            return [p.strip() + "?" if not p.strip().endswith("?") else p.strip() for p in parts]
        return [question]

    async def _collect_ask_answer(
        self,
        repository: str,
        sub_question: str,
        business_id: str,
    ) -> str:
        if self._ask is None:
            return "[Q&A not available]"
        full_text = ""
        try:
            async for ev in self._ask.ask_stream(
                repository=repository,
                question=sub_question,
                scope=None,
                business_id=business_id,
            ):
                if ev.get("event") == "wiki-answer":
                    full_text = str((ev.get("data") or {}).get("content", ""))
        except Exception:
            log.warning("deep_research_ask_stream_failed", sub_question=sub_question, exc_info=True)
            return "[Error retrieving answer]"
        return full_text

    async def research(
        self,
        question: str,
        repository: str,
        business_id: str = "default",
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Perform multi-turn deep research on a question."""
        if self._ask is None:
            return {
                "question": question,
                "sub_questions": [],
                "synthesis": "Wiki Q&A is not available (ask service not configured).",
                "depth": max_depth,
            }

        sub_questions = await self.decompose_question(question)

        if self._use_iterative_rag and self._rag_engine is not None:
            from wiki.rag.protocol import RetrievalScope

            scope = RetrievalScope(scope_type="global")
            sub_answers = []
            for sq in sub_questions:
                state = await self._rag_engine.arun(question=sq, scope=scope, max_rounds=5)
                sub_answers.append({"question": sq, "answer": state.get("current_draft", "")})

            synthesis = ""
            if self._llm is not None:
                try:
                    synth_prompt = (
                        f"Original question: {question}\n\n"
                        "Sub-question answers:\n"
                        + "\n".join(f"Q: {sa['question']}\nA: {sa['answer']}" for sa in sub_answers)
                        + "\n\nSynthesize a comprehensive answer."
                    )
                    synthesis = await self._llm.complete(
                        [{"role": "user", "content": synth_prompt}]
                    )
                except Exception:
                    log.warning("deep_research_synthesis_failed", exc_info=True)
                    synthesis = "\n\n".join(sa["answer"] for sa in sub_answers)
            else:
                synthesis = "\n\n".join(sa["answer"] for sa in sub_answers)

            return {
                "question": question,
                "sub_questions": [sa["question"] for sa in sub_answers],
                "sub_answers": sub_answers,
                "synthesis": synthesis,
                "iterative_rag": True,
            }

        sub_answers: list[dict[str, str]] = []
        for sq in sub_questions:
            try:
                answer_text = await self._collect_ask_answer(repository, sq, business_id)
                sub_answers.append({"question": sq, "answer": answer_text})
            except Exception:  # noqa: BLE001
                log.warning("deep_research_sub_question_failed", sub_question=sq, exc_info=True)
                sub_answers.append({"question": sq, "answer": "[Error retrieving answer]"})

        synthesis = self._synthesize(question, sub_answers)

        return {
            "question": question,
            "sub_questions": sub_answers,
            "synthesis": synthesis,
            "depth": max_depth,
        }

    def _synthesize(self, question: str, sub_answers: list[dict[str, str]]) -> str:
        """Combine sub-answers into a coherent synthesis."""
        if not sub_answers:
            return "No research findings available."

        parts: list[str] = [f"## Research: {question}\n"]
        for i, sa in enumerate(sub_answers, 1):
            parts.append(f"### Finding {i}: {sa['question']}")
            parts.append(sa["answer"])
            parts.append("")

        return "\n".join(parts)
