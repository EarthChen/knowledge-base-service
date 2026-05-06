"""Unified context builder for wiki page generation.

Queries the FalkorDB graph to assemble rich domain context (method signatures,
call chains, enums/constants, cross-domain dependencies) that all Composers
share via EnrichedDomainContext.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from core.log import get_logger

log = get_logger(__name__)

_METHODS_CY = """
MATCH (m:Module)-[:CONTAINS*1..3]->(f:Function)
WHERE m.name IN $names
RETURN m.name AS module_name, f.name AS func_name,
       coalesce(f.signature, '') AS signature,
       coalesce(f.file, '') AS file_path,
       coalesce(f.start_line, 0) AS start_line,
       coalesce(f.repository, '') AS repository,
       coalesce(f.docstring, '') AS docstring
""".strip()


def _call_chain_cypher(depth: int) -> str:
    d = max(1, int(depth))
    return f"""
MATCH (a:Module)-[:CALLS*1..{d}]->(b:Module)
WHERE a.name IN $names
RETURN a.name AS caller, b.name AS callee
""".strip()


_ENUMS_CY = """
MATCH (m:Module)-[:CONTAINS]->(c)
WHERE m.name IN $names AND (c:Enum OR c.is_constant = true)
RETURN c.name AS name, c.file AS file, labels(c) AS labels
""".strip()


@dataclass
class MethodDetail:
    name: str
    signature: str  # Full method signature with param types and return type
    file_path: str
    start_line: int
    repository: str
    docstring: str = ""
    module_name: str = ""


@dataclass
class CallChainStep:
    caller: str
    callee: str
    caller_method: str
    callee_method: str
    relationship: str  # CALLS / IMPORTS


@dataclass
class EntityDetail:
    uid: str
    name: str
    repository: str
    file_path: str
    entity_type: str  # Module / Class / Interface
    business_summary: str
    methods: list[MethodDetail] = field(default_factory=list)
    call_chains: list[CallChainStep] = field(default_factory=list)


@dataclass
class EnrichedDomainContext:
    domain_name: str
    parent_domain: str

    biz_entities: list[EntityDetail] = field(default_factory=list)
    data_models: list[dict] = field(default_factory=list)

    intra_domain_calls: list[CallChainStep] = field(default_factory=list)
    cross_domain_calls: list[CallChainStep] = field(default_factory=list)

    key_snippets: list[str] = field(default_factory=list)
    enums_and_constants: list[dict] = field(default_factory=list)

    sibling_domains: list[str] = field(default_factory=list)
    dependent_domains: list[str] = field(default_factory=list)
    dependee_domains: list[str] = field(default_factory=list)

    sub_topics: list[dict] = field(default_factory=list)

    existing_wiki_context: str = ""  # Summaries of existing wiki pages in same domain


class ContentContextBuilder:
    """Assembles EnrichedDomainContext by querying the graph store."""

    def __init__(self, graph_store: Any, wiki_store: Any | None = None) -> None:
        self._graph = graph_store
        self._wiki = wiki_store

    async def build_context(
        self,
        domain_name: str,
        module_names: list[str],
        module_index: dict[str, Any],
        entity_roles: dict[str, str],
        domain_mapping: dict[str, list],
        *,
        depth: int = 2,
    ) -> EnrichedDomainContext:
        """Build complete context for a domain by querying the graph in parallel."""
        methods_task = self._query_methods(module_names)
        calls_task = self._query_call_chains(module_names, depth)
        enums_task = self._query_enums_constants(module_names)

        methods_result, calls_result, enums_result = await asyncio.gather(
            methods_task,
            calls_task,
            enums_task,
            return_exceptions=True,
        )

        methods_list: list[MethodDetail] = (
            methods_result if isinstance(methods_result, list) else []
        )
        if isinstance(methods_result, BaseException):
            log.warning(
                "content_context_methods_query_failed",
                error=repr(methods_result),
            )

        calls_parsed: list[CallChainStep] = (
            calls_result if isinstance(calls_result, list) else []
        )
        if isinstance(calls_result, BaseException):
            log.warning(
                "content_context_call_chains_query_failed",
                error=repr(calls_result),
            )

        enums_list: list[dict] = enums_result if isinstance(enums_result, list) else []
        if isinstance(enums_result, BaseException):
            log.warning(
                "content_context_enums_query_failed",
                error=repr(enums_result),
            )

        biz_entities = self._build_entities(
            module_names,
            module_index,
            entity_roles,
            methods_list,
        )

        all_names_set = set(module_names)
        intra_calls, cross_calls = [], []
        for step in calls_parsed:
            if step.caller in all_names_set and step.callee in all_names_set:
                intra_calls.append(step)
            else:
                cross_calls.append(step)

        for ent in biz_entities:
            ent.call_chains = [
                s
                for s in intra_calls
                if s.caller == ent.name or s.callee == ent.name
            ]

        data_models = self._collect_data_models(module_names, module_index, entity_roles)

        dependent_domains, dependee_domains = self._compute_domain_deps(
            domain_name,
            module_names,
            domain_mapping,
            cross_calls,
        )

        existing_wiki_ctx = ""
        if self._wiki is not None:
            existing_wiki_ctx = await self._fetch_existing_wiki_context(domain_name)

        sibling_domains = [d for d in domain_mapping if d != domain_name]

        return EnrichedDomainContext(
            domain_name=domain_name,
            parent_domain="root",
            biz_entities=biz_entities,
            data_models=data_models,
            intra_domain_calls=intra_calls,
            cross_domain_calls=cross_calls[:10],
            key_snippets=[],
            enums_and_constants=enums_list,
            sibling_domains=sibling_domains[:10],
            dependent_domains=dependent_domains,
            dependee_domains=dependee_domains,
            sub_topics=[],
            existing_wiki_context=existing_wiki_ctx,
        )

    async def _query_methods(self, module_names: list[str]) -> list[MethodDetail]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            result = await self._graph.execute_query(
                _METHODS_CY,
                {"names": module_names},
            )
        except Exception:
            log.warning("graph_methods_query_failed", exc_info=True)
            return []
        rows = getattr(result, "data", None) or []
        out: list[MethodDetail] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            mod_name = str(row.get("module_name", "") or "")
            out.append(
                MethodDetail(
                    name=str(row.get("func_name", "") or ""),
                    signature=str(row.get("signature", "") or ""),
                    file_path=str(row.get("file_path", "") or ""),
                    start_line=int(row.get("start_line") or 0),
                    repository=str(row.get("repository", "") or ""),
                    docstring=str(row.get("docstring", "") or ""),
                    module_name=mod_name,
                ),
            )
        return out

    async def _query_call_chains(
        self, module_names: list[str], depth: int
    ) -> list[CallChainStep]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            result = await self._graph.execute_query(
                _call_chain_cypher(depth),
                {"names": module_names},
            )
        except Exception:
            log.warning("graph_call_chains_query_failed", exc_info=True)
            return []
        rows = getattr(result, "data", None) or []
        steps: list[CallChainStep] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            steps.append(
                CallChainStep(
                    caller=str(row.get("caller", "") or ""),
                    callee=str(row.get("callee", "") or ""),
                    caller_method="",
                    callee_method="",
                    relationship="CALLS",
                ),
            )
        return steps

    async def _query_enums_constants(self, module_names: list[str]) -> list[dict]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            result = await self._graph.execute_query(
                _ENUMS_CY,
                {"names": module_names},
            )
        except Exception:
            log.warning("graph_enums_constants_query_failed", exc_info=True)
            return []
        rows = getattr(result, "data", None) or []
        out: list[dict] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            labels = row.get("labels")
            if not isinstance(labels, list):
                labels = [str(labels)] if labels is not None else []
            out.append({
                "name": row.get("name"),
                "file": row.get("file"),
                "labels": labels,
            })
        return out

    def _build_entities(
        self,
        module_names: list[str],
        module_index: dict[str, Any],
        entity_roles: dict[str, str],
        methods: list[MethodDetail],
    ) -> list[EntityDetail]:
        by_mod: dict[str, list[MethodDetail]] = {}
        for m in methods:
            key = m.module_name
            if key not in by_mod:
                by_mod[key] = []
            by_mod[key].append(m)

        entities: list[EntityDetail] = []
        for mod_name in module_names:
            for mod_dict in module_index.get(mod_name, []) or []:
                if not isinstance(mod_dict, dict):
                    continue
                uid = str(mod_dict.get("uid", "") or f"Module::{mod_name}:0")
                role = str(entity_roles.get(uid, "supporting"))
                if role not in ("has_business_logic", "entry_point"):
                    continue
                props = mod_dict.get("properties", {}) or {}
                if not isinstance(props, dict):
                    props = {}
                repo = str(mod_dict.get("_repo", "") or "")
                file_path = str(
                    props.get("file", "")
                    or props.get("file_path", "")
                    or props.get("path", "")
                    or "",
                )
                summary = str(
                    props.get("business_summary", "")
                    or props.get("docstring", "")
                    or "",
                )
                entity_type = str(props.get("entity_type", "") or "Module")
                entities.append(
                    EntityDetail(
                        uid=uid,
                        name=mod_name,
                        repository=repo,
                        file_path=file_path,
                        entity_type=entity_type,
                        business_summary=summary,
                        methods=list(by_mod.get(mod_name, [])),
                        call_chains=[],
                    ),
                )
        return entities

    def _collect_data_models(
        self,
        module_names: list[str],
        module_index: dict[str, Any],
        entity_roles: dict[str, str],
    ) -> list[dict]:
        data_models: list[dict] = []
        for mod_name in module_names:
            for mod_dict in module_index.get(mod_name, []) or []:
                if not isinstance(mod_dict, dict):
                    continue
                uid = str(mod_dict.get("uid", "") or "")
                if str(entity_roles.get(uid, "")) != "data_model":
                    continue
                props = mod_dict.get("properties", {}) or {}
                if not isinstance(props, dict):
                    props = {}
                data_models.append({
                    "uid": uid,
                    "name": str(props.get("name", mod_name)),
                    "type": "DTO",
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:8]],
                })
        return data_models[:20]

    def _compute_domain_deps(
        self,
        domain_name: str,
        module_names: list[str],
        domain_mapping: dict[str, list],
        cross_calls: list[CallChainStep],
    ) -> tuple[list[str], list[str]]:
        local = set(module_names)
        mod_to_domain: dict[str, str] = {}
        for dom, pairs in domain_mapping.items():
            if not isinstance(pairs, list):
                continue
            for pair in pairs:
                mname: str | None = None
                if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                    mname = str(pair[1])
                elif isinstance(pair, str):
                    mname = pair
                if mname:
                    mod_to_domain[mname] = str(dom)

        dependents: set[str] = set()
        dependees: set[str] = set()

        def dom_for(mod: str) -> str | None:
            d = mod_to_domain.get(mod)
            if d and d != domain_name:
                return d
            return None

        for step in cross_calls:
            ca, ce = step.caller, step.callee
            if ca in local and ce not in local:
                d = dom_for(ce)
                if d:
                    dependents.add(d)
            if ce in local and ca not in local:
                d = dom_for(ca)
                if d:
                    dependees.add(d)

        return sorted(dependents), sorted(dependees)

    async def _fetch_existing_wiki_context(self, domain_name: str) -> str:
        if self._wiki is None or not hasattr(self._wiki, "execute_query"):
            return ""
        wiki_root = f"wiki/{domain_name}"
        wiki_under = f"wiki/{domain_name}/"
        q = (
            "MATCH (wp:WikiPage) "
            "WHERE wp.path = $domain_name OR wp.path = $wiki_root "
            "OR wp.path STARTS WITH $wiki_under "
            "RETURN coalesce(wp.executive_summary, '') AS executive_summary "
            "LIMIT 50"
        )
        try:
            result = await self._wiki.execute_query(
                q,
                {
                    "domain_name": domain_name,
                    "wiki_root": wiki_root,
                    "wiki_under": wiki_under,
                },
            )
        except Exception:
            log.warning("wiki_existing_context_query_failed", exc_info=True)
            return ""
        rows = getattr(result, "data", None) or []
        summaries: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("executive_summary", "") or "").strip()
            if text:
                summaries.append(text)
        return "\n\n".join(summaries)
