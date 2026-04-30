"""Wiki page persistence: graph writes, code-hash sync, embedding, confidence, claim tracking."""

from __future__ import annotations

import asyncio
import inspect
import json
import time as _time
from datetime import datetime, timezone
from typing import Any

from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from log import get_logger
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
        """After full generation, mark all entities as wiki-synced."""
        query_port = self._store if self._store is not None else self._graph
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
        """After successful wiki page generation, set wiki_code_hash = code_hash."""
        if not uids:
            return
        query_port = self._store if self._store is not None else self._graph
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

        ts = datetime.now(timezone.utc).isoformat()
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
        for chunk_start in range(0, len(page_dicts), _PERSIST_CHUNK):
            chunk = page_dicts[chunk_start : chunk_start + _PERSIST_CHUNK]
            try:
                await asyncio.wait_for(
                    self._store.persist_wiki_pages(repository, chunk),
                    timeout=120,
                )
                total_persisted += len(chunk)
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
            for pd in page_dicts
            if pd.get("entity_uid")
        ]
        if pairs:
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

        if self.confidence_scoring_enabled() and self._store is not None:
            _cs_t0 = _time.monotonic()
            log.info("confidence_scoring_start", repository=repository, page_count=len(page_dicts))
            try:
                scorer = confidence_scorer_from_wiki_app_config(self._wiki_cfg)
                scores: list[tuple[str, float]] = []
                for i, pd in enumerate(page_dicts):
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
                        log.info("confidence_scoring_progress", repository=repository, scored=i + 1, total=len(page_dicts))
                await set_wiki_page_confidence_scores(
                    self._store, scores, repository=repository,
                )
                log.info("confidence_scoring_done", repository=repository, scored=len(scores), elapsed_s=round(_time.monotonic() - _cs_t0, 1))
            except Exception as exc:
                log.warning("wiki_confidence_persist_failed", repository=repository, error=str(exc))

        if total_persisted > 0:
            _emb_t0 = _time.monotonic()
            log.info("wiki_page_embedding_start", repository=repository, page_count=len(page_dicts))
            try:
                emb_gen = EmbeddingGenerator.shared(config=self._embedding_cfg)
                items = [
                    doc_dict_for_embedding(
                        {"title": d["title"], "content": d["content"][:3000]},
                    )
                    for d in page_dicts
                ]
                embeddings = await emb_gen.generate_for_docs(items)
                log.info("wiki_page_embedding_vectors_done", repository=repository, count=len(embeddings), elapsed_s=round(_time.monotonic() - _emb_t0, 1))
                emb_items: list[tuple[str, NodeLabel, list[float]]] = [
                    (
                        f"WikiPage:{repository}:{page_dict['path']}",
                        NodeLabel.WIKI_PAGE,
                        embedding,
                    )
                    for page_dict, embedding in zip(page_dicts, embeddings, strict=True)
                ]
                _batch = getattr(self._store, "batch_set_node_embeddings", None)
                _f = getattr(_batch, "__func__", _batch) if _batch is not None else None
                if _f is not None and inspect.iscoroutinefunction(_f):
                    await self._store.batch_set_node_embeddings(emb_items)
                else:
                    for page_dict, embedding in zip(page_dicts, embeddings, strict=True):
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
