"""Incremental indexer — indexes only changed files based on git diff.

Supports both full reindexing and incremental updates triggered by
git push events or manual requests.  Handles both code files and
document files (.md, .rst, .txt) in incremental mode.
"""

from __future__ import annotations

import asyncio
import subprocess
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from core.config import get_settings
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.config_indexer import _config_file_extension
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator, doc_dict_for_embedding
from indexer.enrichment import (
    EnrichmentPriorityClassifier,
    is_trivial_enrichment_entity,
    truncate_enrichment_item,
)
from indexer.graph_enricher import GraphEnricher
from indexer.import_resolver import ImportResolver
from indexer.chunk_hash import apply_content_hash_to_nodes
from indexer.index_report import IndexReport
from core.log import get_logger
from store.falkordb_store import FalkorDBStore
from store.indexer_store import IndexerStore
from store.settings_store import SettingsStore
from store.schema import GraphNode, NodeLabel
from wiki.incremental import WikiIncrementalUpdater
from wiki.models import WikiConfig

if TYPE_CHECKING:
    from indexer.enrichment import CodeSummaryEnricher
    from llm.gateway_client import RepoTaskManager

log = get_logger(__name__)

_DOC_EXTENSIONS = frozenset(DocumentIndexer.SUPPORTED_EXTENSIONS)
_ENRICH_BATCH_SIZE = 50


def _git_changed_pairs_to_diff_triples(
    git_pairs: list[tuple[str, str]],
) -> list[tuple[str, str | None, str | None]]:
    """Map ``(path, status)`` from git name-status to wiki incremental ``(status, old, new)`` tuples."""
    out: list[tuple[str, str | None, str | None]] = []
    for fpath, raw_status in git_pairs:
        st = raw_status.upper()
        if st == "D":
            out.append(("D", fpath, None))
        elif st == "A":
            out.append(("A", None, fpath))
        else:
            out.append(("M", fpath, fpath))
    return out


