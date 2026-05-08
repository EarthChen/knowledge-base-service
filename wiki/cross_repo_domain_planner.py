"""Classify modules from multiple repositories into shared business domains."""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from core.log import get_logger
from store.schema import GraphNode
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.dependency_graph import HierarchicalDecomposer, ModuleGraph, ModuleInfo
from wiki.json_robust import parse_json_robust_sync
from wiki.prompts import SYSTEM_JSON_ONLY

if TYPE_CHECKING:
    from wiki.llm_port import LLMPort
    from wiki.dependency_graph import DomainNode

log = get_logger(__name__)


@dataclass
class _TriageResult:
    """Result of Phase 1 triage: how to handle each new module."""
    assignments: dict[tuple[str, str], str]
    new_domains: dict[str, list[tuple[str, str]]]
    reclassify_domains: list[str]

    @classmethod
    def assign_all_to_infra(
        cls, pairs: list[tuple[str, str]], infra_label: str,
    ) -> "_TriageResult":
        return cls(
            assignments={p: infra_label for p in pairs},
            new_domains={},
            reclassify_domains=[],
        )


def clean_repo_path(path: str) -> str:
    """Remove GitLab group prefix from repository path.

    'ultron/ultron-basic-user' → 'ultron-basic-user'
    """
    if "/" in path:
        return path.rsplit("/", 1)[-1]
    return path


