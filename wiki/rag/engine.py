from __future__ import annotations

import inspect
import json
import re
from collections.abc import AsyncIterator
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from wiki.llm_port import LLMPort
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
    eval_suggestions: list[str]  # feedback from evaluate node


def _build_init_state(question: str, scope: RetrievalScope, max_rounds: int) -> RAGState:
    return {
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
        "eval_suggestions": [],
    }


def _is_arun_stream_callable(engine: Any) -> bool:
    """True when ``engine.arun_stream`` is a real async generator implementation (not a unittest mock)."""
    stream_meth = getattr(engine, "arun_stream", None)
    if stream_meth is None:
        return False
    fn = getattr(stream_meth, "__func__", stream_meth)
    try:
        fn = inspect.unwrap(fn)
    except Exception:
        pass
    return inspect.isasyncgenfunction(fn)


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
        llm: LLMPort | Any,
        model_strategy: Any | None = None,
    ):
        self._retriever = retriever
        self._llm = llm
        self._model_strategy = model_strategy
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
            gen_llm = self._llm
            if self._model_strategy:
                try:
                    gen_llm = await self._model_strategy.get_llm_port("rag_generate")
                except Exception:
                    pass
            raw = await gen_llm.complete([{"role": "user", "content": prompt}])
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

        async def plan(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            gaps = state.get("gaps", [])
            gaps_text = "\n".join(f"- {g}" for g in gaps) if gaps else "None identified"
            eval_suggestions = state.get("eval_suggestions", [])
            suggestions_text = "\n".join(f"- {s}" for s in eval_suggestions) if eval_suggestions else ""

            plan_llm = self._llm
            if self._model_strategy:
                try:
                    plan_llm = await self._model_strategy.get_llm_port("rag_plan")
                except Exception:
                    pass

            prompt = (
                f"Original question:\n{q}\n\n"
                f"Information gaps:\n{gaps_text}\n\n"
            )
            if suggestions_text:
                prompt += f"Previous evaluation feedback:\n{suggestions_text}\n\n"
            prompt += (
                "Decompose into 2-4 precise sub-queries to fill these gaps. "
                'Reply with ONLY valid JSON: {"sub_queries": ["query1", "query2", ...]}'
            )
            raw = await plan_llm.complete([{"role": "user", "content": prompt}])
            data = _parse_reflection(raw)
            sub_queries = [str(x) for x in data.get("sub_queries", []) if str(x).strip()]
            if not sub_queries:
                sub_queries = state.get("next_queries", [])

            ev = rag_sse_append(
                state,
                "planning",
                {
                    "round": state.get("round", 1),
                    "sub_queries": sub_queries,
                },
            )
            return {"next_queries": sub_queries, "sse_events": ev}

        async def evaluate(state: RAGState) -> dict[str, Any]:
            q = state["question"]
            draft = state.get("current_draft", "")

            eval_llm = self._llm
            if self._model_strategy:
                try:
                    eval_llm = await self._model_strategy.get_llm_port("rag_evaluate")
                except Exception:
                    pass

            prompt = (
                f"Question:\n{q}\n\n"
                f"Current answer:\n{draft}\n\n"
                "Evaluate this answer independently. Is it complete, accurate, and well-supported? "
                "Reply with ONLY valid JSON: "
                '{"score": number, "suggestions": ["improvement1"], "next_queries": ["query1"]}'
            )
            raw = await eval_llm.complete([{"role": "user", "content": prompt}])
            data = _parse_reflection(raw)

            try:
                score = float(data.get("score", 0.5))
            except (TypeError, ValueError):
                score = 0.5
            suggestions = [str(x) for x in data.get("suggestions", [])]
            nq = [str(x) for x in data.get("next_queries", []) if str(x).strip()]

            ev = rag_sse_append(
                state,
                "evaluating",
                {
                    "round": state.get("round", 1),
                    "score": score,
                    "suggestions": suggestions[:3],
                },
            )

            if score >= 0.85:
                return {
                    "is_complete": True,
                    "confidence": score,
                    "sse_events": ev,
                    "eval_suggestions": suggestions,
                }
            return {"next_queries": nq, "sse_events": ev, "eval_suggestions": suggestions}

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
        graph.add_node("plan", plan)
        graph.add_node("evaluate", evaluate)
        graph.add_node("finalize", finalize)

        graph.set_entry_point("initial_search")
        graph.add_edge("initial_search", "generate_draft")

        def route_after_draft(s: RAGState) -> str:
            if s.get("is_complete") or int(s.get("round", 1)) >= int(s.get("max_rounds", 7)):
                return "finalize"
            if not (s.get("next_queries") or []):
                return "finalize"
            if int(s.get("round", 1)) >= 3 and float(s.get("confidence", 0.0)) < 0.7:
                return "evaluate"
            if int(s.get("round", 1)) >= 2:
                return "plan"
            return "dynamic_retrieve"

        graph.add_conditional_edges(
            "generate_draft",
            route_after_draft,
            {
                "finalize": "finalize",
                "evaluate": "evaluate",
                "plan": "plan",
                "dynamic_retrieve": "dynamic_retrieve",
            },
        )
        graph.add_edge("dynamic_retrieve", "generate_draft")
        graph.add_edge("plan", "dynamic_retrieve")

        def route_after_evaluate(s: RAGState) -> str:
            if s.get("is_complete"):
                return "finalize"
            return "plan"

        graph.add_conditional_edges(
            "evaluate",
            route_after_evaluate,
            {"finalize": "finalize", "plan": "plan"},
        )
        graph.add_edge("finalize", END)
        return graph.compile()

    async def arun(self, *, question: str, scope: RetrievalScope, max_rounds: int = 7) -> RAGState:
        init = _build_init_state(question, scope, max_rounds)
        out = await self._graph.ainvoke(init)
        return out

    async def arun_stream(
        self,
        *,
        question: str,
        scope: RetrievalScope,
        max_rounds: int = 7,
    ) -> AsyncIterator[dict[str, Any]]:
        init = _build_init_state(question, scope, max_rounds)
        prev_events_len = 0
        prev_draft = ""
        last_state: RAGState | None = None
        async for state in self._graph.astream(init, stream_mode="values"):
            last_state = state
            events = list(state.get("sse_events") or [])
            if len(events) > prev_events_len:
                for ev in events[prev_events_len:]:
                    yield {"type": "sse", "data": ev}
                prev_events_len = len(events)
            draft = str(state.get("current_draft") or "")
            if draft != prev_draft:
                delta = draft[len(prev_draft) :] if draft.startswith(prev_draft) else draft
                yield {"type": "draft", "content": draft, "delta": delta}
                prev_draft = draft
        if last_state is not None:
            yield {
                "type": "done",
                "confidence": float(last_state.get("confidence", 0.0)),
                "round": int(last_state.get("round", 1)),
                "accumulated_context": list(last_state.get("accumulated_context") or []),
            }
