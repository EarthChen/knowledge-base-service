"""Wiki page enrichment coordination: trigger, background execution, status."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from core.log import get_logger
from wiki.models import (
    ImportanceTier,
    PageType,
    WikiConfig,
    WikiPage,
    WikiPageMetadata,
)
from wiki.errors import WikiRepoNotFoundError

log = get_logger(__name__)


class WikiEnrichmentCoordinator:
    """Coordinates page enrichment: triggers, background runs, status queries."""

    _enrichment_running: dict[str, str] = {}

    def __init__(
        self,
        store: Any | None,
        graph: Any,
        wiki_cfg: Any,
        persistence: Any,
        llm_resolver: Callable[[str | None], Any | None],
        repository_exists: Callable[[str], Awaitable[bool]],
        deferred_enrichment: Any | None = None,
        supervisor: Any | None = None,
    ) -> None:
        self._store = store
        self._graph = graph
        self._wiki_cfg = wiki_cfg
        self._persistence = persistence
        self._resolve_llm_port = llm_resolver
        self._repository_exists = repository_exists
        self._deferred_enrichment = deferred_enrichment
        self._supervisor = supervisor
        self._enrichment_lock = asyncio.Lock()

    async def _require_repo(self, repository: str) -> None:
        if not await self._repository_exists(repository):
            raise WikiRepoNotFoundError(repository)

    async def get_enrichment_status(
        self,
        repository: str,
        *,
        verify_repository: bool = True,
    ) -> dict[str, Any]:
        """Return enrichment level distribution for wiki pages."""
        if verify_repository:
            await self._require_repo(repository)
        if self._store is None or not hasattr(self._store, "execute_query"):
            return {
                "repository": repository,
                "total_pages": 0,
                "base": 0,
                "enriched": 0,
                "encyclopedia": 0,
            }
        q = (
            "MATCH (p:WikiPage {repository: $repo}) "
            "RETURN p.enrichment_level AS level, count(p) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        counts: dict[str, int] = {"base": 0, "enriched": 0, "encyclopedia": 0}
        total = 0
        for row in getattr(result, "raw", []) or []:
            raw_level = row[0]
            if raw_level is None or raw_level == "":
                level = "base"
            else:
                level = str(raw_level)
            cnt = int(row[1])
            counts[level] = counts.get(level, 0) + cnt
            total += cnt
        return {"repository": repository, "total_pages": total, **counts}

    async def trigger_enrichment(
        self,
        repository: str,
        *,
        verify_repository: bool = True,
    ) -> dict[str, Any]:
        """Trigger enrichment for eligible wiki pages.

        Counts pages at BASE enrichment level and starts a background
        enrichment task if eligible pages exist.
        """
        if verify_repository:
            await self._require_repo(repository)
        if not getattr(self._wiki_cfg, "enrichment_enabled", True):
            return {
                "eligible_pages": 0,
                "repository": repository,
                "status": "skipped",
                "reason": "Enrichment is disabled",
            }
        llm_port = self._resolve_llm_port(None)
        if self._store is None or llm_port is None:
            return {
                "eligible_pages": 0,
                "repository": repository,
                "status": "skipped",
                "reason": "LLM or store not available",
            }
        q = (
            "MATCH (p:WikiPage {repository: $repo}) "
            "WHERE p.enrichment_level IS NULL OR p.enrichment_level = 'base' "
            "OR p.enrichment_level = '' "
            "RETURN count(p) AS cnt"
        )
        result = await self._store.execute_query(q, {"repo": repository})
        rows = getattr(result, "raw", []) or []
        eligible_pages = int(rows[0][0]) if rows else 0

        if eligible_pages == 0:
            return {
                "eligible_pages": 0,
                "repository": repository,
                "status": "skipped",
            }

        async with self._enrichment_lock:
            existing_task = self._enrichment_running.get(repository)
            if existing_task is not None:
                return {
                    "task_id": existing_task,
                    "eligible_pages": eligible_pages,
                    "repository": repository,
                    "status": "already_running",
                }

            task_id = f"enrich-{uuid.uuid4().hex[:12]}"
            self._enrichment_running[repository] = task_id
            if self._supervisor is not None:
                self._supervisor.spawn(
                    lambda r=repository,
                    lp=llm_port,
                    tid=task_id: self.run_enrichment_background(r, lp, tid),
                    name="indexing:enrichment-bg",
                    max_retries=2,
                )
            else:
                asyncio.create_task(
                    self.run_enrichment_background(repository, llm_port, task_id),
                    name=f"enrichment-{task_id}",
                )
        return {
            "task_id": task_id,
            "eligible_pages": eligible_pages,
            "repository": repository,
            "status": "started",
        }

    async def run_enrichment_background(
        self,
        repository: str,
        llm_port: Any,
        task_id: str,
    ) -> None:
        """Background task: enrich eligible pages using AsyncEnrichmentPipeline."""
        try:
            from wiki.async_enrichment import AsyncEnrichmentPipeline

            if self._store is None:
                log.info("enrichment_bg_no_store", task_id=task_id, repository=repository)
                return

            q = (
                "MATCH (p:WikiPage {repository: $repo}) "
                "WHERE p.enrichment_level IS NULL OR p.enrichment_level = 'base' "
                "OR p.enrichment_level = '' "
                "RETURN p.path AS path, p.content AS content, p.title AS title, "
                "coalesce(p.page_type, '') AS pt, coalesce(p.importance_tier, '') AS tier, "
                "coalesce(p.language, 'zh') AS lang"
            )
            result = await self._store.execute_query(q, {"repo": repository})
            rows = getattr(result, "raw", []) or []
            if not rows:
                log.info("enrichment_bg_no_pages", task_id=task_id, repository=repository)
                return

            pages: list[WikiPage] = []
            page_tier_map: dict[str, ImportanceTier] = {}
            _wiki_language = "zh"
            for row in rows:
                page_path = str(row[0] or "")
                if not page_path:
                    continue
                content = str(row[1] or "")
                title = str(row[2] or "")
                pt_raw = str(row[3] or "").strip()
                tier_raw = row[4]
                _row_lang = str(row[5] or "").strip() if len(row) > 5 else ""
                if _row_lang:
                    _wiki_language = _row_lang
                try:
                    pt = PageType(pt_raw) if pt_raw else PageType.MODULE_OVERVIEW
                except ValueError:
                    pt = PageType.MODULE_OVERVIEW
                if tier_raw is None or str(tier_raw).strip() == "":
                    tier = ImportanceTier.STANDARD
                else:
                    try:
                        tier = ImportanceTier(str(tier_raw).lower())
                    except ValueError:
                        tier = ImportanceTier.STANDARD
                page_tier_map[page_path] = tier
                pages.append(
                    WikiPage(
                        path=page_path,
                        title=title,
                        page_type=pt,
                        content=content,
                        diagrams=[],
                        source_locations=[],
                        metadata=WikiPageMetadata(
                            node_count=0,
                            edge_count=0,
                            generation_mode="full",
                            fallback_tier=None,
                        ),
                        method_locations=[],
                    )
                )

            pipeline = AsyncEnrichmentPipeline(
                llm_port,
                round1_enabled=getattr(self._wiki_cfg, "enrichment_round1_enabled", True),
                round2_enabled=getattr(self._wiki_cfg, "enrichment_round2_enabled", False),
            )

            targets = [
                (page, page_tier_map.get(page.path, ImportanceTier.STANDARD))
                for page in pages
                if page.page_type != PageType.REPO_OVERVIEW
            ]
            if not targets:
                log.info(
                    "enrichment_bg_no_targets",
                    task_id=task_id,
                    repository=repository,
                )
                return

            enrich_limit = max(1, int(getattr(self._wiki_cfg, "compose_concurrency", 3)))
            enrich_sem = asyncio.Semaphore(enrich_limit)

            async def _enrich_one(page: WikiPage, tier: ImportanceTier) -> None:
                async with enrich_sem:
                    await pipeline.enrich_page(
                        page,
                        entity_name=page.title,
                        entity_label=page.page_type.value,
                        tier=tier,
                        language=_wiki_language,
                    )

            tasks = [_enrich_one(p, t) for p, t in targets]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            work_pages: list[WikiPage] = []
            for (page, _tier), r in zip(targets, results, strict=True):
                if isinstance(r, Exception):
                    log.warning(
                        "enrichment_bg_enrich_failed",
                        path=page.path,
                        error=str(r),
                        exc_info=r,
                    )
                else:
                    work_pages.append(page)

            for p in work_pages:
                try:
                    await self._persistence.persist_pages_to_graph(
                        repository, [p], language=_wiki_language
                    )
                except Exception:
                    log.warning("enrichment_bg_persist_failed", path=p.path, exc_info=True)

            log.info(
                "enrichment_bg_done",
                task_id=task_id,
                repository=repository,
                enriched_count=len(work_pages),
            )
        except Exception:
            log.error("enrichment_bg_error", task_id=task_id, repository=repository, exc_info=True)
        finally:
            self._enrichment_running.pop(repository, None)

    async def enrich_pages_after_compose(
        self,
        pages: list[WikiPage],
        page_tier_map: dict[str, ImportanceTier],
        config: WikiConfig,
        llm_provider: str | None = None,
    ) -> None:
        app_cfg = self._wiki_cfg
        if not app_cfg.enrichment_enabled:
            return
        if config.mode == "structure":
            log.info(
                "enrichment_skipped_structure_mode",
                repository=config.repository,
                page_count=len(pages),
            )
            return
        llm_port = self._resolve_llm_port(llm_provider)
        if llm_port is None:
            return
        from wiki.async_enrichment import AsyncEnrichmentPipeline

        pipeline = AsyncEnrichmentPipeline(
            llm_port,
            round1_enabled=app_cfg.enrichment_round1_enabled,
            round2_enabled=app_cfg.enrichment_round2_enabled,
        )
        if not page_tier_map:
            log.info(
                "enrichment_skipped_no_tiers",
                reason="ImportanceScorer did not run; enrichment requires tier data",
            )
            return
        enrich_limit = max(1, int(getattr(self._wiki_cfg, "compose_concurrency", 3)))
        enrich_sem = asyncio.Semaphore(enrich_limit)

        async def _enrich_one(page: WikiPage, tier: ImportanceTier) -> None:
            async with enrich_sem:
                await pipeline.enrich_page(
                    page,
                    entity_name=page.title,
                    entity_label=page.page_type.value,
                    tier=tier,
                    language=config.language,
                )

        targets = [
            (page, page_tier_map.get(page.path, ImportanceTier.STANDARD))
            for page in pages
            if page.page_type != PageType.REPO_OVERVIEW
        ]
        tasks = [_enrich_one(p, t) for p, t in targets]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for (page, _tier), result in zip(targets, results, strict=True):
            if isinstance(result, Exception):
                log.warning(
                    "enrichment_compose_enrich_failed",
                    path=page.path,
                    error=str(result),
                    exc_info=result,
                )
