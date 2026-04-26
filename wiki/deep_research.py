"""Multi-turn deep research mode for comprehensive wiki Q&A."""
from __future__ import annotations

from typing import Any

from log import get_logger

log = get_logger(__name__)


class DeepResearchService:
    def __init__(self, ask_service: Any) -> None:
        self._ask = ask_service

    async def decompose_question(self, question: str) -> list[str]:
        """Break a complex question into sub-questions."""
        # decomposition_prompt reserved for a future LLM call:
        # "Break this question into 2-4 specific sub-questions ... one per line."
        # For now, use simple heuristic decomposition
        # In production, this would use an LLM
        parts = question.split(" and ")
        if len(parts) >= 2:
            return [p.strip() + "?" if not p.strip().endswith("?") else p.strip() for p in parts]
        return [question]

    async def research(
        self,
        question: str,
        repository: str,
        business_id: str = "default",
        max_depth: int = 2,
    ) -> dict[str, Any]:
        """Perform multi-turn deep research on a question."""
        _ = repository, business_id, self._ask  # wire for future ask_stream integration
        sub_questions = await self.decompose_question(question)

        sub_answers: list[dict[str, str]] = []
        for sq in sub_questions:
            try:
                # Collect answer chunks from ask_stream if available
                answer_text = f"[Research finding for: {sq}]"
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
