"""Dashboard LLM-enhanced deep search engine.

Uses a simplified ReAct pattern: plan → execute sub-queries → synthesize.
Designed for Dashboard users who need natural-language search with
LLM-powered query understanding and result synthesis.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

import json_repair

from config import get_settings

if TYPE_CHECKING:
    from llm.gateway_client import RepoTaskManager
    from llm.provider import LLMProvider
    from query.graph_query import GraphQueryService
    from query.hybrid_query import HybridQueryService

logger = logging.getLogger(__name__)


def _truncate_for_synthesis(results_text: str, max_tokens: int) -> str:
    """Cap JSON payload using the same ``len(text) // 4`` heuristic as wiki token estimates."""
    if max_tokens <= 0:
        return ""
    estimated = len(results_text) // 4
    if estimated <= max_tokens:
        return results_text
    return results_text[: max_tokens * 4]


def _extract_first_brace_json_slice(candidate: str) -> str | None:
    """Return the first balanced `{...}` substring, or None."""
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return candidate[start : i + 1]
    return None


def _legacy_parse_json_object_brace_only(candidate: str) -> dict[str, Any] | None:
    """Original behavior: brace-counting plus stdlib json.loads only (no repair)."""
    start = candidate.find("{")
    if start < 0:
        return None
    depth = 0
    for i in range(start, len(candidate)):
        ch = candidate[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(candidate[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


def _parse_json_object_from_llm(text: str) -> dict[str, Any] | None:
    """Parse a JSON object from LLM text (fenced code or raw)."""
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)```", text, re.DOTALL)
    candidate = code_block.group(1).strip() if code_block else text.strip()

    json_slice = _extract_first_brace_json_slice(candidate)
    if json_slice is not None:
        try:
            obj = json.loads(json_slice)
            return obj if isinstance(obj, dict) else None
        except json.JSONDecodeError:
            pass

        try:
            obj = json_repair.loads(json_slice)
            if isinstance(obj, dict):
                logger.warning(
                    "Used json_repair.loads() because LLM JSON was malformed "
                    "(stdlib json.loads failed)"
                )
                return obj
        except Exception:
            pass

        return _legacy_parse_json_object_brace_only(candidate)

    return None

_PLAN_PROMPT = """你是一个代码知识库搜索助手。用户的查询是：

"{query}"

请分析查询意图并生成搜索计划。输出 JSON：
{{
  "intent": "查询意图类型（search/impact_analysis/flow_query/concept_query）",
  "sub_queries": [
    {{"type": "rag_query|rag_graph", "query": "搜索词", "query_type": "可选的图查询类型", "name": "可选的实体名"}}
  ]
}}"""

_SYNTHESIZE_PROMPT = """你是一个代码知识库搜索助手。基于以下搜索结果，回答用户的查询。

用户查询: "{query}"

搜索结果:
{results_text}

请输出 JSON:
{{
  "sufficient": true,
  "analysis": "综合分析（Markdown 格式）",
  "business_flows": [{{"name": "流程名", "impact": "影响描述"}}],
  "code_locations": [{{"file": "文件路径", "function": "函数名", "relevance": "相关性说明"}}],
  "follow_up_queries": []
}}

判断 sufficient 的标准：查询中涉及的所有实体是否都有对应的搜索结果（含代码位置）。
如果 sufficient 为 false，在 follow_up_queries 中提供追加搜索计划（格式同上方 sub_queries）。"""


class DeepSearchEngine:
    """LLM-enhanced search engine for Dashboard users.

    Implements a multi-iteration search loop:
    1. Plan: LLM decomposes query into sub-queries
    2. Execute: Run sub-queries against hybrid search and graph query
    3. Synthesize: LLM analyzes results, decides if sufficient
    4. If insufficient, generate follow-up queries and loop
    """

    def __init__(
        self,
        llm: LLMProvider,
        hybrid_svc: HybridQueryService,
        graph_svc: GraphQueryService,
        task_manager: RepoTaskManager | None = None,
        *,
        synthesis_max_tokens: int | None = None,
        rag_engine: Any | None = None,
        use_iterative_rag: bool = False,
    ) -> None:
        self._llm = llm
        self._hybrid = hybrid_svc
        self._graph = graph_svc
        self._task_manager = task_manager
        self._synthesis_max_tokens = (
            synthesis_max_tokens
            if synthesis_max_tokens is not None
            else get_settings().llm.synthesis_max_tokens
        )
        self._rag_engine = rag_engine
        self._use_iterative_rag = use_iterative_rag

    async def search(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        include_code: bool = True,
        model: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a deep search with iterative refinement.

        Returns dict with analysis, business_flows, code_locations, search_trace.
        """
        trace: list[dict[str, Any]] = []

        plan = await self._plan_search(query, model=model, tenant_id=tenant_id)
        trace.append({"step": "plan", "result": plan})

        all_results: list[dict[str, Any]] = []
        synthesis: dict[str, Any] = {}

        for iteration in range(max_iterations):
            sub_queries = (
                plan.get("sub_queries", [])
                if iteration == 0
                else synthesis.get("follow_up_queries", [])
            )
            if not sub_queries:
                break

            results, _failed = await self._execute_sub_queries(sub_queries)
            all_results.extend(results)
            trace.append({
                "step": f"search_iter_{iteration}",
                "queries": sub_queries,
                "result_count": len(results),
            })

            synthesis = await self._synthesize(
                query, all_results, model=model, tenant_id=tenant_id,
            )
            trace.append({
                "step": f"synthesize_iter_{iteration}",
                "sufficient": synthesis.get("sufficient"),
            })

            if synthesis.get("sufficient", True):
                break

        return {
            "analysis": synthesis.get("analysis", ""),
            "business_flows": synthesis.get("business_flows", []),
            "code_locations": synthesis.get("code_locations", []),
            "search_trace": trace,
        }

    async def search_stream(
        self,
        query: str,
        *,
        max_iterations: int = 3,
        model: str | None = None,
        tenant_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Streaming version of search — yields SSE-compatible event dicts.

        Event types:
          plan       — search plan with intent and sub_queries
          progress   — a sub-query is being executed
          search_done — iteration search complete with result count
          synthesis  — iteration synthesis with sufficient flag and partial analysis
          conclusion — final result
          error      — non-fatal or fatal error
        """
        try:
            plan = await self._plan_search(query, model=model, tenant_id=tenant_id)
            yield {"type": "plan", "data": plan}
        except Exception as exc:
            yield {"type": "error", "data": {"phase": "plan", "message": str(exc)}}
            return

        all_results: list[dict[str, Any]] = []
        synthesis: dict[str, Any] = {}

        for iteration in range(max_iterations):
            sub_queries = (
                plan.get("sub_queries", [])
                if iteration == 0
                else synthesis.get("follow_up_queries", [])
            )
            if not sub_queries:
                break

            yield {"type": "progress", "data": {
                "iteration": iteration,
                "sub_queries": sub_queries,
            }}

            try:
                results, failed_count = await self._execute_sub_queries(sub_queries)
                all_results.extend(results)
                event_data: dict[str, Any] = {
                    "iteration": iteration,
                    "result_count": len(results),
                    "total_results": len(all_results),
                }
                if failed_count:
                    event_data["failed_queries"] = failed_count
                yield {"type": "search_done", "data": event_data}
            except Exception as exc:
                yield {"type": "error", "data": {
                    "phase": "search",
                    "iteration": iteration,
                    "message": str(exc),
                }}
                continue

            try:
                synthesis = await self._synthesize(
                    query, all_results, model=model, tenant_id=tenant_id,
                )
            except Exception as exc:
                yield {"type": "error", "data": {
                    "phase": "synthesis",
                    "iteration": iteration,
                    "message": str(exc),
                }}
                synthesis = {}
                break

            if synthesis.get("error"):
                yield {"type": "error", "data": {
                    "phase": "synthesis",
                    "iteration": iteration,
                    "message": synthesis.get("analysis", "Synthesis failed"),
                }}
                break

            yield {"type": "synthesis", "data": {
                "iteration": iteration,
                "sufficient": synthesis.get("sufficient"),
                "partial_analysis": (synthesis.get("analysis") or "")[:500],
            }}

            if synthesis.get("sufficient", True):
                break

        yield {"type": "conclusion", "data": {
            "analysis": synthesis.get("analysis", ""),
            "business_flows": synthesis.get("business_flows", []),
            "code_locations": synthesis.get("code_locations", []),
        }}

    async def _plan_search(
        self,
        query: str,
        *,
        model: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        prompt = _PLAN_PROMPT.format(query=query)
        fallback = {
            "intent": "search",
            "sub_queries": [{"type": "rag_query", "query": query}],
        }
        if self._task_manager and tenant_id:
            try:
                raw = await self._task_manager.prompt(f"search:{tenant_id}", prompt)
                parsed = _parse_json_object_from_llm(raw)
                if parsed is not None:
                    return parsed
                logger.warning("Failed to parse plan JSON from gateway response")
            except Exception:
                logger.warning("Gateway plan search failed, falling back to LLM", exc_info=True)
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
                model=model,
            )
        except Exception:
            logger.warning("Failed to plan search", exc_info=True)
            return fallback

    async def _execute_sub_queries(
        self, sub_queries: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], int]:
        """Execute sub-queries in parallel.

        Returns (results, failed_count).
        """
        tasks = [self._execute_single(sq) for sq in sub_queries]
        results: list[dict[str, Any]] = []
        failed = 0
        for result in await asyncio.gather(*tasks, return_exceptions=True):
            if isinstance(result, Exception):
                logger.warning("Sub-query failed: %s", result)
                failed += 1
            elif result:
                results.append(result)
        return results, failed

    async def _execute_single(
        self, sub_query: dict[str, Any]
    ) -> dict[str, Any] | None:
        q_type = sub_query.get("type", "rag_query")
        if q_type == "rag_query":
            hybrid_result = await self._hybrid.search_with_context(
                sub_query.get("query", ""), k=5, offset=0, limit=500, sort_by="score",
            )
            rows = hybrid_result.get("semantic_matches") or hybrid_result["results"]
            return {
                "type": "hybrid",
                "matches": rows,
                "context": hybrid_result["graph_context"],
            }
        elif q_type == "rag_graph":
            query_type = sub_query.get("query_type", "business_flow")
            name = sub_query.get("name", "")
            if query_type == "business_flow" and name:
                result = await self._graph.find_business_flow(name)
                return {"type": "graph", "data": result.data}
            elif query_type == "flows_for_function" and name:
                result = await self._graph.find_flows_for_function(name)
                return {"type": "graph", "data": result.data}
            elif query_type == "related_concepts" and name:
                result = await self._graph.find_related_concepts(name)
                return {"type": "graph", "data": result.data}
        return None

    async def _synthesize(
        self,
        query: str,
        results: list[dict[str, Any]],
        *,
        model: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        raw_json = json.dumps(results, ensure_ascii=False, default=str)
        results_text = _truncate_for_synthesis(raw_json, self._synthesis_max_tokens)
        prompt = _SYNTHESIZE_PROMPT.format(query=query, results_text=results_text)
        error_fallback = {
            "sufficient": False,
            "analysis": "搜索结果汇总失败，请重试或缩小查询范围。",
            "business_flows": [],
            "code_locations": [],
            "error": True,
        }
        if self._task_manager and tenant_id:
            try:
                raw = await self._task_manager.prompt(f"search:{tenant_id}", prompt)
                parsed = _parse_json_object_from_llm(raw)
                if parsed is not None:
                    return parsed
                logger.warning("Failed to parse synthesis JSON from gateway response")
            except Exception:
                logger.warning("Gateway synthesize failed, falling back to LLM", exc_info=True)
        try:
            return await self._llm.complete_json(
                [{"role": "user", "content": prompt}],
                schema={"type": "object"},
                model=model,
            )
        except Exception:
            logger.warning("Failed to synthesize results", exc_info=True)
            return error_fallback
