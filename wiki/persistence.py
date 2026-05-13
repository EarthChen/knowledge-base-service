"""Wiki page persistence: graph writes, code-hash sync, embedding, confidence, claim tracking."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import time as _time
from datetime import UTC, datetime
from typing import Any

from core.log import get_logger
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from store.schema import NodeLabel
from wiki.confidence_inputs import gather_confidence_inputs, set_wiki_page_confidence_scores
from wiki.confidence_scorer import confidence_scorer_from_wiki_app_config
from wiki.models import WikiPage

log = get_logger(__name__)


class WikiPagePersistence:
    """Owns all graph-write operations for wiki pages."""

    def __init__(
        self,
        store: Any | None,
        graph: Any,
        wiki_store: Any | None,
        wiki_cfg: Any,
        embedding_cfg: Any,
        llm: Any | None = None,
    ) -> None:
        self._store = store
        self._graph = graph
        self._wiki_store = wiki_store
        self._wiki_cfg = wiki_cfg
        self._embedding_cfg = embedding_cfg
        self._llm = llm

    def confidence_scoring_enabled(self) -> bool:
        return bool(getattr(self._wiki_cfg, "confidence_scoring_enabled", False))

    async def bulk_set_wiki_code_hashes(self, repository: str) -> None:
        """After full generation, mark all source code entities as wiki-synced."""
        query_port = self._graph
        if query_port is None or not hasattr(query_port, "execute_query"):
            return
        await query_port.execute_query(
            "MATCH (n {repository: $repo}) "
            "WHERE n.code_hash IS NOT NULL "
            "SET n.wiki_code_hash = n.code_hash",
            {"repo": repository},
        )
        log.info("bulk_wiki_code_hashes_set", repository=repository)

    async def inject_wikilinks(self, repository: str, pages: list[WikiPage]) -> None:
        """Append ``## Related Pages`` using outgoing ``WIKI_REFERENCES`` from the graph."""
        if self._wiki_store is None or not pages:
            return
        from wiki.reference_generator import WikiReferenceGenerator

        ref_gen = WikiReferenceGenerator(self._wiki_store)
        for page in pages:
            uid = f"WikiPage:{repository}:{page.path}"
            try:
                out = await self._wiki_store.get_wiki_page_references(uid)
            except Exception:
                log.debug("wiki_page_references_lookup_failed", page_uid=uid, exc_info=True)
                continue
            rows = getattr(out, "data", None) or []
            paths: list[str] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                p = str(row.get("path", "") or "").strip()
                if p:
                    paths.append(p)
            page.content = ref_gen.inject_wikilinks(page.content or "", paths)

    async def sync_graph_references_into_page_content(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str,
        skip_claim_tracking: bool,
    ) -> None:
        """Build ``WIKI_REFERENCES`` from the code graph, inject related links into page bodies, re-persist."""
        if self._wiki_store is None or not pages:
            return
        try:
            from wiki.reference_generator import WikiReferenceGenerator

            ref_gen = WikiReferenceGenerator(self._wiki_store)
            n = await ref_gen.generate(repository)
            log.info("wiki_reference_edges_generated", repository=repository, count=n)
            await self.inject_wikilinks(repository, pages)
            await self.persist_pages_to_graph(
                repository,
                pages,
                language=language,
                skip_claim_tracking=skip_claim_tracking,
            )
        except Exception:
            log.warning("wiki_sync_references_inject_failed", repository=repository, exc_info=True)

    async def update_wiki_code_hashes(self, repository: str, uids: list[str]) -> None:
        """After successful wiki page generation, set wiki_code_hash = code_hash on source nodes."""
        if not uids:
            return
        query_port = self._graph
        if query_port is None or not hasattr(query_port, "execute_query"):
            return
        await query_port.execute_query(
            "MATCH (n {repository: $repo}) "
            "WHERE n.uid IN $uids AND n.code_hash IS NOT NULL "
            "SET n.wiki_code_hash = n.code_hash",
            {"repo": repository, "uids": uids},
        )
        log.info("wiki_code_hashes_updated", repository=repository, count=len(uids))

    async def persist_pages_to_graph(
        self,
        repository: str,
        pages: list[WikiPage],
        *,
        language: str = "en",
        skip_claim_tracking: bool = False,
    ) -> None:
        if self._store is None or not hasattr(self._store, "persist_wiki_pages"):
            return
        _t0 = _time.monotonic()
        log.info("persist_pages_start", repository=repository, page_count=len(pages))

        old_contents: dict[str, str] = {}
        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
        ):
            for i, p in enumerate(pages):
                wuid = f"WikiPage:{repository}:{p.path}"
                try:
                    r = await asyncio.wait_for(
                        self._store.execute_query(
                            "MATCH (w:WikiPage {uid: $uid}) RETURN coalesce(w.content, '') AS c LIMIT 1",
                            {"uid": wuid},
                        ),
                        timeout=10,
                    )
                except TimeoutError:
                    log.warning("supersession_query_timeout", path=p.path, page_num=i)
                    continue
                rows = getattr(r, "data", None) or []
                if rows:
                    r0 = rows[0]
                    if isinstance(r0, dict):
                        old_contents[p.path] = str(r0.get("c", "") or "")
                    else:
                        old_contents[p.path] = ""
                else:
                    old_contents[p.path] = ""
            log.info("supersession_tracking_done", repository=repository, elapsed_s=round(_time.monotonic() - _t0, 1))

        ts = datetime.now(UTC).isoformat()
        page_dicts = [
            {
                "path": p.path,
                "title": p.title,
                "content": p.content,
                "page_type": p.page_type.value,
                "generated_at": ts,
                "importance_tier": getattr(p.metadata, "importance_tier", None),
                "enrichment_level": getattr(p.metadata, "enrichment_level", None),
                "entity_uid": getattr(p, "_source_entity_uid", None),
                "business_domain": (
                    str(getattr(p, "business_domain", "") or "").strip()
                ),
                "canonical_key": str(getattr(p, "canonical_key", "") or ""),
                "navigation_json": (
                    json.dumps(p.navigation.to_api_dict(), ensure_ascii=False)
                    if p.navigation
                    else ""
                ),
            }
            for p in pages
        ]

        _PERSIST_CHUNK = 200
        _t_persist = _time.monotonic()
        total_persisted = 0
        persisted_dicts: list[dict[str, Any]] = []
        for chunk_start in range(0, len(page_dicts), _PERSIST_CHUNK):
            chunk = page_dicts[chunk_start : chunk_start + _PERSIST_CHUNK]
            try:
                await asyncio.wait_for(
                    self._store.persist_wiki_pages(repository, chunk),
                    timeout=120,
                )
                total_persisted += len(chunk)
                persisted_dicts.extend(chunk)
                if chunk_start > 0:
                    log.info(
                        "persist_pages_chunk",
                        repository=repository,
                        persisted=total_persisted,
                        total=len(page_dicts),
                    )
            except TimeoutError:
                log.warning(
                    "persist_pages_chunk_timeout",
                    repository=repository,
                    chunk_start=chunk_start,
                    chunk_size=len(chunk),
                )
            except Exception as exc:
                log.warning("wiki_page_persist_failed", repository=repository, chunk_start=chunk_start, error=str(exc)[:200])

        log.info(
            "persist_pages_write_done",
            repository=repository,
            persisted=total_persisted,
            elapsed_s=round(_time.monotonic() - _t_persist, 1),
        )

        pairs: list[dict[str, str]] = [
            {
                "wiki_uid": f"WikiPage:{repository}:{pd['path']}",
                "entity_uid": pd["entity_uid"],
            }
            for pd in persisted_dicts
            if pd.get("entity_uid")
        ]
        seen_pairs: set[tuple[str, str]] = {(p["wiki_uid"], p["entity_uid"]) for p in pairs}
        for page in pages:
            covered = getattr(page, "covered_entity_uids", None) or []
            if covered:
                wiki_uid = f"WikiPage:{repository}:{page.path}"
                for eu in covered:
                    key = (wiki_uid, eu)
                    if eu and key not in seen_pairs:
                        pairs.append({"wiki_uid": wiki_uid, "entity_uid": eu})
                        seen_pairs.add(key)
        if pairs:
            log.info(
                "source_entity_pairs",
                repository=repository,
                total_pairs=len(pairs),
                sample=pairs[:3],
            )
            _EDGE_CHUNK = 200
            for edge_start in range(0, len(pairs), _EDGE_CHUNK):
                edge_chunk = pairs[edge_start : edge_start + _EDGE_CHUNK]
                batch_q = (
                    "UNWIND $pairs AS pair "
                    "MATCH (wp:WikiPage {uid: pair.wiki_uid}) "
                    "MATCH (e {uid: pair.entity_uid}) "
                    "MERGE (wp)-[:SOURCE_ENTITY]->(e)"
                )
                try:
                    await asyncio.wait_for(
                        self._store.execute_query(batch_q, {"pairs": edge_chunk}),
                        timeout=120,
                    )
                except TimeoutError:
                    log.warning("source_entity_chunk_timeout", repository=repository, edge_start=edge_start)
                except Exception as exc:
                    log.warning("source_entity_batch_failed", repository=repository, error=str(exc)[:200])

        log.info("persist_pages_complete", repository=repository, total_time_s=round(_time.monotonic() - _t0, 1))

        if self.confidence_scoring_enabled() and self._store is not None and persisted_dicts:
            _cs_t0 = _time.monotonic()
            log.info("confidence_scoring_start", repository=repository, page_count=len(persisted_dicts))
            try:
                scorer = confidence_scorer_from_wiki_app_config(self._wiki_cfg)
                scores: list[tuple[str, float]] = []
                for i, pd in enumerate(persisted_dicts):
                    uid = f"WikiPage:{repository}:{pd['path']}"
                    gen_at = str(pd.get("generated_at", "") or ts)
                    try:
                        inputs = await asyncio.wait_for(
                            gather_confidence_inputs(
                                self._store, uid, repository, gen_at,
                            ),
                            timeout=10,
                        )
                        scores.append((pd["path"], scorer.compute(inputs)))
                    except TimeoutError:
                        log.warning("confidence_input_timeout", path=pd["path"], page_num=i)
                        continue
                    if (i + 1) % 200 == 0:
                        log.info("confidence_scoring_progress", repository=repository, scored=i + 1, total=len(persisted_dicts))
                await set_wiki_page_confidence_scores(
                    self._store, scores, repository=repository,
                )
                log.info("confidence_scoring_done", repository=repository, scored=len(scores), elapsed_s=round(_time.monotonic() - _cs_t0, 1))
            except Exception as exc:
                log.warning("wiki_confidence_persist_failed", repository=repository, error=str(exc))

        if total_persisted > 0:
            _emb_t0 = _time.monotonic()
            log.info("wiki_page_embedding_start", repository=repository, page_count=len(persisted_dicts))
            try:
                emb_gen = EmbeddingGenerator.shared(config=self._embedding_cfg)
                items = [
                    doc_dict_for_embedding(
                        {"title": d["title"], "content": d["content"][:3000]},
                    )
                    for d in persisted_dicts
                ]
                embeddings = await emb_gen.generate_for_docs(items)
                log.info("wiki_page_embedding_vectors_done", repository=repository, count=len(embeddings), elapsed_s=round(_time.monotonic() - _emb_t0, 1))
                emb_items: list[tuple[str, NodeLabel, list[float]]] = [
                    (
                        f"WikiPage:{repository}:{page_dict['path']}",
                        NodeLabel.WIKI_PAGE,
                        embedding,
                    )
                    for page_dict, embedding in zip(persisted_dicts, embeddings, strict=True)
                ]
                _batch = getattr(self._store, "batch_set_node_embeddings", None)
                _f = getattr(_batch, "__func__", _batch) if _batch is not None else None
                if _f is not None and inspect.iscoroutinefunction(_f):
                    await self._store.batch_set_node_embeddings(emb_items)
                else:
                    for page_dict, embedding in zip(persisted_dicts, embeddings, strict=True):
                        uid = f"WikiPage:{repository}:{page_dict['path']}"
                        await self._store.set_node_embedding(uid, NodeLabel.WIKI_PAGE, embedding)
                log.info("wiki_page_embedding_done", repository=repository, elapsed_s=round(_time.monotonic() - _emb_t0, 1))
            except Exception as exc:
                log.warning("wiki_page_embedding_failed", repository=repository, error=str(exc))
        else:
            log.info("wiki_page_embedding_skipped", repository=repository, reason="no_pages_persisted")

        if (
            self._wiki_cfg.supersession_tracking_enabled
            and self._llm is not None
            and self._wiki_store is not None
            and not skip_claim_tracking
        ):
            log.info("claim_tracking_start", repository=repository, page_count=len(pages))
            from wiki.claim_extractor import extract_claims
            from wiki.claim_tracker import ClaimTracker

            now_ts = int(_time.time())
            conc_raw = getattr(self._wiki_cfg, "claim_tracking_concurrency", 5)
            conc = max(1, int(conc_raw))
            sem = asyncio.Semaphore(conc)

            async def _track_claims_one_page(page: WikiPage) -> None:
                async with sem:
                    try:
                        old_c = old_contents.get(page.path, "")
                        wiki_uid = f"WikiPage:{repository}:{page.path}"
                        old_claims = (
                            await extract_claims(self._llm, old_c, language) if old_c.strip() else []
                        )
                        new_claims = await extract_claims(self._llm, page.content, language)
                        pairs = ClaimTracker.find_supersedions(old_claims, new_claims)
                        next_v = await self._wiki_store.next_claim_version(wiki_uid)
                        by_text: dict[str, str] = {}
                        for cl in new_claims:
                            proposed = f"WikiClaimHistory:{wiki_uid}:{next_v}"
                            cuid = await self._wiki_store.find_or_create_wiki_claim(
                                wiki_uid,
                                cl.claim_text,
                                next_v,
                                new_claim_uid=proposed,
                                created_at=now_ts,
                            )
                            if cuid == proposed:
                                next_v += 1
                            by_text[cl.claim_text.strip()] = cuid
                        for pr in pairs:
                            old_u = await self._wiki_store.find_wiki_claim_by_text(
                                wiki_uid, pr.old_claim_text,
                            )
                            nu = by_text.get(pr.new_claim_text.strip())
                            if old_u and nu:
                                await self._wiki_store.set_wiki_claim_superseded(
                                    old_u, nu, now_ts,
                                )
                        sup_list = [pair.new_claim_text for pair in pairs]
                        if sup_list:
                            await self._wiki_store.set_wiki_page_supersedes(
                                wiki_uid,
                                json.dumps(sup_list, ensure_ascii=False),
                            )
                    except Exception as exc:
                        log.warning(
                            "wiki_claim_tracking_failed",
                            repository=repository,
                            path=page.path,
                            error=str(exc),
                        )

            _ct_t0 = _time.monotonic()
            await asyncio.gather(*[_track_claims_one_page(p) for p in pages])
            log.info(
                "claim_tracking_done",
                repository=repository,
                elapsed_s=round(_time.monotonic() - _ct_t0, 1),
                pages=len(pages),
            )

    async def cleanup_stale_wiki_pages(
        self,
        repository: str,
        current_page_paths: list[str],
    ) -> int:
        """Remove WikiPage nodes that are not in the current generation set.

        Called after wiki regeneration to delete pages from previous runs
        whose topic names have changed. Safe for both full and incremental
        modes because it only targets ``topic`` and ``domain_overview`` pages
        which are always fully regenerated by the pipeline.
        """
        if self._store is None or not hasattr(self._store, "execute_query"):
            return 0
        current_uids = [f"WikiPage:{repository}:{p}" for p in current_page_paths]
        result = await self._store.execute_query(
            "MATCH (w:WikiPage) "
            "WHERE w.repository = $repo "
            "AND w.page_type IN ['topic', 'domain_overview'] "
            "AND NOT w.uid IN $keep_uids "
            "DETACH DELETE w "
            "RETURN count(w) AS deleted",
            {"repo": repository, "keep_uids": current_uids},
        )
        deleted = 0
        if result.data and isinstance(result.data[0], dict):
            deleted = int(result.data[0].get("deleted", 0))
        if deleted > 0:
            log.info(
                "stale_wiki_pages_cleaned",
                repository=repository,
                deleted=deleted,
                kept=len(current_uids),
            )
        return deleted

    async def cleanup_stale_wiki_pages_by_domain(
        self,
        repository: str,
        current_page_paths: list[str],
        affected_domains: list[str],
    ) -> int:
        """Remove stale WikiPage nodes only for the specified affected domains.

        Unlike ``cleanup_stale_wiki_pages`` which targets all topic/domain_overview
        pages for a repository, this variant limits deletion to pages whose title
        matches one of the ``affected_domains``.
        """
        if not affected_domains:
            return 0

        if self._store is None or not hasattr(self._store, "execute_query"):
            return 0

        current_uids = set()
        for path in current_page_paths:
            uid = f"WikiPage:{repository}:{path}"
            current_uids.add(uid)

        deleted = 0
        result = await self._store.execute_query(
            "MATCH (wp:WikiPage) "
            "WHERE wp.repository = $repo "
            "AND wp.page_type IN ['topic', 'domain_overview'] "
            "AND wp.title IN $domains "
            "AND NOT wp.uid IN $keep_uids "
            "DETACH DELETE wp "
            "RETURN count(wp) AS deleted",
            {
                "repo": repository,
                "domains": list(set(affected_domains)),
                "keep_uids": list(current_uids),
            },
        )
        if result.data and isinstance(result.data[0], dict):
            deleted = int(result.data[0].get("deleted", 0))

        if deleted > 0:
            log.info(
                "stale_domain_pages_cleaned",
                repository=repository,
                affected_domains=sorted(set(affected_domains)),
                deleted=deleted,
                kept=len(current_uids),
            )
        return deleted

    async def cleanup_stale_domain_sections(
        self,
        business_id: str,
        current_domain_names: list[str],
    ) -> int:
        """Remove WikiSection nodes for domains that no longer exist.

        Also removes orphaned HAS_CHILD edges pointing to/from these sections.
        """
        if self._store is None or not hasattr(self._store, "execute_query"):
            return 0
        from wiki.tree_builder import WikiTreeBuilder

        keep_uids = [
            WikiTreeBuilder().generate_domain_section_uid(business_id, d)
            for d in current_domain_names
        ]
        result = await self._store.execute_query(
            "MATCH (s:WikiSection) "
            "WHERE s.section_type = 'business_domain' "
            "AND NOT s.uid IN $keep_uids "
            "DETACH DELETE s "
            "RETURN count(s) AS deleted",
            {"keep_uids": keep_uids},
        )
        deleted = 0
        if result.data and isinstance(result.data[0], dict):
            deleted = int(result.data[0].get("deleted", 0))
        if deleted > 0:
            log.info(
                "stale_domain_sections_cleaned",
                business_id=business_id,
                deleted=deleted,
            )
        return deleted

    async def cleanup_stale_domain_edges(
        self,
        business_id: str,
        current_domain_names: list[str],
    ) -> int:
        """Remove HAS_CHILD edges from obsolete domain sections to WikiPages.

        When domain classification changes, pages may have old edges linking
        them to previous domains. This deletes those stale edges while
        preserving edges from current domains.
        """
        if self._store is None or not hasattr(self._store, "execute_query"):
            return 0
        from wiki.tree_builder import WikiTreeBuilder

        keep_uids = [
            WikiTreeBuilder().generate_domain_section_uid(business_id, d)
            for d in current_domain_names
        ]
        result = await self._store.execute_query(
            "MATCH (s:WikiSection)-[r:HAS_CHILD {view_type: 'business_domain'}]->(wp:WikiPage) "
            "WHERE s.section_type = 'business_domain' "
            "AND NOT s.uid IN $keep_uids "
            "DELETE r "
            "RETURN count(r) AS deleted",
            {"keep_uids": keep_uids},
        )
        deleted = 0
        if result.data and isinstance(result.data[0], dict):
            deleted = int(result.data[0].get("deleted", 0))
        if deleted > 0:
            log.info(
                "stale_domain_edges_cleaned",
                business_id=business_id,
                deleted=deleted,
            )
        return deleted