def _try_git_head_sha(repo_root: str) -> str | None:
    """Return ``git rev-parse HEAD`` when *repo_root* is a git checkout, else ``None``."""
    try:
        proc = subprocess.run(
            ["git", "-C", repo_root, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if proc.returncode != 0:
            return None
        sha = (proc.stdout or "").strip()
        return sha or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def _try_git_head_sha_for_file(file_path: str) -> str | None:
    """Walk parents from *file_path* to find ``.git`` and resolve HEAD."""
    p = Path(file_path).resolve()
    cur = p if p.is_dir() else p.parent
    for _ in range(64):
        if (cur / ".git").exists():
            return _try_git_head_sha(str(cur))
        if cur.parent == cur:
            break
        cur = cur.parent
    return None


def _stamp_repository_metadata(
    nodes: list[GraphNode],
    repository: str | None,
    *,
    commit_sha: str | None = None,
) -> None:
    """Set ``repository`` and optional ``commit_sha`` on node properties before upsert."""
    if repository:
        for n in nodes:
            n.properties["repository"] = repository
    if commit_sha:
        for n in nodes:
            n.properties["commit_sha"] = commit_sha


def _get_exclude_dirs() -> set[str]:
    return set(get_settings().exclude_dirs)


def _path_keys_for_store(fpath: str, directory: str) -> list[str]:
    """Graph ``file`` / ``path`` keys to query (repo-relative and absolute on-disk) for the same file."""
    full = str(Path(directory) / fpath)
    keys: set[str] = {fpath}
    if full and full != fpath:
        keys.add(full)
    return list(keys)


class IncrementalIndexer:
    """Orchestrates code + document indexing — full or incremental."""

    def __init__(
        self,
        store: FalkorDBStore,
        graph_builder: CodeGraphBuilder,
        embedding_gen: EmbeddingGenerator,
        doc_indexer: DocumentIndexer | None = None,
        enricher: CodeSummaryEnricher | None = None,
        repo_task_manager: RepoTaskManager | None = None,
        wiki_incremental_updater: WikiIncrementalUpdater | None = None,
        wiki_auto_updater: Callable[[str], Awaitable[Any]] | None = None,
        settings_store: SettingsStore | None = None,
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen
        self._doc_indexer = doc_indexer or DocumentIndexer()
        self._enricher = enricher
        self._repo_task_mgr = repo_task_manager
        self._wiki_incremental_updater = wiki_incremental_updater
        self._wiki_auto_updater = wiki_auto_updater
        self._settings_store = settings_store
        self._last_report: IndexReport | None = None

    def get_last_report(self) -> IndexReport | None:
        """Return the most recent index quality report from full or incremental indexing."""
        return self._last_report

    @property
    def enrichment_available(self) -> bool:
        """Whether LLM 摘要（直连或网关）可用于补全 business_summary。"""
        return self._enricher is not None or self._repo_task_mgr is not None

    async def _check_auto_update_enabled(self) -> bool:
        """Hot-read from DB, fallback to startup config."""
        try:
            if self._settings_store is not None:
                val = await self._settings_store.get("wiki.auto_update_on_index")
                if val is not None:
                    return val.strip().lower() in ("true", "1", "yes")
        except Exception:
            log.warning("auto_update_settings_read_failed", exc_info=True)
        return get_settings().wiki.auto_update_on_index

    async def _maybe_auto_update_wiki(
        self,
        changed_files: list[tuple[str, str | None, str | None]],
        repository: str | None,
        wiki_config: WikiConfig,
    ) -> None:
        """When wiki auto-update is enabled, run incremental wiki refresh."""
        if repository is None:
            return
        if self._wiki_auto_updater is None and self._wiki_incremental_updater is None:
            return
        if not await self._check_auto_update_enabled():
            return
        try:
            if self._wiki_auto_updater is not None:
                await self._wiki_auto_updater(repository)
            elif self._wiki_incremental_updater is not None:
                await self._wiki_incremental_updater.update_from_index_event(
                    repository,
                    changed_files,
                    wiki_config,
                )
        except Exception:
            log.warning("auto_wiki_update_failed", repository=repository, exc_info=True)

    def _enrichment_backend_label(self) -> str:
        """Return API progress label for LLM enrichment mode (empty if disabled)."""
        if get_settings().llm.enrichment_strategy == "disabled":
            return ""
        if not self._enricher:
            return ""
        if self._repo_task_mgr and getattr(self._enricher, "_gw", None):
            return "gateway"
        return "direct"

    async def index_full(
        self,
        directory: str,
        progress_callback: Callable[..., None] | None = None,
        *,
        repository: str | None = None,
    ) -> dict[str, Any]:
        """Full reindex — pipelined parse+enrich (1 ACP task) then embed.

        Parse and enrichment run concurrently: as files are parsed, code
        entities are streamed into the feedback loop via an asyncio queue.
        Only lightweight enrichment items flow through the queue; full node
        objects are released after upsert.
        """
        log.info("full_index_start", directory=directory)

        report = IndexReport()
        start_time = time.monotonic()

        enrich_backend = self._enrichment_backend_label()

        total_nodes = 0
        total_edges = 0
        total_embeds = 0
        processed = 0
        file_paths_for_embed: list[str] = []
        enrich_refs: dict[str, list[tuple]] = {}
        enrich_candidates = 0
        enrich_skipped_trivial = 0

        enrichment_strategy = get_settings().llm.enrichment_strategy
        run_llm_indexing_enrichment = enrichment_strategy != "disabled"
        priority_classifier = (
            EnrichmentPriorityClassifier() if enrichment_strategy == "core_only" else None
        )

        enrich_queue: asyncio.Queue[list[dict[str, str]] | None] = asyncio.Queue()
        summary_map: dict[str, str] = {}

        if progress_callback:
            progress_callback(
                phase="indexing_and_enriching",
                enrichment_backend=enrich_backend,
            )

        repo_id = f"enrich:{directory.rstrip('/').rsplit('/', 1)[-1]}"

        async def _enrichment_consumer() -> None:
            if not run_llm_indexing_enrichment:
                while await enrich_queue.get() is not None:
                    pass
                return
            if self._repo_task_mgr:
                result = await self._repo_task_mgr.enrich_stream(repo_id, enrich_queue)
                summary_map.update(result)
                return
            if self._enricher and hasattr(self._enricher, '_gw') and self._enricher._gw:
                result = await self._enricher._gw.enrich_stream(enrich_queue)
                summary_map.update(result)
                return
            while await enrich_queue.get() is not None:
                pass

        enrichment_task = asyncio.create_task(_enrichment_consumer())

        batch_buffer: list[dict[str, str]] = []
        commit_sha = _try_git_head_sha(directory)

        _sentinel_sent = False
        try:
            for fpath, nodes, edges in self._builder.iter_directory_with_cross_file(directory):
                try:
                    if fpath == CodeGraphBuilder.CROSS_FILE_RESOLUTION_PATH:
                        if edges:
                            idx_store = IndexerStore(self._store)
                            await idx_store.upsert_edges_batch(repository or "", edges)
                            total_edges += len(edges)
                            for e in edges:
                                etype = str(e.edge_type)
                                report.edge_counts[etype] = (
                                    report.edge_counts.get(etype, 0) + 1
                                )
                        continue

                    apply_content_hash_to_nodes(nodes)
                    _stamp_repository_metadata(nodes, repository, commit_sha=commit_sha)
                    await self._store.batch_upsert(nodes, edges)
                    total_nodes += len(nodes)
                    total_edges += len(edges)
                    file_paths_for_embed.append(fpath)

                    for n in nodes:
                        if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS):
                            enrich_candidates += 1
                            item = {
                                "name": n.properties.get("name", ""),
                                "signature": n.properties.get("signature", ""),
                                "docstring": n.properties.get("docstring", ""),
                                "code_snippet": n.properties.get("code_snippet", ""),
                                "file": n.properties.get("file", ""),
                                "entity_kind": (
                                    "function" if n.label == NodeLabel.FUNCTION else "class"
                                ),
                            }
                            sr = n.properties.get("semantic_roles")
                            if sr:
                                item["semantic_roles"] = sr
                            if is_trivial_enrichment_entity(item):
                                enrich_skipped_trivial += 1
                                continue
                            if not run_llm_indexing_enrichment:
                                continue
                            if priority_classifier and not priority_classifier.is_core_entity(item):
                                continue
                            item = truncate_enrichment_item(item)
                            enrich_refs.setdefault(item["name"], []).append((n.label, n.uid))
                            batch_buffer.append(item)
                            if len(batch_buffer) >= _ENRICH_BATCH_SIZE:
                                await enrich_queue.put(batch_buffer)
                                batch_buffer = []

                    processed += 1
                    if progress_callback:
                        progress_callback(
                            current_file=fpath,
                            processed_files=processed,
                            nodes=total_nodes,
                            edges=total_edges,
                        )

                    report.record_file_success(fpath, nodes, edges)
                except Exception as exc:
                    report.record_file_failure(fpath, str(exc))
                    report.duration_seconds = time.monotonic() - start_time
                    report.finalize()
                    self._last_report = report
                    log.info("index_quality_report", report=report.to_dict())
                    raise

            if batch_buffer:
                await enrich_queue.put(batch_buffer)
            await enrich_queue.put(None)
            _sentinel_sent = True
        finally:
            if not _sentinel_sent:
                try:
                    await enrich_queue.put(None)
                except Exception:
                    log.debug("enrich_queue_sentinel_put_failed", exc_info=True)
                enrichment_task.cancel()

        try:
            await enrichment_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            log.warning(
                "llm_enrichment_failed_non_fatal",
                directory=directory,
                error=str(exc),
            )

        enriched = 0
        for name, summary in summary_map.items():
            if name in enrich_refs and summary:
                for label, uid in enrich_refs[name]:
                    await self._store.update_node_property(label, uid, "business_summary", summary)
                    enriched += 1
        total_entities = sum(len(v) for v in enrich_refs.values())
        log.info(
            "pipeline_enrich_complete",
            enriched=enriched,
            total_queued=total_entities,
            candidates=enrich_candidates,
            skipped_trivial=enrich_skipped_trivial,
        )

        if progress_callback:
            progress_callback(enriched_count=enriched)

        if progress_callback:
            progress_callback(phase="embedding")
        embed_file_count = len(file_paths_for_embed)
        for idx, fpath in enumerate(file_paths_for_embed):
            nodes_for_embed = await self._store.get_nodes_by_file(fpath)
            if nodes_for_embed:
                total_embeds += await self._generate_and_store_embeddings(
                    nodes_for_embed, skip_enrich=True,
                )
            if progress_callback and (idx + 1) % 20 == 0:
                progress_callback(
                    embeddings=total_embeds,
                    current_file=fpath,
                    phase=f"embedding ({idx + 1}/{embed_file_count})",
                )

        if progress_callback:
            progress_callback(phase="resolving_references", embeddings=total_embeds)
        xref = await self._store.resolve_cross_file_edges()

        enricher = GraphEnricher(self._store)
        enrich_stats = await enricher.enrich()
        log.info("graph_enrichment_complete", **enrich_stats)

        # Supplement missing CONTAINS relationships (Function→Module)
        from indexer.post_process import supplement_contains_relationships
        graph_name = self._store.graph_name if hasattr(self._store, "graph_name") else ""
        try:
            contains_count = await supplement_contains_relationships(self._store, graph_name)
            log.info("supplement_contains_complete", attempted=contains_count)
        except Exception:
            log.warning("supplement_contains_failed", exc_info=True)

        report.duration_seconds = time.monotonic() - start_time
        report.finalize()
        self._last_report = report
        log.info("index_quality_report", report=report.to_dict())

        stats = {
            "nodes": total_nodes,
            "edges": total_edges,
            "embeddings": total_embeds,
            "inherits": xref.get("inherits", 0),
            "imports": xref.get("imports", 0),
            "references": xref.get("references", 0),
            "enriched": enriched,
            "index_report": report.to_dict(),
        }
        log.info("full_index_complete", **{k: v for k, v in stats.items() if k != "index_report"})
        return stats

    async def index_incremental(
        self,
        directory: str,
        base_ref: str = "HEAD~1",
        head_ref: str = "HEAD",
        progress_callback: Callable[..., None] | None = None,
        *,
        repository: str | None = None,
    ) -> dict[str, Any]:
        """Incremental index — streaming parse, single-task enrich, per-file embed."""
        report = IndexReport()
        start_time = time.monotonic()

        changed_files = await self._get_changed_files(directory, base_ref, head_ref)
        if not changed_files:
            report.duration_seconds = time.monotonic() - start_time
            report.finalize()
            self._last_report = report
            log.info("incremental_index_no_changes")
            return {
                "added": 0,
                "modified": 0,
                "deleted": 0,
                "nodes": 0,
                "edges": 0,
                "index_report": report.to_dict(),
            }

        deleted_files = [f for f, status in changed_files if status == "D"]
        modified_files = [f for f, status in changed_files if status in ("A", "M")]

        if progress_callback:
            progress_callback(phase="indexing_code", total_files=len(modified_files))

        deleted_count = 0
        for fpath in deleted_files:
            try:
                deleted_count += await self._store.delete_by_file(fpath)
                full_path = str(Path(directory) / fpath)
                deleted_count += await self._store.delete_by_file(full_path)
                report.record_file_success(fpath, [], [])
            except Exception as exc:
                report.record_file_failure(fpath, str(exc))
                report.duration_seconds = time.monotonic() - start_time
                report.finalize()
                self._last_report = report
                log.info("index_quality_report", report=report.to_dict())
                raise

        total_nodes = 0
        total_edges = 0
        total_doc_nodes = 0
        total_doc_edges = 0

        enrich_items: list[dict[str, str]] = []
        enrich_refs: list[tuple] = []
        enrich_candidates = 0
        enrich_skipped_trivial = 0
        code_file_paths: list[str] = []
        doc_file_paths: list[str] = []

        processed_count = 0
        commit_sha = _try_git_head_sha(directory)
        repo_paths = self._builder.collect_relative_source_paths(directory)
        import_resolver = ImportResolver(ImportResolver.build_file_index(repo_paths))

        enrichment_strategy = get_settings().llm.enrichment_strategy
        run_llm_indexing_enrichment = enrichment_strategy != "disabled"
        priority_classifier = (
            EnrichmentPriorityClassifier() if enrichment_strategy == "core_only" else None
        )

        total_embeds = 0
        for fpath in modified_files:
            try:
                full_path = str(Path(directory) / fpath)
                if not Path(full_path).exists():
                    report.record_file_skipped()
                    continue

                path_keys = _path_keys_for_store(fpath, directory)
                old_hashes = await self._store.get_chunk_hashes_for_files(path_keys)
                old_uids = await self._store.get_node_uids_for_files(path_keys)

                ext = _config_file_extension(Path(fpath))

                if ext in _DOC_EXTENSIONS:
                    try:
                        doc = self._doc_indexer.parse_document(full_path, store_path=fpath)
                        doc_nodes, doc_edges = self._doc_indexer.build_graph(doc)
                        apply_content_hash_to_nodes(doc_nodes)
                        new_uids = {n.uid for n in doc_nodes}
                        stale = list(old_uids - new_uids)
                        await self._store.delete_parser_edges_for_files(path_keys)
                        if stale:
                            await self._store.delete_nodes_by_uids(stale)
                        _stamp_repository_metadata(doc_nodes, repository, commit_sha=commit_sha)
                        await self._store.batch_upsert(doc_nodes, doc_edges)
                        doc_file_paths.append(fpath)
                        total_doc_nodes += len(doc_nodes)
                        total_doc_edges += len(doc_edges)
                        embeddable = [
                            n
                            for n in doc_nodes
                            if n.label
                            in (
                                NodeLabel.FUNCTION,
                                NodeLabel.CLASS,
                                NodeLabel.DOCUMENT,
                                NodeLabel.CHUNK,
                            )
                        ]
                        t_emb = len(embeddable)
                        to_embed = [
                            n
                            for n in embeddable
                            if old_hashes.get(n.uid) != n.properties.get("content_hash")
                        ]
                        log.info(
                            "chunk_skip",
                            file=fpath,
                            total=t_emb,
                            skipped=t_emb - len(to_embed),
                            updated=len(to_embed),
                        )
                        if to_embed:
                            total_embeds += await self._generate_and_store_embeddings(
                                to_embed, skip_enrich=True,
                            )
                        report.record_file_success(fpath, doc_nodes, doc_edges)
                    except Exception as exc:
                        log.warning("incremental_doc_index_error", file=full_path, error=str(exc))
                        report.record_file_failure(fpath, str(exc))
                else:
                    nodes, edges = self._builder.build_from_file(
                        full_path,
                        store_path=fpath,
                        import_resolver=import_resolver,
                    )
                    apply_content_hash_to_nodes(nodes)
                    new_uids = {n.uid for n in nodes}
                    stale = list(old_uids - new_uids)
                    await self._store.delete_parser_edges_for_files(path_keys)
                    if stale:
                        await self._store.delete_nodes_by_uids(stale)
                    _stamp_repository_metadata(nodes, repository, commit_sha=commit_sha)
                    await self._store.batch_upsert(nodes, edges)
                    code_file_paths.append(fpath)
                    total_nodes += len(nodes)
                    total_edges += len(edges)
                    embeddable = [
                        n
                        for n in nodes
                        if n.label
                        in (
                            NodeLabel.FUNCTION,
                            NodeLabel.CLASS,
                            NodeLabel.DOCUMENT,
                            NodeLabel.CHUNK,
                        )
                    ]
                    t_emb = len(embeddable)
                    to_embed = [
                        n
                        for n in embeddable
                        if old_hashes.get(n.uid) != n.properties.get("content_hash")
                    ]
                    log.info(
                        "chunk_skip",
                        file=fpath,
                        total=t_emb,
                        skipped=t_emb - len(to_embed),
                        updated=len(to_embed),
                    )
                    if to_embed:
                        total_embeds += await self._generate_and_store_embeddings(
                            to_embed, skip_enrich=True,
                        )
                    for n in nodes:
                        if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS):
                            enrich_candidates += 1
                            item = {
                                "name": n.properties.get("name", ""),
                                "signature": n.properties.get("signature", ""),
                                "docstring": n.properties.get("docstring", ""),
                                "code_snippet": n.properties.get("code_snippet", ""),
                                "file": n.properties.get("file", ""),
                                "entity_kind": (
                                    "function" if n.label == NodeLabel.FUNCTION else "class"
                                ),
                            }
                            sr = n.properties.get("semantic_roles")
                            if sr:
                                item["semantic_roles"] = sr
                            if is_trivial_enrichment_entity(item):
                                enrich_skipped_trivial += 1
                                continue
                            if not run_llm_indexing_enrichment:
                                continue
                            if priority_classifier and not priority_classifier.is_core_entity(item):
                                continue
                            enrich_refs.append((n.label, n.uid))
                            enrich_items.append(truncate_enrichment_item(item))

                    report.record_file_success(fpath, nodes, edges)

                processed_count += 1
                if progress_callback:
                    progress_callback(
                        current_file=fpath,
                        processed_files=processed_count,
                        nodes=total_nodes,
                        edges=total_edges,
                    )
            except Exception as exc:
                report.record_file_failure(fpath, str(exc))
                report.duration_seconds = time.monotonic() - start_time
                report.finalize()
                self._last_report = report
                log.info("index_quality_report", report=report.to_dict())
                raise

        enrich_backend = self._enrichment_backend_label()
        if enrich_backend and progress_callback:
            progress_callback(phase="enriching", enrichment_backend=enrich_backend)
        repo_id = f"enrich:{directory.rstrip('/').rsplit('/', 1)[-1]}"
        if enrich_items:
            log.info(
                "incremental_enrich_prefilter",
                candidates=enrich_candidates,
                skipped_trivial=enrich_skipped_trivial,
                queued=len(enrich_items),
            )
        enriched_n = await self._enrich_from_items(enrich_items, enrich_refs, repo_id=repo_id)
        del enrich_items, enrich_refs

        if progress_callback and enrich_backend:
            progress_callback(enriched_count=enriched_n)

        if progress_callback:
            progress_callback(phase="embedding", embeddings=total_embeds)

        if progress_callback:
            progress_callback(phase="resolving_references", embeddings=total_embeds)
        xref = await self._store.resolve_cross_file_edges()

        enricher = GraphEnricher(self._store)
        enrich_stats = await enricher.enrich()
        log.info("graph_enrichment_complete", **enrich_stats)

        report.duration_seconds = time.monotonic() - start_time
        report.finalize()
        self._last_report = report
        log.info("index_quality_report", report=report.to_dict())

        stats = {
            "added": len([f for f, s in changed_files if s == "A"]),
            "modified": len([f for f, s in changed_files if s == "M"]),
            "deleted": len(deleted_files),
            "deleted_nodes": deleted_count,
            "nodes": total_nodes,
            "edges": total_edges,
            "doc_nodes": total_doc_nodes,
            "doc_edges": total_doc_edges,
            "embeddings": total_embeds,
            "inherits": xref.get("inherits", 0),
            "imports": xref.get("imports", 0),
            "references": xref.get("references", 0),
            "enriched": enriched_n,
            "index_report": report.to_dict(),
        }
        log.info("incremental_index_complete", **{k: v for k, v in stats.items() if k != "index_report"})

        if repository:
            wiki_cfg = WikiConfig(
                repository=repository,
                mode="structure",
                format="markdown",
                language="en",
            )
            await self._maybe_auto_update_wiki(
                _git_changed_pairs_to_diff_triples(changed_files),
                repository,
                wiki_cfg,
            )

        return stats

    async def enrich_only(
        self,
        entities: list[dict[str, Any]],
        repo_id: str,
        progress_callback: Callable[..., None] | None = None,
    ) -> int:
        """对已入库的 Function/Class 批量生成 business_summary（不重新解析或嵌入）。"""
        if not self._enricher and not self._repo_task_mgr:
            return 0
        if get_settings().llm.enrichment_strategy == "disabled":
            return 0

        work_items: list[dict[str, str]] = []
        work_refs: list[tuple[NodeLabel, str]] = []

        for row in entities:
            label_raw = (row.get("label") or "").strip()
            if label_raw == "Function":
                entity_kind = "function"
                nl: NodeLabel = NodeLabel.FUNCTION
            elif label_raw == "Class":
                entity_kind = "class"
                nl = NodeLabel.CLASS
            else:
                continue

            uid = row.get("uid") or ""
            if not uid:
                continue

            item = {
                "name": row.get("name") or "",
                "signature": row.get("signature") or "",
                "docstring": row.get("docstring") or "",
                "code_snippet": row.get("code_snippet") or "",
                "file": row.get("file") or "",
                "entity_kind": entity_kind,
            }
            sr = row.get("semantic_roles")
            if sr:
                item["semantic_roles"] = sr
            if is_trivial_enrichment_entity(item):
                continue
            work_items.append(item)
            work_refs.append((nl, uid))

        total = len(work_items)
        if not total:
            return 0

        enrich_backend = self._enrichment_backend_label()
        if progress_callback:
            kwargs: dict[str, Any] = {
                "phase": "enriching",
                "total_files": total,
                "processed_files": 0,
            }
            if enrich_backend:
                kwargs["enrichment_backend"] = enrich_backend
            progress_callback(**kwargs)

        enriched_total = 0
        for i in range(0, total, _ENRICH_BATCH_SIZE):
            batch_items = work_items[i : i + _ENRICH_BATCH_SIZE]
            batch_refs = work_refs[i : i + _ENRICH_BATCH_SIZE]
            n_done = await self._enrich_from_items(
                batch_items, batch_refs, repo_id=repo_id,
            )
            enriched_total += n_done
            processed = min(i + _ENRICH_BATCH_SIZE, total)
            if progress_callback:
                progress_callback(
                    processed_files=processed,
                    total_files=total,
                    enriched_count=enriched_total,
                )

        return enriched_total

    async def index_file(
        self,
        file_path: str,
        content: str | None = None,
        *,
        store_path: str | None = None,
        repository: str | None = None,
    ) -> dict[str, int]:
        """Index or reindex a single file.

        *store_path* is the path persisted in the graph (relative to repo root).
        When *None* it equals *file_path* (backward compatible).
        """
        persist = store_path or file_path
        path_keys = {persist, file_path} if file_path != persist else {persist}
        old_hashes = await self._store.get_chunk_hashes_for_files(path_keys)
        old_uids = await self._store.get_node_uids_for_files(path_keys)
        nodes, edges = self._builder.build_from_file(file_path, content, store_path=persist)
        apply_content_hash_to_nodes(nodes)
        new_uids = {n.uid for n in nodes}
        await self._store.delete_parser_edges_for_files(path_keys)
        stale = list(old_uids - new_uids)
        if stale:
            await self._store.delete_nodes_by_uids(stale)
        _sha = _try_git_head_sha_for_file(file_path)
        _stamp_repository_metadata(nodes, repository, commit_sha=_sha)
        await self._store.batch_upsert(nodes, edges)
        embeddable = [
            n
            for n in nodes
            if n.label
            in (
                NodeLabel.FUNCTION,
                NodeLabel.CLASS,
                NodeLabel.DOCUMENT,
                NodeLabel.CHUNK,
            )
        ]
        t_emb = len(embeddable)
        to_embed = [
            n
            for n in embeddable
            if old_hashes.get(n.uid) != n.properties.get("content_hash")
        ]
        log.info(
            "chunk_skip",
            file=persist,
            total=t_emb,
            skipped=t_emb - len(to_embed),
            updated=len(to_embed),
        )
        embed_count = 0
        if to_embed:
            embed_count = await self._generate_and_store_embeddings(to_embed)
        return {"nodes": len(nodes), "edges": len(edges), "embeddings": embed_count}

    async def _enrich_from_items(
        self,
        items: list[dict[str, str]],
        refs: list[tuple],
        repo_id: str = "",
    ) -> int:
        """Enrich code entities in a single ACP task using pre-collected items.

        *refs* is a parallel list of ``(label, uid)`` tuples — only UIDs are
        kept in memory instead of full node objects.  After enrichment,
        ``business_summary`` is written directly to the graph store.

        When *repo_id* is provided and a :class:`RepoTaskManager` is available,
        enrichment reuses the persistent task for that repository.
        """
        if not items:
            return 0
        if not self._enricher and not self._repo_task_mgr:
            return 0

        strategy = get_settings().llm.enrichment_strategy
        if strategy == "disabled":
            return 0
        if strategy == "core_only":
            clf = EnrichmentPriorityClassifier()
            pairs = [(it, ref) for it, ref in zip(items, refs) if clf.is_core_entity(it)]
            if not pairs:
                return 0
            items = [p[0] for p in pairs]
            refs = [p[1] for p in pairs]

        log.info("batch_enrich_start", total_entities=len(items))

        if self._repo_task_mgr and repo_id:
            summaries = await self._repo_task_mgr.enrich(repo_id, items)
        elif self._enricher:
            summaries = await self._enricher.enrich_batch(items)
        else:
            return 0

        if len(summaries) != len(items):
            log.warning(
                "batch_enrich_length_mismatch",
                expected=len(items),
                got=len(summaries),
            )

        enriched = 0
        for (label, uid), summary in zip(refs, summaries):
            if summary:
                await self._store.update_node_property(
                    label, uid, "business_summary", summary,
                )
                enriched += 1

        log.info("batch_enrich_complete", enriched=enriched, total=len(items))
        return enriched

    async def _generate_and_store_embeddings(
        self, nodes: list, *, skip_enrich: bool = False,
    ) -> int:
        """Generate and store embeddings for Function, Class, Document, and Chunk nodes."""
        embeddable = [
            n for n in nodes
            if n.label in (
                NodeLabel.FUNCTION,
                NodeLabel.CLASS,
                NodeLabel.DOCUMENT,
                NodeLabel.CHUNK,
            )
        ]
        if not embeddable:
            return 0

        if not skip_enrich and self._enricher:
            strategy = get_settings().llm.enrichment_strategy
            if strategy != "disabled":
                clf = EnrichmentPriorityClassifier() if strategy == "core_only" else None
                code_nodes = [n for n in embeddable if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS)]
                work_nodes: list[GraphNode] = []
                items_for_enrich: list[dict[str, str]] = []
                for n in code_nodes:
                    item = {
                        "name": n.properties.get("name", ""),
                        "signature": n.properties.get("signature", ""),
                        "docstring": n.properties.get("docstring", ""),
                        "code_snippet": n.properties.get("code_snippet", ""),
                        "file": n.properties.get("file", ""),
                        "entity_kind": (
                            "function" if n.label == NodeLabel.FUNCTION else "class"
                        ),
                    }
                    sr = n.properties.get("semantic_roles")
                    if sr:
                        item["semantic_roles"] = sr
                    if is_trivial_enrichment_entity(item):
                        continue
                    if clf and not clf.is_core_entity(item):
                        continue
                    work_nodes.append(n)
                    items_for_enrich.append(truncate_enrichment_item(item))
                if work_nodes:
                    summaries = await self._enricher.enrich_batch(items_for_enrich)
                    for node, summary in zip(work_nodes, summaries):
                        if summary:
                            node.properties["business_summary"] = summary
                            await self._store.update_node_property(
                                node.label, node.uid, "business_summary", summary
                            )

        doc_indices = [i for i, n in enumerate(embeddable) if n.label == NodeLabel.DOCUMENT]
        code_indices = [
            i
            for i, n in enumerate(embeddable)
            if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS)
        ]
        chunk_indices = [i for i, n in enumerate(embeddable) if n.label == NodeLabel.CHUNK]

        by_index: dict[int, list[float]] = {}
        if doc_indices:
            doc_items = [doc_dict_for_embedding(embeddable[i].properties) for i in doc_indices]
            doc_embs = await self._embedding.generate_for_docs(doc_items)
            for i, emb in zip(doc_indices, doc_embs):
                by_index[i] = emb
        if code_indices:
            code_items = [
                {
                    "name": embeddable[i].properties.get("name", ""),
                    "signature": embeddable[i].properties.get("signature", ""),
                    "docstring": embeddable[i].properties.get("docstring", ""),
                    "code_snippet": embeddable[i].properties.get(
                        "code_snippet", embeddable[i].properties.get("content", ""),
                    ),
                    "business_summary": embeddable[i].properties.get("business_summary", ""),
                }
                for i in code_indices
            ]
            code_embs = await self._embedding.generate_for_code(code_items)
            for i, emb in zip(code_indices, code_embs):
                by_index[i] = emb
        if chunk_indices:
            chunk_items = [
                {
                    "name": "",
                    "signature": "",
                    "docstring": "",
                    "code_snippet": str(
                        embeddable[i].properties.get("text", "")
                        or embeddable[i].properties.get("code_snippet", "")
                        or "",
                    ),
                    "business_summary": embeddable[i].properties.get("business_summary", ""),
                }
                for i in chunk_indices
            ]
            chunk_embs = await self._embedding.generate_for_code(chunk_items)
            for i, emb in zip(chunk_indices, chunk_embs):
                by_index[i] = emb

        for idx, node in enumerate(embeddable):
            await self._store.set_node_embedding(node.uid, node.label, by_index[idx])

        return len(embeddable)

    def _is_indexable_file(self, file_path: str) -> bool:
        """Check if a file is indexable (code or document)."""
        parts = Path(file_path).parts
        if any(part in _get_exclude_dirs() for part in parts):
            return False
        ext = _config_file_extension(Path(file_path))
        return self._builder.detect_language(file_path) is not None or ext in _DOC_EXTENSIONS

    async def _get_changed_files(
        self, directory: str, base_ref: str, head_ref: str,
    ) -> list[tuple[str, str]]:
        """Run git diff to find changed files with their status.

        Includes both code files and document files (.md, .rst, .txt).
        """
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "diff", "--name-status", base_ref, head_ref],
                    capture_output=True,
                    text=True,
                    cwd=directory,
                    timeout=30,
                ),
            )
            if result.returncode != 0:
                error_msg = result.stderr.strip()
                log.error("git_diff_failed", stderr=error_msg, base_ref=base_ref, head_ref=head_ref)
                raise RuntimeError(f"git diff failed: {error_msg}")

            files: list[tuple[str, str]] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t")
                if len(parts) >= 2:
                    status = parts[0]
                    if status[0] in ("R", "C") and len(parts) >= 3:
                        old_path, new_path = parts[1], parts[2]
                        if self._is_indexable_file(old_path):
                            files.append((old_path, "D"))
                        if self._is_indexable_file(new_path):
                            files.append((new_path, "A"))
                    else:
                        fpath = parts[1]
                        if self._is_indexable_file(fpath):
                            files.append((fpath, status[0]))
            return files

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.error("git_diff_error", error=str(exc))
            raise RuntimeError(f"git diff error: {exc}") from exc
