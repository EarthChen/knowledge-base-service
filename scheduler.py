"""Scheduled repository sync — periodic git pull + incremental re-index.

Stores per-repository schedule configs in a JSON file and runs
background tasks using asyncio to pull and re-index at configured intervals.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from config import Settings
from git_manager import GitManager, normalize_repo_name
from log import get_logger
from repo_registry import RepoRegistry
from service_registry import ServiceRegistry
from store.graph_queries import GraphQueryRepository

log = get_logger(__name__)

_DEFAULT_INTERVAL = 60
_MIN_INTERVAL = 5
_MAX_INTERVAL = 1440

SCHEDULE_FILE = Path(__file__).resolve().parent / "data" / "sync_schedules.json"


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class SyncScheduleConfig:
    """Persisted schedule row for one repository."""

    repo_name: str
    git_url: str
    branch: str | None
    interval_minutes: int = _DEFAULT_INTERVAL
    enabled: bool = True
    last_sync_at: str | None = None
    last_sync_status: str = "pending"
    last_sync_detail: str = ""
    created_at: str = field(default_factory=_utc_now_iso)

    def clamp_interval(self) -> None:
        self.interval_minutes = max(_MIN_INTERVAL, min(_MAX_INTERVAL, int(self.interval_minutes)))


class SyncScheduler:
    """Background asyncio scheduler for git pull + incremental indexing."""

    def __init__(
        self,
        registry: ServiceRegistry,
        settings: Settings,
        repo_registry: RepoRegistry | None = None,
        schedule_store_path: Path | None = None,
    ) -> None:
        self._registry = registry
        self._settings = settings
        self._repo_registry = repo_registry
        # Default lives under package ``data/``; production should pass the same
        # directory as ``RepoRegistry`` (parent of ``git.clone_base_path``).
        self._store_path = schedule_store_path or SCHEDULE_FILE
        self._schedules: dict[str, SyncScheduleConfig] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._state_lock = asyncio.Lock()
        self._sync_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._stopped = asyncio.Event()

    def _sync_lock_for(self, repo_name: str) -> asyncio.Lock:
        return self._sync_locks[repo_name]

    def _load(self) -> None:
        self._schedules = {}
        if not self._store_path.exists():
            return
        try:
            raw = json.loads(self._store_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("sync_schedule_load_failed", error=str(exc))
            return

        rows = raw.get("schedules") if isinstance(raw, dict) else raw
        if not isinstance(rows, list):
            return

        for item in rows:
            if not isinstance(item, dict):
                continue
            try:
                cfg = SyncScheduleConfig(
                    repo_name=str(item["repo_name"]),
                    git_url=str(item["git_url"]),
                    branch=item.get("branch"),
                    interval_minutes=int(item.get("interval_minutes", _DEFAULT_INTERVAL)),
                    enabled=bool(item.get("enabled", True)),
                    last_sync_at=item.get("last_sync_at"),
                    last_sync_status=str(item.get("last_sync_status", "pending")),
                    last_sync_detail=str(item.get("last_sync_detail", "")),
                    created_at=str(item.get("created_at", _utc_now_iso())),
                )
                cfg.clamp_interval()
                self._schedules[cfg.repo_name] = cfg
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("sync_schedule_row_skipped", error=str(exc))

    def _save_unlocked(self) -> None:
        self._store_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schedules": [asdict(c) for c in self._schedules.values()]}
        self._store_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    async def _save(self) -> None:
        async with self._state_lock:
            self._save_unlocked()

    def _cancel_task(self, repo_name: str) -> None:
        t = self._tasks.pop(repo_name, None)
        if t and not t.done():
            t.cancel()

    def _ensure_task(self, repo_name: str) -> None:
        cfg = self._schedules.get(repo_name)
        if not cfg or not cfg.enabled:
            self._cancel_task(repo_name)
            return
        self._cancel_task(repo_name)
        self._tasks[repo_name] = asyncio.create_task(
            self._schedule_loop(repo_name),
            name=f"sync_schedule:{repo_name}",
        )

    async def _schedule_loop(self, repo_name: str) -> None:
        log.info("sync_schedule_loop_started", repo=repo_name)
        try:
            while not self._stopped.is_set():
                cfg = self._schedules.get(repo_name)
                if cfg is None:
                    return
                interval_sec = max(_MIN_INTERVAL * 60, cfg.interval_minutes * 60)
                try:
                    await asyncio.wait_for(self._stopped.wait(), timeout=interval_sec)
                    return
                except TimeoutError:
                    pass

                cfg = self._schedules.get(repo_name)
                if cfg is None:
                    return
                if not cfg.enabled:
                    continue

                await self._run_sync_and_record(repo_name)
        except asyncio.CancelledError:
            log.info("sync_schedule_loop_cancelled", repo=repo_name)
            raise
        except Exception as exc:
            log.error("sync_schedule_loop_crash", repo=repo_name, error=str(exc))

    def _format_stats_summary(self, stats: dict[str, Any] | None) -> str:
        if not stats:
            return ""
        parts = [
            f"nodes={stats.get('nodes', 0)}",
            f"edges={stats.get('edges', 0)}",
            f"doc_nodes={stats.get('doc_nodes', 0)}",
        ]
        return ", ".join(parts)

    async def _resolve_canonical_repository_for_git(
        self,
        git_url: str,
        requested_name: str | None,
        registry: RepoRegistry,
        queries: GraphQueryRepository,
    ) -> tuple[str, str | None]:
        """Match ``main._resolve_canonical_repository_for_git`` — single name for URL + graph."""
        requested_stripped = requested_name.strip() if requested_name else None
        candidate = requested_stripped or normalize_repo_name(git_url)
        if not candidate:
            tail = git_url.strip().rstrip("/").split("/")[-1]
            if tail.endswith(".git"):
                tail = tail[:-4]
            candidate = tail or git_url.strip()

        existing = registry.get_canonical_name(git_url)
        if existing is None:
            existing = await queries.find_repository_by_git_url(git_url)

        if existing:
            if candidate != existing:
                return existing, (f"已忽略仓库名 '{candidate}'，沿用同一 git URL 已登记或已索引名称 '{existing}'")
            return existing, None

        return candidate, None

    async def _execute_git_sync(self, cfg: SyncScheduleConfig) -> dict[str, Any]:
        """Git pull (via GitManager) + incremental index — mirrors ``sync_repository`` (git_url path)."""
        svc = await self._registry.get_service("default")
        queries = GraphQueryRepository(svc.store)
        mgr = GitManager(self._settings.git)

        if self._repo_registry is None:
            return {
                "ok": False,
                "error": "Repository registry not initialized",
                "repository": cfg.repo_name,
                "git_pull": None,
                "index_stats": None,
            }

        result = await mgr.ensure_repo(cfg.git_url, branch=cfg.branch)
        if result["status"] in ("clone_failed", "pull_failed"):
            detail = str(result.get("detail", ""))
            return {
                "ok": False,
                "error": f"Git operation failed: {detail}",
                "repository": cfg.repo_name,
                "git_pull": result["status"],
                "index_stats": None,
            }

        repo_name, name_warn = await self._resolve_canonical_repository_for_git(
            cfg.git_url,
            cfg.repo_name,
            self._repo_registry,
            queries,
        )
        if name_warn:
            log.warning("scheduler_repository_name_canonicalized", detail=name_warn, git_url=cfg.git_url)

        repo_dir = result["directory"]
        pre_head = result.get("pre_head") or ""

        if result["status"] == "up_to_date":
            return {
                "ok": True,
                "repository": repo_name,
                "directory": repo_dir,
                "git_pull": "already_up_to_date",
                "index_stats": None,
                "summary": "Already up to date",
            }

        base_ref = "HEAD~1"
        head_ref = "HEAD"
        base = pre_head if pre_head else base_ref
        index_stats = await svc.indexer.index_incremental(
            repo_dir, base, head_ref, repository=repo_name,
        )

        if index_stats.get("doc_nodes", 0) > 0 or index_stats.get("nodes", 0) > 0:
            await queries.tag_unowned_nodes(
                repo_name,
                directory=repo_dir,
                git_url=cfg.git_url,
            )

        self._repo_registry.register(cfg.git_url, repo_name)

        return {
            "ok": True,
            "repository": repo_name,
            "directory": repo_dir,
            "git_pull": result["status"],
            "index_stats": index_stats,
            "summary": self._format_stats_summary(index_stats),
        }

    async def _run_sync_and_record(self, repo_name: str) -> dict[str, Any]:
        async with self._sync_lock_for(repo_name):
            cfg = self._schedules.get(repo_name)
            if cfg is None:
                return {"ok": False, "error": "Schedule not found"}

            log.info("sync_schedule_run_start", repo=repo_name)
            try:
                outcome = await self._execute_git_sync(cfg)
            except Exception as exc:
                log.error("sync_schedule_run_error", repo=repo_name, error=str(exc))
                async with self._state_lock:
                    cur = self._schedules.get(repo_name)
                    if cur:
                        cur.last_sync_at = _utc_now_iso()
                        cur.last_sync_status = "failed"
                        cur.last_sync_detail = str(exc)
                        self._save_unlocked()
                return {"ok": False, "repository": repo_name, "error": str(exc)}

            last_status: str
            last_detail: str
            async with self._state_lock:
                cur = self._schedules.get(repo_name)
                if not cur:
                    return outcome

                cur.last_sync_at = _utc_now_iso()
                if outcome.get("ok"):
                    cur.last_sync_status = "success"
                    if outcome.get("git_pull") == "already_up_to_date":
                        cur.last_sync_detail = str(outcome.get("summary", "Already up to date"))
                    elif outcome.get("index_stats") is None and outcome.get("git_pull") != "already_up_to_date":
                        cur.last_sync_detail = outcome.get("summary") or "No index changes"
                    else:
                        cur.last_sync_detail = outcome.get("summary") or self._format_stats_summary(
                            outcome.get("index_stats") or {}
                        )
                else:
                    cur.last_sync_status = "failed"
                    cur.last_sync_detail = str(outcome.get("error", "failed"))

                last_status = cur.last_sync_status
                last_detail = cur.last_sync_detail
                self._save_unlocked()

            log.info(
                "sync_schedule_run_done",
                repo=repo_name,
                status=last_status,
                detail=last_detail[:200],
            )
            return outcome

    async def start(self) -> None:
        """Load configs and start background tasks."""
        async with self._state_lock:
            self._load()
        for name in list(self._schedules.keys()):
            self._ensure_task(name)
        log.info("sync_scheduler_started", schedules=len(self._schedules))

    async def stop(self) -> None:
        """Cancel all background tasks."""
        self._stopped.set()
        for name, t in list(self._tasks.items()):
            if not t.done():
                t.cancel()
        for name, t in list(self._tasks.items()):
            try:
                await t
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                log.warning("sync_scheduler_task_join_error", repo=name, error=str(exc))
        self._tasks.clear()
        log.info("sync_scheduler_stopped")

    async def add_schedule(self, config: SyncScheduleConfig) -> SyncScheduleConfig:
        """Add or update a schedule."""
        config.clamp_interval()
        async with self._state_lock:
            existing = self._schedules.get(config.repo_name)
            if existing:
                config.created_at = existing.created_at
            self._schedules[config.repo_name] = config
            self._save_unlocked()
        self._ensure_task(config.repo_name)
        return config

    async def remove_schedule(self, repo_name: str) -> bool:
        """Remove a schedule."""
        async with self._state_lock:
            if repo_name not in self._schedules:
                return False
            del self._schedules[repo_name]
            self._save_unlocked()
        self._cancel_task(repo_name)
        return True

    async def list_schedules(self) -> list[SyncScheduleConfig]:
        """List all schedules."""
        async with self._state_lock:
            return sorted(self._schedules.values(), key=lambda c: c.repo_name)

    async def get_schedule(self, repo_name: str) -> SyncScheduleConfig | None:
        """Get a specific schedule."""
        async with self._state_lock:
            return self._schedules.get(repo_name)

    async def trigger_sync_now(self, repo_name: str) -> dict[str, Any]:
        """Manually trigger an immediate sync."""
        async with self._state_lock:
            if repo_name not in self._schedules:
                raise ValueError(f"No schedule for repository '{repo_name}'")
        return await self._run_sync_and_record(repo_name)