class CrossRepoBusinessDomainPlanner:
    """Batch LLM classification across repositories, with per-repo fallback for large inputs."""

    def __init__(
        self,
        llm: LLMPort | None,
        *,
        infrastructure_label: str = "__infrastructure__",
        batch_threshold: int = 100,
        sub_batch_size: int = 80,
        max_concurrency: int = 3,
        max_tokens_per_batch: int = 30_000,
    ) -> None:
        self._llm = llm
        self._infrastructure_label = infrastructure_label
        self._batch_threshold = batch_threshold
        self._sub_batch_size = sub_batch_size
        self._max_concurrency = max_concurrency
        self._max_tokens_per_batch = max_tokens_per_batch
        self._metadata_cache: dict[tuple[str, str], dict[str, str | int | float | list[str]]] = {}

    def create_hierarchical_decomposer(
        self,
        *,
        max_depth: int = 4,
        min_modules_for_nesting: int = 3,
        max_tokens_per_batch: int | None = None,
    ) -> HierarchicalDecomposer | None:
        """Future pipeline hook for nested LLM domain trees; flat `classify()` remains default."""
        if self._llm is None:
            return None
        mtpb = (
            max_tokens_per_batch
            if max_tokens_per_batch is not None
            else self._max_tokens_per_batch
        )
        return HierarchicalDecomposer(
            self._llm,
            max_depth=max_depth,
            min_modules_for_nesting=min_modules_for_nesting,
            max_tokens_per_batch=mtpb,
        )

    async def classify_hierarchical(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
        store: Any,
    ) -> tuple[dict[str, list[tuple[str, str]]], list | None]:
        """Classify modules and optionally return a nested domain tree.

        Returns:
            (flat_domain_mapping, domain_tree_or_none)
        """
        flat_result = await self.classify(business_id, all_modules)

        domain_tree = None
        decomposer = self.create_hierarchical_decomposer()
        if decomposer is not None and store is not None:
            try:
                all_module_infos: list[ModuleInfo] = []
                for _repo_id, modules in all_modules.items():
                    for m in modules:
                        name = m.properties.get("name", "")
                        if isinstance(name, str) and name:
                            all_module_infos.append(
                                ModuleInfo(
                                    name=name,
                                    path=str(m.properties.get("path", "")),
                                    uid=m.uid,
                                    summary=str(
                                        m.properties.get("business_summary", "")
                                        or m.properties.get("docstring", "")
                                        or ""
                                    ),
                                    semantic_roles=list(m.properties.get("semantic_roles", []) or []),
                                )
                            )

                if all_module_infos:
                    module_graph = ModuleGraph(modules=all_module_infos, edges=[], entry_points=[])
                    domain_tree = await decomposer.decompose(all_module_infos, module_graph)
                    log.info(
                        "hierarchical_decomposition_done",
                        business_id=business_id,
                        domains=len(domain_tree) if domain_tree else 0,
                    )
            except Exception:
                log.warning(
                    "hierarchical_decomposition_failed",
                    business_id=business_id,
                    exc_info=True,
                )

        return flat_result, domain_tree

    async def classify(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
        pre_groups: list | None = None,
    ) -> dict[str, list[tuple[str, str]]]:
        self._metadata_cache = self._build_metadata_cache(all_modules)
        pairs_in_order = self._all_pairs_in_order(all_modules)
        if not pairs_in_order:
            return {}

        if self._llm is None:
            return self._all_infrastructure(pairs_in_order)

        try:
            if len(pairs_in_order) <= self._batch_threshold:
                return await self._classify_single_batch(
                    business_id, pairs_in_order, pre_groups=pre_groups
                )
            return await self._classify_multi_batch(business_id, all_modules, pairs_in_order, pre_groups=pre_groups)
        except Exception:
            log.warning(
                "cross_repo_business_domain_classification_failed",
                business_id=business_id,
                exc_info=True,
            )
            return self._all_infrastructure(pairs_in_order)

    async def classify_incremental(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
    ) -> tuple[dict[str, list[tuple[str, str]]], set[str]]:
        """Two-phase incremental domain classification.

        Phase 1 (triage): lightweight LLM call that decides for each new module:
          - assign to an existing domain
          - create a new domain
          - flag an existing domain for reclassification

        Phase 2 (reclassify, only when needed): full classification of the
        flagged domains' modules + relevant new modules.  Unaffected domains
        are preserved as-is.
        """
        self._metadata_cache = self._build_metadata_cache(all_modules)

        existing: dict[str, list[tuple[str, str]]] = {}
        new_modules: dict[str, list[GraphNode]] = {}

        for repo_id, modules in all_modules.items():
            for m in modules:
                name = m.properties.get("name")
                if not isinstance(name, str) or not name:
                    continue
                domain = m.properties.get("business_domain")
                if isinstance(domain, str) and domain.strip():
                    existing.setdefault(domain.strip(), []).append((repo_id, name))
                else:
                    new_modules.setdefault(repo_id, []).append(m)

        new_pairs = self._all_pairs_in_order(new_modules) if new_modules else []

        if not new_pairs:
            log.info(
                "incremental_classify_no_new_modules",
                business_id=business_id,
                existing_domains=len(existing),
            )
            return existing, set()

        log.info(
            "incremental_classify_start",
            business_id=business_id,
            existing_modules=sum(len(v) for v in existing.values()),
            new_modules=len(new_pairs),
            existing_domains=sorted(existing.keys()),
        )

        if self._llm is None:
            existing.setdefault(self._infrastructure_label, []).extend(new_pairs)
            return existing, {self._infrastructure_label}

        max_retries = 2
        triage: _TriageResult | None = None
        for attempt in range(max_retries + 1):
            try:
                triage = await self._triage_new_modules(
                    business_id, new_pairs, existing,
                )
                break
            except Exception:
                if attempt < max_retries:
                    log.warning(
                        "incremental_triage_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        exc_info=True,
                    )
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    log.warning("incremental_triage_failed_after_retries", exc_info=True)
        if triage is None:
            existing.setdefault(self._infrastructure_label, []).extend(new_pairs)
            return existing, {self._infrastructure_label}

        affected: set[str] = set()
        for pair, domain in triage.assignments.items():
            existing.setdefault(domain, []).append(pair)
            affected.add(domain)

        for domain_name, pairs in triage.new_domains.items():
            existing.setdefault(domain_name, []).extend(pairs)
            affected.add(domain_name)

        if not triage.reclassify_domains:
            log.info(
                "incremental_classify_done_no_reclass",
                business_id=business_id,
                assigned=len(triage.assignments),
                new_domains=len(triage.new_domains),
            )
            return existing, affected

        log.info(
            "incremental_reclassify_triggered",
            business_id=business_id,
            affected_domains=triage.reclassify_domains,
        )
        reclassified: dict[str, list[tuple[str, str]]] | None = None
        for attempt in range(max_retries + 1):
            try:
                reclassified = await self._reclassify_affected_domains(
                    business_id, triage.reclassify_domains, existing,
                )
                break
            except Exception:
                if attempt < max_retries:
                    log.warning(
                        "incremental_reclassify_retry",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        exc_info=True,
                    )
                    await asyncio.sleep(1 * (attempt + 1))
                else:
                    log.warning("incremental_reclassify_failed_after_retries", exc_info=True)

        if reclassified is not None:
            for domain_name in triage.reclassify_domains:
                existing.pop(domain_name, None)
                affected.add(domain_name)
            for domain_name, pairs in reclassified.items():
                existing.setdefault(domain_name, []).extend(pairs)
                affected.add(domain_name)
        else:
            affected.update(triage.reclassify_domains)

        return existing, affected

    async def _triage_new_modules(
        self,
        business_id: str,
        new_pairs: list[tuple[str, str]],
        existing: dict[str, list[tuple[str, str]]],
    ) -> "_TriageResult":
        """Phase 1: lightweight LLM call to decide how to handle each new module."""
        assert self._llm is not None

        domain_overview: list[dict[str, Any]] = []
        for domain_name, pairs in sorted(existing.items()):
            sample = [p[1] for p in pairs[:5]]
            domain_overview.append({
                "domain": domain_name,
                "module_count": len(pairs),
                "sample_modules": sample,
            })

        new_rows: list[dict[str, str]] = []
        for repo_id, name in new_pairs:
            new_rows.append({
                "repository": clean_repo_path(repo_id),
                "name": name,
                "summary": self._module_summary(repo_id, name),
            })

        prompt = (
            "You are classifying NEW modules into an existing business domain structure.\n\n"
            f"Business ID: {business_id}\n\n"
            f"Existing domains:\n{json.dumps(domain_overview, indent=2, ensure_ascii=False)}\n\n"
            f"New modules to classify:\n{json.dumps(new_rows, indent=2, ensure_ascii=False)}\n\n"
            "For each new module, decide one of:\n"
            "1. Assign to an existing domain (if it fits well)\n"
            "2. Create a new domain (if no existing domain is appropriate)\n"
            "3. Flag a domain for reclassification (if the new module reveals that "
            "an existing domain should be split or reorganized)\n\n"
            "Return ONLY valid JSON:\n"
            "{\n"
            '  "assignments": [{"module": "name", "repo": "repo-id", "domain": "ExistingDomainName"}],\n'
            '  "new_domains": {"NewDomainName": [["repo-id", "module-name"]]},\n'
            '  "reclassify_domains": ["DomainNameThatNeedsReorg"]\n'
            "}"
        )
        if hasattr(self._llm, "complete_json"):
            messages = [
                {"role": "system", "content": SYSTEM_JSON_ONLY},
                {"role": "user", "content": prompt},
            ]
            try:
                parsed = await self._llm.complete_json(messages, {})
            except (ValueError, Exception):
                log.warning(
                    "cross_repo_triage_complete_json_failed",
                    business_id=business_id,
                    exc_info=True,
                )
                raise
        else:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = parse_json_robust_sync(raw)
        if not isinstance(parsed, dict):
            raise ValueError(f"LLM triage response is not a valid JSON object: {raw[:200]}")

        assignments: dict[tuple[str, str], str] = {}
        for item in parsed.get("assignments", []):
            if not isinstance(item, dict):
                continue
            mod = str(item.get("module", "") or "")
            repo = str(item.get("repo", "") or "")
            domain = str(item.get("domain", "") or "")
            if mod and domain:
                matched = self._find_pair(new_pairs, repo, mod)
                if matched:
                    assignments[matched] = domain

        new_domains: dict[str, list[tuple[str, str]]] = {}
        for domain_name, pairs_raw in (parsed.get("new_domains") or {}).items():
            if not isinstance(pairs_raw, list):
                continue
            for pair in pairs_raw:
                if isinstance(pair, list) and len(pair) >= 2:
                    matched = self._find_pair(new_pairs, str(pair[0]), str(pair[1]))
                    if matched:
                        new_domains.setdefault(str(domain_name), []).append(matched)

        reclassify = [
            str(d) for d in (parsed.get("reclassify_domains") or [])
            if isinstance(d, str) and d in existing
        ]

        unassigned = [
            p for p in new_pairs
            if p not in assignments
            and not any(p in pairs for pairs in new_domains.values())
        ]
        if unassigned:
            all_known_domains = list(existing.keys()) + list(new_domains.keys())
            remaining = await self._classify_remaining(unassigned, all_known_domains)
            for pair, domain in remaining.items():
                assignments[pair] = domain

        return _TriageResult(
            assignments=assignments,
            new_domains=new_domains,
            reclassify_domains=reclassify,
        )

    @staticmethod
    def _find_pair(
        pairs: list[tuple[str, str]], repo_hint: str, module_name: str,
    ) -> tuple[str, str] | None:
        """Find a pair by module name, tolerating cleaned repo names."""
        for p in pairs:
            if p[1] == module_name:
                if not repo_hint or repo_hint in p[0] or clean_repo_path(p[0]) == repo_hint:
                    return p
        return None

    async def _classify_remaining(
        self,
        unassigned: list[tuple[str, str]],
        known_domains: list[str],
    ) -> dict[tuple[str, str], str]:
        """Focused LLM call for modules that triage missed."""
        assert self._llm is not None

        rows = [
            {
                "repository": clean_repo_path(repo_id),
                "name": name,
                "summary": self._module_summary(repo_id, name),
            }
            for repo_id, name in unassigned
        ]
        prompt = (
            "Classify each module into one of the existing domains, or propose a new domain.\n\n"
            f"Existing domains: {json.dumps(known_domains, ensure_ascii=False)}\n\n"
            f"Modules:\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY valid JSON: an object mapping module names to domain names.\n"
            'Example: {"ModuleA": "ExistingDomain", "ModuleB": "NewDomainName"}'
        )
        try:
            if hasattr(self._llm, "complete_json"):
                messages = [
                    {"role": "system", "content": SYSTEM_JSON_ONLY},
                    {"role": "user", "content": prompt},
                ]
                try:
                    parsed = await self._llm.complete_json(messages, {})
                except (ValueError, Exception):
                    log.warning("classify_remaining_failed", exc_info=True)
                    return {p: self._infrastructure_label for p in unassigned}
            else:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                parsed = parse_json_robust_sync(raw)
        except Exception:
            log.warning("classify_remaining_failed", exc_info=True)
            return {p: self._infrastructure_label for p in unassigned}

        if not isinstance(parsed, dict):
            return {p: self._infrastructure_label for p in unassigned}

        result: dict[tuple[str, str], str] = {}
        for pair in unassigned:
            domain = parsed.get(pair[1])
            if isinstance(domain, str) and domain.strip():
                result[pair] = domain.strip()
            else:
                result[pair] = self._infrastructure_label
        return result

    async def _reclassify_affected_domains(
        self,
        business_id: str,
        affected_domain_names: list[str],
        current_mapping: dict[str, list[tuple[str, str]]],
    ) -> dict[str, list[tuple[str, str]]]:
        """Phase 2: reclassify only the affected domains' modules."""
        assert self._llm is not None

        affected_pairs: list[tuple[str, str]] = []
        for domain_name in affected_domain_names:
            affected_pairs.extend(current_mapping.get(domain_name, []))

        if not affected_pairs:
            return {}

        rows: list[dict[str, str]] = []
        for repo_id, name in affected_pairs:
            rows.append({
                "repository": clean_repo_path(repo_id),
                "name": name,
                "summary": self._module_summary(repo_id, name),
            })

        unaffected = [
            d for d in current_mapping if d not in affected_domain_names
        ]
        context = f"Other domains (unchanged): {json.dumps(unaffected, ensure_ascii=False)}" if unaffected else ""

        prompt = (
            "Reclassify the following modules into business domains.\n"
            f"These modules were previously in domains: {json.dumps(affected_domain_names, ensure_ascii=False)}\n"
            "Split, merge, or rename domains as needed for better organization.\n"
            f'{context}\n\n'
            f"Business ID: {business_id}\n\n"
            f"Modules:\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY valid JSON: an object whose keys are domain names and whose "
            "values are arrays of [repository_id, module_name] pairs."
        )
        if hasattr(self._llm, "complete_json"):
            messages = [
                {"role": "system", "content": SYSTEM_JSON_ONLY},
                {"role": "user", "content": prompt},
            ]
            try:
                data = await self._llm.complete_json(messages, {})
            except (ValueError, Exception):
                log.warning(
                    "reclassify_affected_domains_complete_json_failed",
                    business_id=business_id,
                    exc_info=True,
                )
                parsed = {}
            else:
                parsed = self._cross_repo_map_from_dict(data)
        else:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = self._parse_cross_repo_map(raw)
        if not parsed:
            original: dict[str, list[tuple[str, str]]] = {}
            for dn in affected_domain_names:
                pairs_in_domain = current_mapping.get(dn, [])
                if pairs_in_domain:
                    original[dn] = list(pairs_in_domain)
            return original if original else {}

        valid = set(affected_pairs)
        return self._merge_llm_assignment(parsed, valid, affected_pairs)

    def _build_metadata_cache(
        self,
        all_modules: dict[str, list[GraphNode]],
    ) -> dict[tuple[str, str], dict[str, str | int | float | list[str]]]:
        cache: dict[tuple[str, str], dict[str, str | int | float | list[str]]] = {}
        for repo_id, modules in all_modules.items():
            for m in modules:
                name = m.properties.get("name")
                if not isinstance(name, str) or not name:
                    continue
                cache[(repo_id, name)] = dict(m.properties)
        return cache

    def _module_summary(self, repository_id: str, module_name: str) -> str:
        props = self._metadata_cache.get((repository_id, module_name), {})
        for key in ("business_summary", "docstring"):
            val = props.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    def _all_pairs_in_order(self, all_modules: dict[str, list[GraphNode]]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for repo_id in sorted(all_modules.keys()):
            for m in all_modules[repo_id]:
                name = m.properties.get("name")
                if isinstance(name, str) and name:
                    pairs.append((repo_id, name))
        return pairs

    def _all_infrastructure(self, pairs_in_order: list[tuple[str, str]]) -> dict[str, list[tuple[str, str]]]:
        return {self._infrastructure_label: list(pairs_in_order)}

    async def _classify_single_batch(
        self,
        business_id: str,
        pairs_in_order: list[tuple[str, str]],
        pre_groups: list | None = None,
    ) -> dict[str, list[tuple[str, str]]]:
        assert self._llm is not None
        valid_pairs = set(pairs_in_order)
        prompt = self._build_single_batch_prompt(
            business_id, pairs_in_order, pre_groups=pre_groups
        )
        if hasattr(self._llm, "complete_json"):
            messages = [
                {"role": "system", "content": SYSTEM_JSON_ONLY},
                {"role": "user", "content": prompt},
            ]
            try:
                data = await self._llm.complete_json(messages, {})
            except (ValueError, Exception):
                log.warning(
                    "cross_repo_single_batch_complete_json_failed",
                    business_id=business_id,
                    exc_info=True,
                )
                return self._all_infrastructure(pairs_in_order)
            parsed = self._cross_repo_map_from_dict(data)
        else:
            raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
            parsed = self._parse_cross_repo_map(raw)
        if not parsed:
            return self._all_infrastructure(pairs_in_order)
        return self._merge_llm_assignment(parsed, valid_pairs, pairs_in_order)

    async def _classify_multi_batch(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
        pairs_in_order: list[tuple[str, str]],
        pre_groups: list | None = None,
    ) -> dict[str, list[tuple[str, str]]]:
        assert self._llm is not None
        valid_pairs = set(pairs_in_order)
        planner = BusinessDomainPlanner(self._llm, infrastructure_label=self._infrastructure_label)
        per_repo: dict[str, dict[str, list[str]]] = {}
        for repo_id in sorted(all_modules.keys()):
            modules = all_modules[repo_id]
            if not modules:
                continue
            per_repo[repo_id] = await planner.classify(
                repo_id,
                modules,
                sub_batch_size=self._sub_batch_size,
                max_concurrency=self._max_concurrency,
            )

        try:
            prompt = self._build_lightweight_merge_prompt(business_id, per_repo, pre_groups=pre_groups)
            if hasattr(self._llm, "complete_json"):
                messages = [
                    {"role": "system", "content": SYSTEM_JSON_ONLY},
                    {"role": "user", "content": prompt},
                ]
                try:
                    merge_data = await self._llm.complete_json(messages, {})
                except (ValueError, Exception):
                    log.warning(
                        "cross_repo_lightweight_merge_json_failed",
                        business_id=business_id,
                        exc_info=True,
                    )
                    mapping = None
                else:
                    mapping = self._domain_name_mapping_from_dict(merge_data)
            else:
                raw = (await self._llm.generate(prompt, system=SYSTEM_JSON_ONLY)).strip()
                mapping = self._parse_domain_name_mapping(raw)
            if mapping:
                return self._apply_domain_name_mapping(mapping, per_repo, valid_pairs, pairs_in_order)
        except Exception:
            log.warning(
                "cross_repo_lightweight_merge_failed",
                business_id=business_id,
                exc_info=True,
            )

        return self._per_repo_fallback(per_repo, valid_pairs, pairs_in_order)

    def _build_single_batch_prompt(
        self,
        business_id: str,
        pairs_in_order: list[tuple[str, str]],
        pre_groups: list | None = None,
    ) -> str:
        rows: list[dict[str, str]] = []
        for repo_id, name in pairs_in_order:
            props = self._metadata_cache.get((repo_id, name), {})
            path = props.get("path")
            path_str = str(path) if path is not None else name
            rows.append(
                {
                    "repository": clean_repo_path(repo_id),
                    "name": name,
                    "summary": self._module_summary(repo_id, name),
                    "path": path_str,
                }
            )
        pre_group_section = ""
        if pre_groups:
            lines = [
                "Pre-grouping hints (modules that call each other or share directory structure):"
            ]
            for g in pre_groups:
                prefix = g.directory_prefix or "mixed"
                names = ", ".join(g.module_names[:10])
                lines.append(f"  Group {g.group_id + 1} ({prefix}): [{names}]")
            lines.append(
                "Use these groups as a REFERENCE — you may split or merge them as appropriate.\n"
            )
            pre_group_section = "\n".join(lines) + "\n"
        return (
            "Classify the following modules from multiple repositories into business domains.\n"
            "Use short, human-readable domain names (e.g. product areas).\n"
            "Place shared utilities, cross-cutting helpers, or generic support modules under "
            f'the domain key "{self._infrastructure_label}" when appropriate.\n\n'
            f"Business ID: {business_id}\n\n"
            f"Modules:\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n\n"
            f"{pre_group_section}"
            "Return ONLY valid JSON: an object whose keys are domain names and whose values are "
            "arrays of [repository_id, module_name] pairs. Each module_name must match a "
            '"name" from the input for the given repository_id.'
        )

    def _build_merge_prompt(
        self,
        business_id: str,
        per_repo: dict[str, dict[str, list[str]]],
    ) -> str:
        return (
            "Merge these per-repository business domain classifications into one unified "
            "cross-repository domain map.\n"
            "Align domains that clearly refer to the same business area; split or rename when "
            "needed for clarity.\n"
            f'Use "{self._infrastructure_label}" for ambiguous or shared infrastructure when appropriate.\n\n'
            f"Business ID: {business_id}\n\n"
            f"Per-repository domains (domain -> module names in that repo only):\n"
            f"{json.dumps(per_repo, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY valid JSON: an object whose keys are unified domain names and whose "
            "values are arrays of [repository_id, module_name] pairs. Every pair must appear "
            "in the input above."
        )

    def _build_lightweight_merge_prompt(
        self,
        business_id: str,
        per_repo: dict[str, dict[str, list[str]]],
        pre_groups: list | None = None,
    ) -> str:
        domain_names_per_repo: dict[str, list[str]] = {}
        for repo_id, domain_map in per_repo.items():
            domain_names_per_repo[repo_id] = sorted(domain_map.keys())

        pre_group_section = ""
        if pre_groups:
            lines = ["Cross-repo module relationship hints (modules that call each other):"]
            for g in pre_groups:
                prefix = g.directory_prefix or "mixed"
                names = ", ".join(g.module_names[:10])
                lines.append(f"  Group {g.group_id + 1} ({prefix}): [{names}]")
            lines.append("Consider grouping related domains when modules call each other.\n")
            pre_group_section = "\n".join(lines) + "\n"

        return (
            "Unify the following per-repository business domain names into a single "
            "consistent set of domain names across all repositories.\n"
            "Map similar domains to the same unified name "
            "(e.g. 'Auth' and 'Authentication' → pick one).\n"
            f'Use "{self._infrastructure_label}" for ambiguous infrastructure domains.\n\n'
            f"Business ID: {business_id}\n\n"
            f"Domain names per repository:\n{json.dumps(domain_names_per_repo, indent=2, ensure_ascii=False)}\n\n"
            f"{pre_group_section}"
            "Return ONLY valid JSON: an object whose keys are unified domain names and whose "
            "values are objects mapping repository_id to the original per-repo domain name.\n"
            "Every per-repo domain name must appear exactly once."
        )

    @staticmethod
    def _cross_repo_map_from_dict(data: Any) -> dict[str, list[tuple[str, str]]]:
        if not isinstance(data, dict):
            return {}
        out: dict[str, list[tuple[str, str]]] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, list):
                continue
            pairs: list[tuple[str, str]] = []
            for item in v:
                if isinstance(item, (list, tuple)) and len(item) == 2:
                    a, b = item
                    if isinstance(a, str) and isinstance(b, str) and a and b:
                        pairs.append((a, b))
            if pairs:
                out[k] = pairs
        return out

    @staticmethod
    def _domain_name_mapping_from_dict(data: Any) -> dict[str, dict[str, str]] | None:
        if not isinstance(data, dict):
            return None
        result: dict[str, dict[str, str]] = {}
        for unified_name, repo_map in data.items():
            if not isinstance(unified_name, str) or not isinstance(repo_map, dict):
                continue
            clean_map: dict[str, str] = {}
            for repo_id, per_repo_name in repo_map.items():
                if isinstance(repo_id, str) and isinstance(per_repo_name, str):
                    clean_map[repo_id] = per_repo_name
            if clean_map:
                result[unified_name] = clean_map
        return result if result else None

    def _parse_domain_name_mapping(
        self,
        raw: str,
    ) -> dict[str, dict[str, str]] | None:
        data = parse_json_robust_sync(raw)
        return self._domain_name_mapping_from_dict(data)

    def _apply_domain_name_mapping(
        self,
        mapping: dict[str, dict[str, str]],
        per_repo: dict[str, dict[str, list[str]]],
        valid_pairs: set[tuple[str, str]],
        pairs_in_order: list[tuple[str, str]],
    ) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        mapped_domains: set[tuple[str, str]] = set()  # (repo_id, per_repo_domain_name)

        for unified_name, repo_map in mapping.items():
            bucket: list[tuple[str, str]] = []
            for repo_id, per_repo_name in repo_map.items():
                modules = per_repo.get(repo_id, {}).get(per_repo_name, [])
                if not modules:
                    continue
                for mod_name in modules:
                    pair = (repo_id, mod_name)
                    if pair in valid_pairs:
                        bucket.append(pair)
                mapped_domains.add((repo_id, per_repo_name))
            if bucket:
                result[unified_name] = bucket

        # Add unmapped domains as-is
        for repo_id, domain_map in per_repo.items():
            for domain_name, modules in domain_map.items():
                if (repo_id, domain_name) not in mapped_domains:
                    bucket = [(repo_id, m) for m in modules if (repo_id, m) in valid_pairs]
                    if bucket:
                        result.setdefault(domain_name, []).extend(bucket)

        return self._merge_llm_assignment(result, valid_pairs, pairs_in_order)

    def _per_repo_fallback(
        self,
        per_repo: dict[str, dict[str, list[str]]],
        valid_pairs: set[tuple[str, str]],
        pairs_in_order: list[tuple[str, str]],
    ) -> dict[str, list[tuple[str, str]]]:
        result: dict[str, list[tuple[str, str]]] = {}
        for repo_id, domain_map in per_repo.items():
            for domain_name, modules in domain_map.items():
                bucket = [(repo_id, m) for m in modules if (repo_id, m) in valid_pairs]
                if bucket:
                    result.setdefault(domain_name, []).extend(bucket)
        return self._merge_llm_assignment(result, valid_pairs, pairs_in_order)

    def _parse_cross_repo_map(self, raw: str) -> dict[str, list[tuple[str, str]]]:
        data = parse_json_robust_sync(raw)
        return self._cross_repo_map_from_dict(data)

    def _merge_llm_assignment(
        self,
        parsed: dict[str, list[tuple[str, str]]],
        valid_pairs: set[tuple[str, str]],
        pairs_in_order: list[tuple[str, str]],
    ) -> dict[str, list[tuple[str, str]]]:
        clean_to_full: dict[str, str] = {}
        for rid, _ in pairs_in_order:
            c = clean_repo_path(rid)
            if c not in clean_to_full:
                clean_to_full[c] = rid

        def canonical_pair(repo_llm: str, mod_name: str) -> tuple[str, str] | None:
            p = (repo_llm, mod_name)
            if p in valid_pairs:
                return p
            full = clean_to_full.get(repo_llm)
            if full is not None:
                pf = (full, mod_name)
                if pf in valid_pairs:
                    return pf
            return None

        assigned: set[tuple[str, str]] = set()
        result: dict[str, list[tuple[str, str]]] = {}

        for domain, pairs in parsed.items():
            bucket: list[tuple[str, str]] = []
            for repo_llm, mod_name in pairs:
                canon = canonical_pair(repo_llm, mod_name)
                if canon is not None and canon not in assigned:
                    assigned.add(canon)
                    bucket.append(canon)
            if bucket:
                result[domain] = bucket

        missing = [p for p in pairs_in_order if p not in assigned]
        if missing:
            infra = list(result.get(self._infrastructure_label, []))
            seen = set(infra)
            for p in missing:
                if p not in seen:
                    infra.append(p)
                    seen.add(p)
            result[self._infrastructure_label] = infra

        return result
