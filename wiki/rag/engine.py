from __future__ import annotations

import json
import re
from typing import Any, Literal, Protocol, TypedDict

from langgraph.graph import END, StateGraph

from wiki.rag.events import rag_sse_append
from wiki.rag.protocol import Chunk, RetrievalScope, Retriever


class RAGState(TypedDict, total=False):
    question: str
    scope: RetrievalScope
    round: int
    max_rounds: int
    accumulated_context: list[Chunk]
    current_draft: str
    gaps: list[str]
    next_queries: list[str]
    confidence: float
    is_complete: bool
    sources: list[dict[str, Any]]
    sse_events: list[dict[str, Any]]


class _LLM(Protocol):
    async def complete(self, messages: list[dict[str, str]], **kwargs: Any) -> str: ...


def _parse_reflection(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        return {}


class IterativeRAGEngine:
    def __init__(
        self,
        *,
        retriever: Retriever,
        plan_llm: _LLM,
        generate_llm: _LLM,
        evaluate_llm: _LLM | None = None,
    ):
        self._retriever = retriever
        self._plan_llm = plan_llm
        self._gen_llm = generate_llm
        self._eval_llm = evaluate_llm or generate_llm
        self._graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(RAGState)

        async def initial_search(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            scope = state["scope"]
            chunks = await self._retriever.retrieve([q], scope, limit=10)
            ev = rag_sse_append(state, "searching", {"queries": [q], "sources_count": len(chunks)})
            return {"accumulated_context": chunks, "round": 1, "sse_events": ev}

        async def generate_draft(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            ctx = state.get("accumulated_context") or []
            ctx_text = "\n\n".join(f"### {c.title}\n{c.content}" for c in ctx[:50])
            prompt = (
                f"Question:\n{q}\n\nContext:\n{ctx_text}\n\n"
                "Reply with ONLY valid JSON: "
                '{"answer":string,"gaps":string[],"next_queries":string[],"confidence":number,"is_complete":bool}'
            )
            raw = await self._gen_llm.complete([{"role": "user", "content": prompt}])
            data = _parse_reflection(raw)
            answer = str(data.get("answer") or raw)
            gaps = [str(x) for x in data.get("gaps") or [] if str(x).strip()]
            nq = [str(x) for x in data.get("next_queries") or [] if str(x).strip()]
            try:
                conf = float(data.get("confidence", 0.5))
            except (TypeError, ValueError):
                conf = 0.5
            is_complete = bool(data.get("is_complete", False))
            if conf >= 0.85 and not is_complete:
                is_complete = True
            ev = rag_sse_append(
                state,
                "draft",
                {"round": state.get("round", 1), "content": answer[:2000], "confidence": conf},
            )
            return {
                "current_draft": answer,
                "gaps": gaps,
                "next_queries": nq,
                "confidence": conf,
                "is_complete": is_complete,
                "sse_events": ev,
            }

        async def dynamic_retrieve(state: RAGState) -> dict[str, Any]:
            nq = state.get("next_queries") or []
            scope = state["scope"]
            new_chunks = await self._retriever.retrieve(nq, scope, limit=10) if nq else []
            merged = list(state.get("accumulated_context") or [])
            merged.extend(new_chunks)
            ev = rag_sse_append(state, "refining", {"round": state.get("round", 1), "reason": "follow-up retrieval"})
            return {
                "accumulated_context": merged,
                "round": int(state.get("round", 1)) + 1,
                "sse_events": ev,
            }

        async def finalize(state: RAGState) -> dict[str, Any]:
            ev = rag_sse_append(
                state,
                "done",
                {
                    "final_answer": state.get("current_draft", ""),
                    "total_rounds": state.get("round", 1),
                    "confidence": state.get("confidence", 0.0),
                },
            )
            return {"sse_events": ev}

        graph.add_node("initial_search", initial_search)
        graph.add_node("generate_draft", generate_draft)
        graph.add_node("dynamic_retrieve", dynamic_retrieve)
        graph.add_node("finalize", finalize)

        graph.set_entry_point("initial_search")
        graph.add_edge("initial_search", "generate_draft")

        def route_after_draft(s: RAGState) -> Literal["finalize", "dynamic_retrieve"]:
            if s.get("is_complete") or int(s.get("round", 1)) >= int(s.get("max_rounds", 7)):
                return "finalize"
            if not (s.get("next_queries") or []):
                return "finalize"
            return "dynamic_retrieve"

        graph.add_conditional_edges("generate_draft", route_after_draft)
        graph.add_edge("dynamic_retrieve", "generate_draft")
        graph.add_edge("finalize", END)
        return graph.compile()

    async def arun(self, *, question: str, scope: RetrievalScope, max_rounds: int = 7) -> RAGState:
        init: RAGState = {
            "question": question,
            "scope": scope,
            "round": 0,
            "max_rounds": max_rounds,
            "accumulated_context": [],
            "current_draft": "",
            "gaps": [],
            "next_queries": [],
            "confidence": 0.0,
            "is_complete": False,
            "sources": [],
            "sse_events": [],
        }
        out = await self._graph.ainvoke(init)
        return out