class WikiPersistence:
    """Graph persistence for domain anchors, module pins, and classification links."""

    def __init__(self, store: Any, *, checkpoint_dir: str | None = None) -> None:
        self._store = store
        self._checkpoint_dir = checkpoint_dir or os.environ.get(
            "WIKI_CHECKPOINT_DIR",
            os.path.join(os.path.dirname(__file__), "..", "data", "checkpoints"),
        )

    @staticmethod
    def _sanitize_business_id(business_id: str) -> str:
        """Sanitize business_id to prevent path traversal attacks."""
        return re.sub(r"[^a-zA-Z0-9_\-]", "_", business_id)

    def _get_checkpoint_db_path(self, business_id: str) -> str:
        """SQLite DB path for LangGraph checkpoints for this business."""
        os.makedirs(self._checkpoint_dir, exist_ok=True)
        safe_id = self._sanitize_business_id(business_id)
        return os.path.join(self._checkpoint_dir, f"{safe_id}_wiki.db")

    async def get_checkpoint_info(self, business_id: str) -> dict[str, Any] | None:
        """Return checkpoint file metadata or None when no SQLite DB exists yet."""
        db_path = self._get_checkpoint_db_path(business_id)
        if not os.path.exists(db_path):
            return None
        stat = os.stat(db_path)
        return {
            "business_id": business_id,
            "db_path": db_path,
            "last_modified": stat.st_mtime,
            "size_bytes": stat.st_size,
        }

    async def delete_checkpoint(self, business_id: str) -> None:
        """Remove checkpoint SQLite file (and WAL/SHM sidecars) for a business."""
        db_path = self._get_checkpoint_db_path(business_id)
        for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
            if os.path.exists(path):
                os.remove(path)

    async def list_domain_anchors(self, business_id: str) -> list[dict]:
        """Return all domain anchors: [{slug, display_name, module_count}]."""
        cypher = (
            "MATCH (d:DomainAnchor {business_id: $bid}) "
            "OPTIONAL MATCH (d)<-[:BELONGS_TO_DOMAIN]-(m:Module) "
            "RETURN d.slug AS slug, d.display_name AS display_name, "
            "count(m) AS module_count ORDER BY slug"
        )
        result = await self._store.execute_query(cypher, {"bid": business_id})
        return result.data if result.data else []

    async def upsert_domain_anchor(
        self, business_id: str, slug: str, display_name: str
    ) -> None:
        """Create or update a DomainAnchor node."""
        cypher = (
            "MERGE (d:DomainAnchor {business_id: $bid, slug: $slug}) "
            "SET d.display_name = $display_name"
        )
        await self._store.execute_query(
            cypher, {"bid": business_id, "slug": slug, "display_name": display_name}
        )

    async def delete_domain_anchor(self, business_id: str, slug: str) -> None:
        """Remove a DomainAnchor and its relationships."""
        cypher = (
            "MATCH (d:DomainAnchor {business_id: $bid, slug: $slug}) "
            "DETACH DELETE d"
        )
        await self._store.execute_query(cypher, {"bid": business_id, "slug": slug})

    async def pin_module_to_domain(
        self, business_id: str, module_name: str, domain_slug: str
    ) -> None:
        """Pin a module to a specific domain (user override).

        Scoped via DomainAnchor.business_id to prevent cross-tenant mutations.
        """
        cypher = (
            "MATCH (d:DomainAnchor {business_id: $bid, slug: $slug}) "
            "MATCH (m:Module {name: $name}) "
            "MERGE (m)-[:BELONGS_TO_DOMAIN]->(d) "
            "SET m.domain_slug = $slug, m.domain_pinned = true"
        )
        await self._store.execute_query(
            cypher, {"bid": business_id, "name": module_name, "slug": domain_slug}
        )

    async def unpin_module(self, business_id: str, module_name: str) -> None:
        """Remove pinned status from a module.

        Scoped via DomainAnchor.business_id to prevent cross-tenant mutations.
        """
        cypher = (
            "MATCH (m:Module {name: $name, domain_pinned: true})"
            "-[:BELONGS_TO_DOMAIN]->(d:DomainAnchor {business_id: $bid}) "
            "SET m.domain_pinned = false "
            "REMOVE m.domain_slug"
        )
        await self._store.execute_query(
            cypher, {"bid": business_id, "name": module_name}
        )

    async def list_pinned_modules(self, business_id: str) -> list[dict]:
        """Return all pinned modules scoped to a business.

        Joins through DomainAnchor to enforce business_id boundary.
        """
        cypher = (
            "MATCH (m:Module {domain_pinned: true})"
            "-[:BELONGS_TO_DOMAIN]->(d:DomainAnchor {business_id: $bid}) "
            "RETURN m.name AS module_name, m.domain_slug AS domain_slug "
            "ORDER BY domain_slug, module_name"
        )
        result = await self._store.execute_query(cypher, {"bid": business_id})
        return result.data if result.data else []

    async def list_domain_modules(self, business_id: str, slug: str) -> list[dict]:
        """Return modules belonging to a specific domain."""
        cypher = (
            "MATCH (m:Module)-[:BELONGS_TO_DOMAIN]->(d:DomainAnchor {business_id: $bid, slug: $slug}) "
            "RETURN m.name AS name, m.repository AS repository, "
            "coalesce(m.path, '') AS path, "
            "coalesce(m.domain_pinned, false) AS pinned "
            "ORDER BY m.name"
        )
        result = await self._store.execute_query(cypher, {"bid": business_id, "slug": slug})
        return result.data if result.data else []

    async def rename_domain(
        self, business_id: str, old_slug: str, new_slug: str, new_display_name: str
    ) -> None:
        """Rename a domain: update DomainAnchor slug/display and cascade to Module.domain_slug."""
        await self._store.execute_query(
            "MATCH (d:DomainAnchor {business_id: $bid, slug: $old}) "
            "SET d.slug = $new, d.display_name = $display",
            {"bid": business_id, "old": old_slug, "new": new_slug, "display": new_display_name},
        )
        await self._store.execute_query(
            "MATCH (m:Module {domain_slug: $old})-[:BELONGS_TO_DOMAIN]->"
            "(d:DomainAnchor {business_id: $bid, slug: $new}) "
            "SET m.domain_slug = $new",
            {"bid": business_id, "old": old_slug, "new": new_slug},
        )

    async def save_domain_classification(
        self, business_id: str, mapping: dict
    ) -> None:
        """Persist classification: clear stale edges, upsert anchors, link modules.

        Removes old BELONGS_TO_DOMAIN edges for affected modules before
        creating new ones, preventing stale assignments from lingering.
        """
        all_module_keys: list[tuple[str, str]] = []
        for info in mapping.values():
            all_module_keys.extend(info.get("modules", []))

        if all_module_keys:
            clear_cypher = (
                "UNWIND $keys AS k "
                "MATCH (m:Module {name: k[1], repository: k[0]})"
                "-[r:BELONGS_TO_DOMAIN]->(d:DomainAnchor {business_id: $bid}) "
                "DELETE r"
            )
            await self._store.execute_query(
                clear_cypher,
                {"keys": [list(k) for k in all_module_keys], "bid": business_id},
            )

        for slug, info in mapping.items():
            display_name = info.get("display_name", slug)
            await self.upsert_domain_anchor(business_id, slug, display_name)
            modules = info.get("modules", [])
            for repo, mod_name in modules:
                cypher = (
                    "MATCH (m:Module {name: $name, repository: $repo}) "
                    "MATCH (d:DomainAnchor {business_id: $bid, slug: $slug}) "
                    "MERGE (m)-[:BELONGS_TO_DOMAIN]->(d) "
                    "SET m.domain_slug = $slug"
                )
                await self._store.execute_query(
                    cypher,
                    {"name": mod_name, "repo": repo, "bid": business_id, "slug": slug},
                )
