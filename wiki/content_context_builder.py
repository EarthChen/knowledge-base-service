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
from wiki.call_chain_builder import CallChainBuilder
from wiki.cypher_queries import (
    CALLERS_CY as _CALLERS_CY,
)
from wiki.cypher_queries import (
    CHUNK_SNIPPETS_CY as _CHUNK_SNIPPETS_CY,
)
from wiki.cypher_queries import (
    ENUMS_CY as _ENUMS_CY,
)
from wiki.cypher_queries import (
    IMPLEMENTS_CY as _IMPLEMENTS_CY,
)
from wiki.cypher_queries import (
    METHOD_CALL_CHAIN_CY as _METHOD_CALL_CHAIN_CY,
)
from wiki.cypher_queries import (
    METHODS_CY as _METHODS_CY,
)
from wiki.cypher_queries import (
    SNIPPETS_CY as _SNIPPETS_CY,
)
from wiki.cypher_queries import (
    call_chain_cypher as _call_chain_cypher_fn,
)

log = get_logger(__name__)


def _call_chain_cypher(depth: int) -> str:
    return _call_chain_cypher_fn(depth)


_MAX_CALL_CHAIN_DEPTH = 5
_MAX_DATA_MODELS = 20
_MAX_FIELDS_PER_MODEL = 8
_MAX_CROSS_DOMAIN_CALLS = 10
_MAX_SIBLING_DOMAINS = 10
_MAX_KEY_SNIPPETS = 6
_MAX_INTERFACE_IMPLS = 20
_MAX_EXTERNAL_CALLERS = 15


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
    method_call_chains: list[dict] = field(default_factory=list)

    key_snippets: list[str] = field(default_factory=list)
    enums_and_constants: list[dict] = field(default_factory=list)

    sibling_domains: list[str] = field(default_factory=list)
    dependent_domains: list[str] = field(default_factory=list)
    dependee_domains: list[str] = field(default_factory=list)

    interface_impls: list[dict] = field(default_factory=list)
    external_callers: list[dict] = field(default_factory=list)

    module_leaf_summaries: dict[str, str] = field(default_factory=dict)

    sub_topics: list[dict] = field(default_factory=list)

    existing_wiki_context: str = ""  # Summaries of existing wiki pages in same domain
    domain_description: str = ""

    def format_summary_for_agent(self, max_chars: int = 6000) -> str:
        """Compress already-queried context into a structured summary for WikiPageAgent.

        This avoids redundant tool-calling by the agent for information CCB
        already retrieved from the graph.
        """
        sections: list[str] = []

        if self.biz_entities:
            method_lines: list[str] = []
            for ent in self.biz_entities:
                for m in ent.methods[:5]:
                    method_lines.append(f"  - {ent.name}.{m.name}: {m.signature}")
            if method_lines:
                sections.append("## Known Methods\n" + "\n".join(method_lines[:15]))

        if self.intra_domain_calls or self.cross_domain_calls:
            call_lines: list[str] = []
            for step in (self.intra_domain_calls + self.cross_domain_calls)[:10]:
                call_lines.append(
                    f"  - {step.caller}.{step.caller_method} → {step.callee}.{step.callee_method}"
                )
            if call_lines:
                sections.append("## Known Call Chains\n" + "\n".join(call_lines))

        if self.interface_impls:
            impl_lines = [
                f"  - {d.get('interface_name', '?')} ← {d.get('impl_name', '?')}"
                for d in self.interface_impls[:10]
            ]
            sections.append("## Known Implementations\n" + "\n".join(impl_lines))

        if self.external_callers:
            caller_lines = [
                f"  - {d.get('caller_name', '?')} → {d.get('target_name', '?')}"
                for d in self.external_callers[:10]
            ]
            sections.append("## Known External Callers\n" + "\n".join(caller_lines))

        if self.module_leaf_summaries:
            summary_lines = [
                f"  - {name}: {text[:120]}"
                for name, text in list(self.module_leaf_summaries.items())[:15]
                if text
            ]
            if summary_lines:
                sections.append("## Module Summaries\n" + "\n".join(summary_lines))

        if self.data_models:
            dm_lines = [
                f"  - {d.get('name', '?')}: fields={d.get('fields', [])[:5]}"
                for d in self.data_models[:10]
            ]
            if dm_lines:
                sections.append("## Data Models\n" + "\n".join(dm_lines))

        if self.domain_description:
            sections.insert(0, f"## Domain Description\n{self.domain_description[:500]}")

        if not sections:
            return ""

        full = f"# Already-queried context for domain: {self.domain_name}\n\n" + "\n\n".join(sections)
        if len(full) > max_chars:
            return full[: max_chars - 3] + "..."
        return full


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
        parent_domain: str | None = None,
        sub_topics: list[dict] | None = None,
    ) -> EnrichedDomainContext:
        """Build complete context for a domain by querying the graph in parallel."""
        capped_depth = min(max(1, int(depth)), _MAX_CALL_CHAIN_DEPTH)

        methods_task = self._query_methods(module_names)
        calls_task = self._query_call_chains(module_names, capped_depth)
        call_chains_task = self._query_method_call_chains(module_names)
        enums_task = self._query_enums_constants(module_names)
        snippets_task = self._query_key_snippets(module_names)
        impls_task = self._query_implementations(module_names)
        callers_task = self._query_callers(module_names)

        (
            methods_result,
            calls_result,
            method_call_chains_result,
            enums_result,
            snippets_result,
            impls_result,
            callers_result,
        ) = await asyncio.gather(
            methods_task,
            calls_task,
            call_chains_task,
            enums_task,
            snippets_task,
            impls_task,
            callers_task,
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

        method_call_chains_list: list[dict] = (
            method_call_chains_result
            if isinstance(method_call_chains_result, list)
            else []
        )
        if isinstance(method_call_chains_result, BaseException):
            log.warning(
                "content_context_method_call_chains_query_failed",
                error=repr(method_call_chains_result),
            )

        enums_list: list[dict] = enums_result if isinstance(enums_result, list) else []
        if isinstance(enums_result, BaseException):
            log.warning(
                "content_context_enums_query_failed",
                error=repr(enums_result),
            )

        snippets_list: list[str] = (
            snippets_result if isinstance(snippets_result, list) else []
        )
        if isinstance(snippets_result, BaseException):
            log.warning(
                "content_context_snippets_query_failed",
                error=repr(snippets_result),
            )

        impls_list: list[dict] = (
            impls_result if isinstance(impls_result, list) else []
        )
        if isinstance(impls_result, BaseException):
            log.warning(
                "content_context_impls_query_failed",
                error=repr(impls_result),
            )

        callers_list: list[dict] = (
            callers_result if isinstance(callers_result, list) else []
        )
        if isinstance(callers_result, BaseException):
            log.warning(
                "content_context_callers_query_failed",
                error=repr(callers_result),
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
            parent_domain=parent_domain or "root",
            biz_entities=biz_entities,
            data_models=data_models,
            intra_domain_calls=intra_calls,
            cross_domain_calls=cross_calls[:_MAX_CROSS_DOMAIN_CALLS],
            method_call_chains=method_call_chains_list,
            key_snippets=snippets_list[:_MAX_KEY_SNIPPETS],
            enums_and_constants=enums_list,
            sibling_domains=sibling_domains[:_MAX_SIBLING_DOMAINS],
            dependent_domains=dependent_domains,
            dependee_domains=dependee_domains,
            interface_impls=impls_list[:_MAX_INTERFACE_IMPLS],
            external_callers=callers_list[:_MAX_EXTERNAL_CALLERS],
            sub_topics=sub_topics or [],
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

        module_task = self._graph.execute_query(
            _call_chain_cypher(depth),
            {"names": module_names},
        )
        method_task = self._graph.execute_query(
            _METHOD_CALL_CHAIN_CY,
            {"names": module_names},
        )

        try:
            module_result, method_result = await asyncio.gather(
                module_task, method_task, return_exceptions=True,
            )
        except Exception:
            log.warning("graph_call_chains_query_failed", exc_info=True)
            return []

        method_rows: list[dict] = []
        if isinstance(method_result, BaseException):
            log.debug("method_call_chain_query_failed", error=repr(method_result))
        else:
            method_rows = [
                r for r in (getattr(method_result, "data", None) or [])
                if isinstance(r, dict)
            ]

        if isinstance(module_result, BaseException):
            log.warning("graph_call_chains_query_failed", error=repr(module_result))
            module_rows: list[dict] = []
        else:
            module_rows = [
                r for r in (getattr(module_result, "data", None) or [])
                if isinstance(r, dict)
            ]

        steps: list[CallChainStep] = []

        if module_rows:
            for row in module_rows:
                caller = str(row.get("caller", "") or "")
                callee = str(row.get("callee", "") or "")
                caller_fns = row.get("caller_functions") or []
                callee_fns = row.get("callee_functions") or []
                steps.append(
                    CallChainStep(
                        caller=caller,
                        callee=callee,
                        caller_method=str(caller_fns[0]) if caller_fns else "",
                        callee_method=str(callee_fns[0]) if callee_fns else "",
                        relationship="CALLS",
                    ),
                )
        elif method_rows:
            seen: set[tuple[str, str]] = set()
            for row in method_rows:
                cm = str(row.get("caller_method", "") or "")
                ce = str(row.get("callee_method", "") or "")
                mod = str(row.get("module_name", "") or "")
                if not cm or not ce or cm == ce or (cm, ce) in seen:
                    continue
                seen.add((cm, ce))
                steps.append(
                    CallChainStep(
                        caller=f"{mod}.{cm}" if mod else cm,
                        callee=ce,
                        caller_method=cm,
                        callee_method=ce,
                        relationship="CALLS",
                    ),
                )

        return steps

    async def _query_method_call_chains(self, module_names: list[str]) -> list[dict]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            builder = CallChainBuilder(self._graph)
            chains = await builder.build_chains(module_names)
            return [
                {
                    "entry_method": c.entry_method,
                    "entry_module": c.entry_module,
                    "chain": [
                        {
                            "func": n.func_name,
                            "module": n.module_name,
                            "file": n.file_path,
                            "sig": n.signature,
                        }
                        for n in c.chain
                    ],
                    "depth": c.depth,
                }
                for c in chains
            ]
        except Exception:
            log.warning("method_call_chains_query_failed", exc_info=True)
            return []

    async def _query_key_snippets(self, module_names: list[str]) -> list[str]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []

        snippet_task = self._graph.execute_query(
            _SNIPPETS_CY, {"names": module_names},
        )
        chunk_task = self._graph.execute_query(
            _CHUNK_SNIPPETS_CY, {"names": module_names},
        )

        try:
            snippet_result, chunk_result = await asyncio.gather(
                snippet_task, chunk_task, return_exceptions=True,
            )
        except Exception:
            log.warning("graph_snippets_query_failed", exc_info=True)
            return []

        out: list[str] = []

        if not isinstance(snippet_result, BaseException):
            for row in getattr(snippet_result, "data", None) or []:
                if not isinstance(row, dict):
                    continue
                func_name = str(row.get("func_name", "") or "")
                snippet = str(row.get("snippet", "") or "").strip()
                file_path = str(row.get("file_path", "") or "")
                line = int(row.get("start_line") or 0)
                if snippet:
                    header = f"// {func_name} @ {file_path}:{line}" if file_path else f"// {func_name}"
                    out.append(f"{header}\n{snippet}")

        if not out and not isinstance(chunk_result, BaseException):
            for row in getattr(chunk_result, "data", None) or []:
                if not isinstance(row, dict):
                    continue
                entity_name = str(row.get("entity_name", "") or "")
                snippet = str(row.get("snippet", "") or "").strip()
                file_path = str(row.get("file_path", "") or "")
                start_line = int(row.get("start_line") or 0)
                end_line = int(row.get("end_line") or 0)
                if snippet:
                    loc = f"{file_path}:{start_line}-{end_line}" if file_path else ""
                    header = f"// {entity_name} @ {loc}" if loc else f"// {entity_name}"
                    out.append(f"{header}\n{snippet}")
                if len(out) >= _MAX_KEY_SNIPPETS:
                    break

        if not out and not isinstance(chunk_result, BaseException):
            log.debug(
                "no_code_snippets_found",
                module_names=module_names[:3],
                snippet_result_type=type(snippet_result).__name__,
                chunk_result_type=type(chunk_result).__name__,
            )

        return out

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
                "name": str(row.get("name") or ""),
                "file": str(row.get("file") or ""),
                "labels": labels,
            })
        return out

    async def _query_implementations(self, module_names: list[str]) -> list[dict]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            result = await self._graph.execute_query(
                _IMPLEMENTS_CY,
                {"names": module_names},
            )
        except Exception:
            log.warning("graph_implements_query_failed", exc_info=True)
            return []
        rows = getattr(result, "data", None) or []
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            impl = str(row.get("impl_name", "") or "")
            intf = str(row.get("interface_name", "") or "")
            if not impl or not intf or (impl, intf) in seen:
                continue
            seen.add((impl, intf))
            out.append({
                "impl_name": impl,
                "interface_name": intf,
                "impl_repo": str(row.get("impl_repo", "") or ""),
                "intf_repo": str(row.get("intf_repo", "") or ""),
                "module_name": str(row.get("module_name", "") or ""),
            })
        return out

    async def _query_callers(self, module_names: list[str]) -> list[dict]:
        if (
            not module_names
            or self._graph is None
            or not hasattr(self._graph, "execute_query")
        ):
            return []
        try:
            result = await self._graph.execute_query(
                _CALLERS_CY,
                {"names": module_names},
            )
        except Exception:
            log.warning("graph_callers_query_failed", exc_info=True)
            return []
        rows = getattr(result, "data", None) or []
        out: list[dict] = []
        seen: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            caller = str(row.get("caller_name", "") or "")
            target = str(row.get("target_name", "") or "")
            if not caller or not target or (caller, target) in seen:
                continue
            seen.add((caller, target))
            out.append({
                "caller_name": caller,
                "target_name": target,
                "caller_repo": str(row.get("caller_repo", "") or ""),
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
                if role in ("framework_noise", "data_model"):
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
                    "fields": [str(f) for f in (props.get("fields", []) or [])[:_MAX_FIELDS_PER_MODEL]],
                })
        return data_models[:_MAX_DATA_MODELS]

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
            "WHERE wp.path = $wiki_root "
            "OR wp.path STARTS WITH $wiki_under "
            "RETURN wp.title AS title, "
            "coalesce(wp.executive_summary, '') AS executive_summary, "
            "left(wp.content, 500) AS content_head "
            "ORDER BY wp.generated_at DESC "
            "LIMIT 5"
        )
        try:
            result = await self._wiki.execute_query(
                q, {"wiki_root": wiki_root, "wiki_under": wiki_under},
            )
        except Exception:
            log.warning("wiki_existing_context_query_failed", exc_info=True)
            return ""
        rows = getattr(result, "data", None) or []
        summaries: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            title = str(row.get("title", "") or "").strip()
            text = str(row.get("executive_summary", "") or "").strip()
            if not text:
                head = str(row.get("content_head", "") or "").strip()
                first_para = head.split("\n\n")[0] if head else ""
                text = first_para[:300].strip()
            if text and title:
                summaries.append(f"- **{title}**: {text}")
            elif text:
                summaries.append(f"- {text}")
        return "\n".join(summaries)
