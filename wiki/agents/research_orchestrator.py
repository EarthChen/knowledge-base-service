from __future__ import annotations

import re
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

DECOMPOSE_SYSTEM = (
    "You break a research question into focused sub-questions that can be "
    "investigated independently. Respond with 2–4 lines only: one "
    "sub-question per line. No introduction, conclusion, or extra commentary."
)

EXPLORE_SYSTEM = (
    "You are a research assistant. Use the available tools to gather "
    "evidence and facts relevant to the user's sub-question."
)

ANSWER_SYSTEM = (
    "You answer a single sub-question using only the evidence provided in "
    "the user message. Be concise and factual; cite or summarize the evidence "
    "you rely on."
)

SYNTHESIS_SYSTEM = (
    "You combine multiple partial answers into one comprehensive, well-structured "
    "response to the original question. Resolve contradictions if present; "
    "otherwise integrate the material clearly."
)


def _parse_sub_questions(text: str, *, max_items: int = 4) -> list[str]:
    """Extract non-empty sub-question lines; strip bullets and numbering."""
    if not text or not str(text).strip():
        return []
    out: list[str] = []
    for line in str(text).splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^(\d+[\.\)]\s*|[\-\*•]\s*)", "", s).strip()
        if s:
            out.append(s)
        if len(out) >= max_items:
            break
    return out


class ResearchOrchestrator:
    """Decompose → N× agent exploration → Synthesize."""

    def __init__(self, agent: Any) -> None:
        self._agent = agent

    async def decompose(self, question: str) -> list[str]:
        """Break question into sub-questions using agent.run_generation."""
        raw = await self._agent.run_generation(DECOMPOSE_SYSTEM, question)
        parsed = _parse_sub_questions(raw)
        if not parsed:
            log.warning(
                "research_decompose_fallback",
                reason="empty_or_unparsed",
                question_preview=question[:240],
            )
            return [question]
        return parsed

    async def explore_sub_question(self, sub_question: str, memory: Any) -> Any:
        """Run tool loop to gather evidence for a sub-question."""
        return await self._agent.run_tool_loop(EXPLORE_SYSTEM, sub_question, memory)

    async def answer_sub_question(self, sub_question: str, memory: Any) -> str:
        """Generate answer from gathered evidence."""
        findings = self._agent.memory_to_prompt(memory)
        user_prompt = (
            f"Sub-question:\n{sub_question}\n\n"
            f"Evidence from tools:\n{findings}"
        )
        return await self._agent.run_generation(ANSWER_SYSTEM, user_prompt)

    async def synthesize(
        self,
        question: str,
        sub_questions: list[str],
        sub_answers: list[str],
    ) -> str:
        """Combine sub-answers into comprehensive final answer."""
        parts = [f"Original question:\n{question}\n\nSub-questions and partial answers:\n"]
        for i, (sq, sa) in enumerate(zip(sub_questions, sub_answers), start=1):
            parts.append(f"\n{i}. {sq}\n   Partial answer: {sa}\n")
        user_prompt = "".join(parts)
        return await self._agent.run_generation(SYNTHESIS_SYSTEM, user_prompt)

    async def research(self, question: str) -> dict[str, Any]:
        """Full pipeline: decompose → explore → answer → synthesize."""
        sub_questions = await self.decompose(question)
        sub_answers: list[str] = []
        for sq in sub_questions:
            memory = self._agent.create_memory()
            memory = await self.explore_sub_question(sq, memory)
            answer = await self.answer_sub_question(sq, memory)
            sub_answers.append(answer)
        synthesis = await self.synthesize(question, sub_questions, sub_answers)
        return {
            "question": question,
            "sub_questions": sub_questions,
            "sub_answers": sub_answers,
            "synthesis": synthesis,
        }
