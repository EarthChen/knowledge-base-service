"""Service registry — manages per-business KnowledgeBaseService instances.

Shares expensive resources (FalkorDB connection, EmbeddingGenerator, parsers)
across all businesses while maintaining isolated FalkorDB graphs per business.
"""

from __future__ import annotations

import asyncio
from typing import Any

from falkordb import FalkorDB

from config import Settings
from log import get_logger
from service import KnowledgeBaseService
from store.business_manager import BusinessManager, graph_name_for
from store.falkordb_store import FalkorDBStore

log = get_logger(__name__)


class ServiceRegistry:
    """Manages per-business KnowledgeBaseService instances, sharing expensive resources."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._db: FalkorDB | None = None
        self._business_mgr: BusinessManager | None = None
        self._services: dict[str, KnowledgeBaseService] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Create FalkorDB connection and ensure default business exists."""
        loop = asyncio.get_running_loop()
        self._db = await loop.run_in_executor(None, self._create_connection)
        self._business_mgr = BusinessManager(self._db)

        await loop.run_in_executor(None, self._business_mgr.ensure_default)
        await self._maybe_migrate_legacy_graph()

        default_svc = await self._create_service("default")
        self._services["default"] = default_svc
        log.info("service_registry_started")

    async def stop(self) -> None:
        """Close all per-business stores and the shared connection."""
        for biz_id, svc in self._services.items():
            try:
                await svc.stop()
            except Exception as exc:
                log.warning("service_stop_error", business_id=biz_id, error=str(exc))
        self._services.clear()

        if self._db is not None:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._db.connection.close)
            except Exception as exc:
                log.warning("registry_connection_close_error", error=str(exc))
            self._db = None
        log.info("service_registry_stopped")

    async def get_service(self, business_id: str = "default") -> KnowledgeBaseService:
        """Return the KBService for a business, creating lazily if needed."""
        if business_id in self._services:
            return self._services[business_id]

        async with self._lock:
            if business_id in self._services:
                return self._services[business_id]

            if self._business_mgr is None:
                raise RuntimeError("ServiceRegistry not started")

            loop = asyncio.get_running_loop()
            meta = await loop.run_in_executor(None, self._business_mgr.get_business, business_id)
            if meta is None:
                raise ValueError(f"Business '{business_id}' does not exist")

            svc = await self._create_service(business_id)
            self._services[business_id] = svc
            log.info("service_created_for_business", business_id=business_id)
            return svc

    async def remove_service(self, business_id: str) -> None:
        """Remove a business: delete its graph data and cached service."""
        if business_id == "default":
            raise ValueError("Cannot remove the default business")

        svc = self._services.pop(business_id, None)
        if svc:
            await svc.stop()

        if self._db is not None:
            gname = graph_name_for(business_id)
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._db.connection.execute_command("GRAPH.DELETE", gname),  # type: ignore[union-attr]
                )
                log.info("graph_deleted", graph=gname)
            except Exception as exc:
                log.warning("graph_delete_error", graph=gname, error=str(exc))

        if self._business_mgr:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, self._business_mgr.delete_business, business_id)

    @property
    def business_manager(self) -> BusinessManager:
        if self._business_mgr is None:
            raise RuntimeError("ServiceRegistry not started")
        return self._business_mgr

    def _create_connection(self) -> FalkorDB:
        cfg = self._settings.falkordb
        if self._settings.falkordb_password and not cfg.password:
            cfg = cfg.model_copy(update={"password": self._settings.falkordb_password})
        kwargs: dict[str, Any] = {"host": cfg.host, "port": cfg.port}
        if cfg.password:
            kwargs["password"] = cfg.password
        return FalkorDB(**kwargs)

    async def _create_service(self, business_id: str) -> KnowledgeBaseService:
        """Build a per-business KBService sharing the registry's FalkorDB connection."""
        if self._db is None:
            raise RuntimeError("ServiceRegistry not started")

        gname = graph_name_for(business_id)
        store = await FalkorDBStore.from_connection(
            self._db,
            gname,
            embedding_dim=self._settings.embedding.dimension,
        )
        svc = KnowledgeBaseService.from_components(
            store=store,
            settings=self._settings,
        )
        return svc

    async def _maybe_migrate_legacy_graph(self) -> None:
        """Migrate legacy 'code_knowledge' graph to 'kb_default' on first run."""
        if self._db is None:
            return

        loop = asyncio.get_running_loop()
        migration_key = "kb:migration_v2_done"

        done = await loop.run_in_executor(None, lambda: self._db.connection.get(migration_key))  # type: ignore[union-attr]
        if done:
            return

        try:
            graphs = await loop.run_in_executor(
                None,
                lambda: self._db.connection.execute_command("GRAPH.LIST"),  # type: ignore[union-attr]
            )
            graph_names = [g.decode() if isinstance(g, bytes) else str(g) for g in (graphs or [])]
        except Exception:
            graph_names = []

        legacy_name = self._settings.falkordb.graph_name  # "code_knowledge"
        target_name = graph_name_for("default")  # "kb_default"

        if legacy_name in graph_names and target_name not in graph_names:
            log.info("migrating_legacy_graph", source=legacy_name, target=target_name)
            try:
                await loop.run_in_executor(
                    None,
                    lambda: self._db.connection.rename(legacy_name, target_name),  # type: ignore[union-attr]
                )
                log.info("legacy_graph_migrated", source=legacy_name, target=target_name)
            except Exception as exc:
                log.warning("legacy_graph_migration_failed", error=str(exc))

        await loop.run_in_executor(
            None,
            lambda: self._db.connection.set(migration_key, "1"),  # type: ignore[union-attr]
        )
