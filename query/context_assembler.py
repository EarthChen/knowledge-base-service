"""Assemble a one-stop context bundle for a code entity (code, graph, wiki)."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from log import get_logger
from query.graph_query import GraphQueryService
from query.hybrid_query import HybridQueryService
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


def _estimate_tokens(text: str) -> int:
    return max(len(text) // 4, 0)


def _json_tokens(obj: Any) -> int:
    try:
        return _estimate_tokens(json.dumps(obj, default=str))
    except (TypeError, ValueError):
        return _estimate_tokens(str(obj))


def _truncate_text(text: str, max_tokens: int) -> str:
    if max_tokens <= 0:
        return ""
    if _estimate_tokens(text) <= max_tokens:
        return text
    max_chars = max(max_tokens * 4, 0)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "…"


class ContextAssembler:
    """Collects entity, call graph, hierarchy, flows, and wiki text within a token budget."""

    def __init__(
        self,
        store: FalkorDBStore,
        hybrid_svc: HybridQueryService,
        graph_svc: GraphQueryService,
    ) -> None:
        self._store = store
        self._hybrid = hybrid_svc
        self._graph = graph_svc

    async def assemble(
        self,
        entity_name: str,
        repository: str | None = None,
        language: str | None = None,
        max_tokens: int = 8000,
    ) -> dict[str, Any]:
        name_key = (entity_name or "").strip()
        if not name_key:
            return self._empty_payload(0.0)

        hybrid_result = await self._hybrid.search_with_context(
            name_key,
            k=12,
            expand_depth=1,
            include_callers=True,
            include_callees=True,
            use_query_expansion=False,
            repository=repository,
            language=language,
            offset=0,
            limit=500,
            sort_by="score",
        )
        confidence = float(hybrid_result["confidence"])
        semantic_rows = hybrid_result.get("semantic_matches") or hybrid_result["results"]
        match = self._pick_match(semantic_rows, name_key, repository)
        if match is None:
            fe = await self._graph.find_entity(name_key, "any")
            if fe.data:
                row = fe.data[0]
                match = {
                    "name": row.get("name", ""),
                    "type": row.get("type", ""),
                    "file": row.get("file", ""),
                    "line": row.get("line", 0),
                    "signature": row.get("signature", ""),
                    "docstring": row.get("docstring", ""),
                    "match_source": "graph_fallback",
                }
                confidence = max(confidence, 0.15)
            else:
                return self._empty_payload(0.0)

        resolved_name = str(match.get("name") or name_key)
        uid = match.get("uid")

        entity_task = self._load_entity_details(resolved_name, repository, uid, match)
        chain_task = self._call_chain_bundle(resolved_name)
        hier_task = self._hierarchy_bundle(resolved_name, str(match.get("type") or ""))
        flows_task = self._business_flows_bundle(resolved_name)
        wiki_task = self._wiki_bundle(repository, resolved_name)

        entity, call_chain, hierarchy, business_flows, wiki_content = await asyncio.gather(
            entity_task,
            chain_task,
            hier_task,
            flows_task,
            wiki_task,
        )

        matched_excerpt = match.get("matched_excerpt") or ""
        excerpt_lines = match.get("excerpt_lines") or []

        payload: dict[str, Any] = {
            "entity": entity,
            "matched_excerpt": matched_excerpt,
            "excerpt_lines": excerpt_lines,
            "call_chain": call_chain,
            "hierarchy": hierarchy,
            "business_flows": business_flows,
            "wiki_content": wiki_content,
            "confidence": max(0.0, min(1.0, confidence)),
        }
        self._truncate_payload(payload, max_tokens)
        return payload

    def _empty_payload(self, confidence: float) -> dict[str, Any]:
        return {
            "entity": {},
            "matched_excerpt": "",
            "excerpt_lines": [],
            "call_chain": {"upstream": [], "downstream": []},
            "hierarchy": {"parents": [], "children": []},
            "business_flows": [],
            "wiki_content": "",
            "confidence": confidence,
        }

    @staticmethod
    def _pick_match(
        matches: list[dict[str, Any]],
        name_key: str,
        repository: str | None,
    ) -> dict[str, Any] | None:
        if not matches:
            return None
        nk = name_key.lower()
        for m in matches:
            if str(m.get("name", "")).lower() == nk:
                if repository:
                    repo = str(m.get("repository") or "").strip()
                    if repo and repo != repository.strip():
                        continue
                return m
        for m in matches:
            if name_key in str(m.get("name", "")):
                return m
        return matches[0]

    async def _load_entity_details(
        self,
        name: str,
        repository: str | None,
        uid: Any,
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        ret = (
            "RETURN n.uid AS uid, n.name AS name, labels(n)[0] AS type, n.file AS file, "
            "n.start_line AS start_line, n.end_line AS end_line, "
            "coalesce(n.code_snippet, '') AS code_snippet, coalesce(n.docstring, '') AS docstring, "
            "coalesce(n.signature, '') AS signature, coalesce(n.repository, '') AS repository "
            "LIMIT 1"
        )
        if uid:
            q = f"MATCH (n) WHERE n.uid = $uid {ret}"
            params: dict[str, Any] = {"uid": str(uid)}
        else:
            params = {"name": name}
            repo_clause = ""
            if repository:
                params["repo"] = repository.strip()
                repo_clause = "AND n.repository = $repo "
            q = (
                f"MATCH (n) WHERE (n:Function OR n:Class) AND (n.name = $name OR n.fqn ENDS WITH $name) "
                f"{repo_clause} {ret}"
            )
        try:
            res = await self._store.execute_query(q, params)
            if res.data:
                row = res.data[0]
                return {
                    "uid": row.get("uid", ""),
                    "name": row.get("name", ""),
                    "type": row.get("type", ""),
                    "file": row.get("file", ""),
                    "start_line": row.get("start_line"),
                    "end_line": row.get("end_line"),
                    "code_snippet": row.get("code_snippet") or "",
                    "docstring": row.get("docstring") or "",
                    "signature": row.get("signature") or "",
                    "repository": row.get("repository") or "",
                }
        except Exception:
            log.debug("context_assembler_entity_load_failed", exc_info=True)

        return {
            "uid": str(uid or ""),
            "name": fallback.get("name", name),
            "type": fallback.get("type", ""),
            "file": fallback.get("file", ""),
            "start_line": fallback.get("line"),
            "end_line": fallback.get("end_line"),
            "code_snippet": fallback.get("code_snippet") or "",
            "docstring": fallback.get("docstring") or "",
            "signature": fallback.get("signature") or "",
            "repository": str(fallback.get("repository") or ""),
        }

    async def _call_chain_bundle(self, function_name: str) -> dict[str, Any]:
        try:
            up = await self._graph.find_call_chain(function_name, depth=1, direction="upstream")
            down = await self._graph.find_call_chain(function_name, depth=1, direction="downstream")
            return {"upstream": list(up.data), "downstream": list(down.data)}
        except Exception:
            log.debug("context_assembler_call_chain_failed", exc_info=True)
            return {"upstream": [], "downstream": []}

    async def _hierarchy_bundle(self, name: str, entity_type: str) -> dict[str, Any]:
        if "Class" not in entity_type and entity_type != "Class":
            return {"parents": [], "children": []}
        try:
            parents = await self._graph.find_inheritance_tree(name, direction="parents")
            children = await self._graph.find_inheritance_tree(name, direction="children")
            return {"parents": list(parents.data), "children": list(children.data)}
        except Exception:
            log.debug("context_assembler_hierarchy_failed", exc_info=True)
            return {"parents": [], "children": []}

    async def _business_flows_bundle(self, function_name: str) -> list[dict[str, Any]]:
        try:
            res = await self._graph.find_flows_for_function(function_name)
            return [dict(r) if isinstance(r, dict) else {"row": r} for r in res.data]
        except Exception:
            log.debug("context_assembler_flows_failed", exc_info=True)
            return []

    async def _wiki_bundle(self, repository: str | None, entity_name: str) -> str:
        needle = entity_name.strip()
        if not needle:
            return ""
        try:
            if repository:
                q = (
                    "MATCH (wp:WikiPage {repository: $repository}) "
                    "WHERE wp.title CONTAINS $needle OR wp.path CONTAINS $needle "
                    "RETURN wp.title AS title, wp.path AS path, coalesce(wp.content, '') AS content "
                    "LIMIT 5"
                )
                rows = await self._store.execute_query(
                    q, {"repository": repository.strip(), "needle": needle},
                )
            else:
                q = (
                    "MATCH (wp:WikiPage) "
                    "WHERE wp.title CONTAINS $needle OR wp.path CONTAINS $needle "
                    "RETURN wp.title AS title, wp.path AS path, coalesce(wp.content, '') AS content "
                    "LIMIT 5"
                )
                rows = await self._store.execute_query(q, {"needle": needle})
            parts: list[str] = []
            for row in rows.data or []:
                title = str(row.get("title") or "")
                path = str(row.get("path") or "")
                body = str(row.get("content") or "")
                parts.append(f"### {title} ({path})\n{body}")
            return "\n\n".join(parts).strip()
        except Exception:
            log.debug("context_assembler_wiki_failed", exc_info=True)
            return ""

    def _total_tokens(self, payload: dict[str, Any]) -> int:
        return (
            _json_tokens(payload.get("entity"))
            + _estimate_tokens(str(payload.get("matched_excerpt") or ""))
            + _json_tokens(payload.get("call_chain"))
            + _json_tokens(payload.get("hierarchy"))
            + _json_tokens(payload.get("business_flows"))
            + _estimate_tokens(str(payload.get("wiki_content") or ""))
        )

    def _truncate_payload(self, payload: dict[str, Any], max_tokens: int) -> None:
        """Drop/truncate least important sections first: wiki → flows → hierarchy → call_chain → entity."""
        if max_tokens <= 0:
            payload["wiki_content"] = ""
            payload["business_flows"] = []
            payload["hierarchy"] = {"parents": [], "children": []}
            payload["call_chain"] = {"upstream": [], "downstream": []}
            payload["entity"] = {}
            return

        while self._total_tokens(payload) > max_tokens:
            wc = str(payload.get("wiki_content") or "")
            if wc:
                new_len = max(_estimate_tokens(wc) // 2, 1)
                payload["wiki_content"] = _truncate_text(wc, new_len)
                continue

            me = str(payload.get("matched_excerpt") or "")
            if me:
                new_len = max(_estimate_tokens(me) // 2, 1)
                payload["matched_excerpt"] = _truncate_text(me, new_len)
                continue

            flows: list[Any] = list(payload.get("business_flows") or [])
            if flows:
                payload["business_flows"] = flows[:-1] or []
                continue

            hier = payload.get("hierarchy") or {}
            parents = list(hier.get("parents") or [])
            children = list(hier.get("children") or [])
            if children:
                hier["children"] = children[:-1]
                payload["hierarchy"] = hier
                continue
            if parents:
                hier["parents"] = parents[:-1]
                payload["hierarchy"] = hier
                continue

            cc = payload.get("call_chain") or {}
            down = list(cc.get("downstream") or [])
            up = list(cc.get("upstream") or [])
            if down:
                cc["downstream"] = down[:-1]
                payload["call_chain"] = cc
                continue
            if up:
                cc["upstream"] = up[:-1]
                payload["call_chain"] = cc
                continue

            ent = dict(payload.get("entity") or {})
            if ent.get("code_snippet"):
                cs = str(ent["code_snippet"])
                ent["code_snippet"] = _truncate_text(cs, max(_estimate_tokens(cs) // 2, 1))
                payload["entity"] = ent
                continue
            if ent.get("docstring"):
                ds = str(ent["docstring"])
                ent["docstring"] = _truncate_text(ds, max(_estimate_tokens(ds) // 2, 1))
                payload["entity"] = ent
                continue
            break
