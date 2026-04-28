"""Classify repository modules into business domains via LLM, with sub-batch support."""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import TYPE_CHECKING

from log import get_logger
from store.schema import GraphNode

if TYPE_CHECKING:
    from wiki.context import LLMPort

log = get_logger(__name__)


class BusinessDomainPlanner:
    """Collect module metadata, then classify via LLM. Large inputs are split into
    concurrent sub-batches bounded by ``max_concurrency``."""

    def __init__(
        self,
        llm: LLMPort | None = None,
        infrastructure_label: str = "__infrastructure__",
    ) -> None:
        self._llm = llm
        self._infrastructure_label = infrastructure_label

    async def classify(
        self,
        repository_id: str,
        modules: list[GraphNode],
        *,
        sub_batch_size: int = 80,
        max_concurrency: int = 3,
    ) -> dict[str, list[str]]:
        if not modules:
            return {}

        names_in_order = self._module_names_in_order(modules)
        if not names_in_order:
            return {}

        valid_names = set(names_in_order)

        if self._llm is None:
            return {self._infrastructure_label: list(names_in_order)}

        sub_batch_size = max(1, sub_batch_size)
        max_concurrency = max(1, max_concurrency)

        if len(modules) <= sub_batch_size:
            try:
                return await self._classify_single_batch(
                    repository_id,
                    modules,
                    names_in_order,
                    valid_names,
                )
            except Exception:
                log.warning(
                    "business_domain_classification_failed",
                    repository_id=repository_id,
                    exc_info=True,
                )
                return self._all_infrastructure(names_in_order)

        batches = [
            modules[i : i + sub_batch_size]
            for i in range(0, len(modules), sub_batch_size)
        ]
        total_batches = len(batches)
        log.info(
            "domain_classify_start",
            repository_id=repository_id,
            module_count=len(modules),
            batch_count=total_batches,
            sub_batch_size=sub_batch_size,
            max_concurrency=max_concurrency,
        )

        t0 = time.monotonic()
        sem = asyncio.Semaphore(max_concurrency)
        batch_results: list[dict[str, list[str]]] = [{} for _ in range(total_batches)]
        failed_count = 0

        async def _run_batch(idx: int, batch: list[GraphNode]) -> None:
            nonlocal failed_count
            async with sem:
                batch_names = self._module_names_in_order(batch)
                batch_valid = set(batch_names)
                try:
                    log.debug(
                        "domain_classify_batch_start",
                        repository_id=repository_id,
                        batch_index=idx,
                        batch_size=len(batch),
                    )
                    bt = time.monotonic()
                    batch_results[idx] = await self._classify_single_batch(
                        repository_id,
                        batch,
                        batch_names,
                        batch_valid,
                    )
                    elapsed_ms = int((time.monotonic() - bt) * 1000)
                    log.info(
                        "domain_classify_batch_done",
                        repository_id=repository_id,
                        batch_index=idx,
                        domains_found=len(batch_results[idx]),
                        elapsed_ms=elapsed_ms,
                    )
                except Exception:
                    failed_count += 1
                    log.warning(
                        "domain_classify_batch_failed",
                        repository_id=repository_id,
                        batch_index=idx,
                        batch_size=len(batch),
                        exc_info=True,
                    )
                    batch_results[idx] = {self._infrastructure_label: batch_names}

        await asyncio.gather(*[_run_batch(i, b) for i, b in enumerate(batches)])

        merged: dict[str, list[str]] = {}
        for batch_result in batch_results:
            for domain, domain_modules in batch_result.items():
                merged.setdefault(domain, []).extend(domain_modules)

        total_ms = int((time.monotonic() - t0) * 1000)
        log.info(
            "domain_classify_done",
            repository_id=repository_id,
            total_domains=len(merged),
            batch_count=total_batches,
            failed_batches=failed_count,
            total_elapsed_ms=total_ms,
        )

        return self._ensure_all_assigned(merged, valid_names, names_in_order)

    async def _classify_single_batch(
        self,
        repository_id: str,
        modules: list[GraphNode],
        names_in_order: list[str],
        valid_names: set[str],
    ) -> dict[str, list[str]]:
        metadata = self._collect_metadata(modules)
        prompt = self._build_prompt(repository_id, metadata)
        raw = (
            await self._llm.generate(
                prompt, system="Reply with JSON only. No markdown fences.",
            )
        ).strip()
        parsed = self._parse_domain_map(raw)
        if not parsed:
            return self._all_infrastructure(names_in_order)
        return self._merge_llm_assignment(parsed, valid_names, names_in_order)

    def _all_infrastructure(self, names_in_order: list[str]) -> dict[str, list[str]]:
        return {self._infrastructure_label: list(names_in_order)}

    def _ensure_all_assigned(
        self,
        merged: dict[str, list[str]],
        valid_names: set[str],
        names_in_order: list[str],
    ) -> dict[str, list[str]]:
        assigned: set[str] = set()
        for names in merged.values():
            assigned.update(names)
        missing = [n for n in names_in_order if n in valid_names and n not in assigned]
        if missing:
            merged.setdefault(self._infrastructure_label, []).extend(missing)
        return merged

    def _module_names_in_order(self, modules: list[GraphNode]) -> list[str]:
        out: list[str] = []
        for m in modules:
            name = m.properties.get("name")
            if isinstance(name, str) and name:
                out.append(name)
        return out

    def _collect_metadata(self, modules: list[GraphNode]) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for m in modules:
            name = m.properties.get("name")
            if not isinstance(name, str) or not name:
                continue
            summary = m.properties.get("business_summary")
            path = m.properties.get("path")
            rows.append(
                {
                    "name": name,
                    "business_summary": summary if isinstance(summary, str) else "",
                    "path": str(path) if path is not None else name,
                }
            )
        return rows

    def _build_prompt(self, repository_id: str, metadata: list[dict[str, str]]) -> str:
        return (
            "Classify the following repository modules into business domains.\n"
            "Use short, human-readable domain names (e.g. product areas).\n"
            "Place shared utilities, cross-cutting helpers, or generic support modules under "
            f'the domain key "{self._infrastructure_label}" when appropriate.\n\n'
            f"Repository: {repository_id}\n\n"
            f"Modules:\n{json.dumps(metadata, indent=2, ensure_ascii=False)}\n\n"
            "Return ONLY valid JSON: an object whose keys are domain names and values are "
            'arrays of module names (each must match a "name" from the input).'
        )

    def _parse_domain_map(self, raw: str) -> dict[str, list[str]]:
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
        out: dict[str, list[str]] = {}
        for k, v in data.items():
            if not isinstance(k, str):
                continue
            if not isinstance(v, list):
                continue
            names: list[str] = []
            for item in v:
                if isinstance(item, str) and item:
                    names.append(item)
            if names:
                out[k] = names
        return out

    def _merge_llm_assignment(
        self,
        parsed: dict[str, list[str]],
        valid_names: set[str],
        names_in_order: list[str],
    ) -> dict[str, list[str]]:
        assigned: set[str] = set()
        result: dict[str, list[str]] = {}

        for domain, names in parsed.items():
            bucket: list[str] = []
            for n in names:
                if n in valid_names and n not in assigned:
                    assigned.add(n)
                    bucket.append(n)
            if bucket:
                result[domain] = bucket

        missing = [n for n in names_in_order if n not in assigned]
        if missing:
            infra = list(result.get(self._infrastructure_label, []))
            seen = set(infra)
            for n in missing:
                if n not in seen:
                    infra.append(n)
                    seen.add(n)
            result[self._infrastructure_label] = infra

        return result
