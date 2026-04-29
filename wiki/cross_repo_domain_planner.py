"""Classify modules from multiple repositories into shared business domains."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from log import get_logger
from store.schema import GraphNode
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.dependency_graph import HierarchicalDecomposer, ModuleGraph, ModuleInfo

if TYPE_CHECKING:
    from wiki.context import LLMPort
    from wiki.dependency_graph import DomainNode

log = get_logger(__name__)

_SYSTEM_JSON = "Reply with JSON only. No markdown fences."


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
    ) -> dict[str, list[tuple[str, str]]]:
        self._metadata_cache = self._build_metadata_cache(all_modules)
        pairs_in_order = self._all_pairs_in_order(all_modules)
        if not pairs_in_order:
            return {}

        if self._llm is None:
            return self._all_infrastructure(pairs_in_order)

        try:
            if len(pairs_in_order) <= self._batch_threshold:
                return await self._classify_single_batch(business_id, pairs_in_order)
            return await self._classify_multi_batch(business_id, all_modules, pairs_in_order)
        except Exception:
            log.warning(
                "cross_repo_business_domain_classification_failed",
                business_id=business_id,
                exc_info=True,
            )
            return self._all_infrastructure(pairs_in_order)

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
    ) -> dict[str, list[tuple[str, str]]]:
        assert self._llm is not None
        valid_pairs = set(pairs_in_order)
        prompt = self._build_single_batch_prompt(business_id, pairs_in_order)
        raw = (await self._llm.generate(prompt, system=_SYSTEM_JSON)).strip()
        parsed = self._parse_cross_repo_map(raw)
        if not parsed:
            return self._all_infrastructure(pairs_in_order)
        return self._merge_llm_assignment(parsed, valid_pairs, pairs_in_order)

    async def _classify_multi_batch(
        self,
        business_id: str,
        all_modules: dict[str, list[GraphNode]],
        pairs_in_order: list[tuple[str, str]],
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

        prompt = self._build_merge_prompt(business_id, per_repo)
        raw = (await self._llm.generate(prompt, system=_SYSTEM_JSON)).strip()
        parsed = self._parse_cross_repo_map(raw)
        if not parsed:
            return self._all_infrastructure(pairs_in_order)
        return self._merge_llm_assignment(parsed, valid_pairs, pairs_in_order)

    def _build_single_batch_prompt(
        self,
        business_id: str,
        pairs_in_order: list[tuple[str, str]],
    ) -> str:
        rows: list[dict[str, str]] = []
        for repo_id, name in pairs_in_order:
            props = self._metadata_cache.get((repo_id, name), {})
            path = props.get("path")
            path_str = str(path) if path is not None else name
            rows.append(
                {
                    "repository": repo_id,
                    "name": name,
                    "summary": self._module_summary(repo_id, name),
                    "path": path_str,
                }
            )
        return (
            "Classify the following modules from multiple repositories into business domains.\n"
            "Use short, human-readable domain names (e.g. product areas).\n"
            "Place shared utilities, cross-cutting helpers, or generic support modules under "
            f'the domain key "{self._infrastructure_label}" when appropriate.\n\n'
            f"Business ID: {business_id}\n\n"
            f"Modules:\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n\n"
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

    def _parse_cross_repo_map(self, raw: str) -> dict[str, list[tuple[str, str]]]:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
            text = re.sub(r"\s*```$", "", text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return {}
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

    def _merge_llm_assignment(
        self,
        parsed: dict[str, list[tuple[str, str]]],
        valid_pairs: set[tuple[str, str]],
        pairs_in_order: list[tuple[str, str]],
    ) -> dict[str, list[tuple[str, str]]]:
        assigned: set[tuple[str, str]] = set()
        result: dict[str, list[tuple[str, str]]] = {}

        for domain, pairs in parsed.items():
            bucket: list[tuple[str, str]] = []
            for pair in pairs:
                if pair in valid_pairs and pair not in assigned:
                    assigned.add(pair)
                    bucket.append(pair)
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
