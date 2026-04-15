"""Incremental indexer — indexes only changed files based on git diff.

Supports both full reindexing and incremental updates triggered by
git push events or manual requests.  Handles both code files and
document files (.md, .rst, .txt) in incremental mode.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator
from indexer.enrichment import is_trivial_enrichment_entity, truncate_enrichment_item
from log import get_logger
from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel

if TYPE_CHECKING:
    from indexer.enrichment import CodeSummaryEnricher
    from llm.gateway_client import RepoTaskManager

log = get_logger(__name__)

_DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}
_ENRICH_BATCH_SIZE = 50

def _get_exclude_dirs() -> set[str]:
    from config import get_settings
    return set(get_settings().exclude_dirs)


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
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen
        self._doc_indexer = doc_indexer or DocumentIndexer()
        self._enricher = enricher
        self._repo_task_mgr = repo_task_manager

    @property
    def enrichment_available(self) -> bool:
        """Whether LLM 摘要（直连或网关）可用于补全 business_summary。"""
        return self._enricher is not None or self._repo_task_mgr is not None

    def _enrichment_backend_label(self) -> str:
        """Return API progress label for LLM enrichment mode (empty if disabled)."""
        if not self._enricher:
            return ""
        if self._repo_task_mgr and getattr(self._enricher, "_gw", None):
            return "gateway"
        return "direct"

    async def index_full(
        self, directory: str, progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Full reindex — pipelined parse+enrich (1 ACP task) then embed.

        Parse and enrichment run concurrently: as files are parsed, code
        entities are streamed into the feedback loop via an asyncio queue.
        Only lightweight enrichment items flow through the queue; full node
        objects are released after upsert.
        """
        log.info("full_index_start", directory=directory)

        enrich_backend = self._enrichment_backend_label()

        total_nodes = 0
        total_edges = 0
        total_embeds = 0
        processed = 0
        file_paths_for_embed: list[str] = []
        enrich_refs: dict[str, list[tuple]] = {}
        enrich_candidates = 0
        enrich_skipped_trivial = 0

        enrich_queue: asyncio.Queue[list[dict[str, str]] | None] = asyncio.Queue()
        summary_map: dict[str, str] = {}

        if progress_callback:
            progress_callback(
                phase="indexing_and_enriching",
                enrichment_backend=enrich_backend,
            )

        repo_id = f"enrich:{directory.rstrip('/').rsplit('/', 1)[-1]}"

        async def _enrichment_consumer() -> None:
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

        for fpath, nodes, edges in self._builder.iter_directory(directory):
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
                    if is_trivial_enrichment_entity(item):
                        enrich_skipped_trivial += 1
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

        if batch_buffer:
            await enrich_queue.put(batch_buffer)
        await enrich_queue.put(None)

        await enrichment_task

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

        stats = {
            "nodes": total_nodes,
            "edges": total_edges,
            "embeddings": total_embeds,
            "inherits": xref.get("inherits", 0),
            "imports": xref.get("imports", 0),
            "references": xref.get("references", 0),
            "enriched": enriched,
        }
        log.info("full_index_complete", **stats)
        return stats

    async def index_incremental(
        self,
        directory: str,
        base_ref: str = "HEAD~1",
        head_ref: str = "HEAD",
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Incremental index — streaming parse, single-task enrich, per-file embed."""
        changed_files = await self._get_changed_files(directory, base_ref, head_ref)
        if not changed_files:
            log.info("incremental_index_no_changes")
            return {"added": 0, "modified": 0, "deleted": 0, "nodes": 0, "edges": 0}

        deleted_files = [f for f, status in changed_files if status == "D"]
        modified_files = [f for f, status in changed_files if status in ("A", "M")]

        if progress_callback:
            progress_callback(phase="indexing_code", total_files=len(modified_files))

        deleted_count = 0
        for fpath in deleted_files:
            deleted_count += await self._store.delete_by_file(fpath)
            full_path = str(Path(directory) / fpath)
            deleted_count += await self._store.delete_by_file(full_path)

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
        for fpath in modified_files:
            full_path = str(Path(directory) / fpath)
            await self._store.delete_by_file(fpath)
            await self._store.delete_by_file(full_path)
            if not Path(full_path).exists():
                continue

            suffix = Path(fpath).suffix.lower()

            if suffix in _DOC_EXTENSIONS:
                try:
                    doc = self._doc_indexer.parse_document(full_path, store_path=fpath)
                    doc_nodes, doc_edges = self._doc_indexer.build_graph(doc)
                    await self._store.batch_upsert(doc_nodes, doc_edges)
                    doc_file_paths.append(fpath)
                    total_doc_nodes += len(doc_nodes)
                    total_doc_edges += len(doc_edges)
                except Exception as exc:
                    log.warning("incremental_doc_index_error", file=full_path, error=str(exc))
            else:
                nodes, edges = self._builder.build_from_file(full_path, store_path=fpath)
                await self._store.batch_upsert(nodes, edges)
                code_file_paths.append(fpath)
                total_nodes += len(nodes)
                total_edges += len(edges)
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
                        if is_trivial_enrichment_entity(item):
                            enrich_skipped_trivial += 1
                            continue
                        enrich_refs.append((n.label, n.uid))
                        enrich_items.append(truncate_enrichment_item(item))

            processed_count += 1
            if progress_callback:
                progress_callback(
                    current_file=fpath,
                    processed_files=processed_count,
                    nodes=total_nodes,
                    edges=total_edges,
                )

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
            progress_callback(phase="embedding")
        total_embeds = 0
        all_embed_paths = code_file_paths + doc_file_paths
        embed_total = len(all_embed_paths)
        for idx, fpath in enumerate(all_embed_paths):
            nodes_for_embed = await self._store.get_nodes_by_file(fpath)
            if nodes_for_embed:
                total_embeds += await self._generate_and_store_embeddings(
                    nodes_for_embed, skip_enrich=True,
                )
            if progress_callback and (idx + 1) % 20 == 0:
                progress_callback(
                    embeddings=total_embeds,
                    current_file=fpath,
                    phase=f"embedding ({idx + 1}/{embed_total})",
                )

        if progress_callback:
            progress_callback(phase="resolving_references", embeddings=total_embeds)
        xref = await self._store.resolve_cross_file_edges()

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
        }
        log.info("incremental_index_complete", **stats)
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
            if is_trivial_enrichment_entity(item):
                continue
            work_items.append(truncate_enrichment_item(item))
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
        self, file_path: str, content: str | None = None, *, store_path: str | None = None,
    ) -> dict[str, int]:
        """Index or reindex a single file.

        *store_path* is the path persisted in the graph (relative to repo root).
        When *None* it equals *file_path* (backward compatible).
        """
        persist = store_path or file_path
        await self._store.delete_by_file(persist)
        if persist != file_path:
            await self._store.delete_by_file(file_path)
        nodes, edges = self._builder.build_from_file(file_path, content, store_path=persist)
        await self._store.batch_upsert(nodes, edges)
        embed_count = await self._generate_and_store_embeddings(nodes)
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
        """Generate and store embeddings for Function, Class, and Document nodes."""
        embeddable = [
            n for n in nodes
            if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS, NodeLabel.DOCUMENT)
        ]
        if not embeddable:
            return 0

        if not skip_enrich and self._enricher:
            code_nodes = [n for n in embeddable if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS)]
            if code_nodes:
                items_for_enrich = [
                    {
                        "name": n.properties.get("name", ""),
                        "signature": n.properties.get("signature", ""),
                        "docstring": n.properties.get("docstring", ""),
                        "code_snippet": n.properties.get("code_snippet", ""),
                        "file": n.properties.get("file", ""),
                        "entity_kind": (
                            "function" if n.label == NodeLabel.FUNCTION else "class"
                        ),
                    }
                    for n in code_nodes
                ]
                summaries = await self._enricher.enrich_batch(items_for_enrich)
                for node, summary in zip(code_nodes, summaries):
                    if summary:
                        node.properties["business_summary"] = summary
                        await self._store.update_node_property(
                            node.label, node.uid, "business_summary", summary
                        )

        items = [
            {
                "name": n.properties.get("name", ""),
                "signature": n.properties.get("signature", ""),
                "docstring": n.properties.get("docstring", ""),
                "code_snippet": n.properties.get("code_snippet", n.properties.get("content", "")),
                "business_summary": n.properties.get("business_summary", ""),
            }
            for n in embeddable
        ]

        embeddings = await self._embedding.generate_for_code(items)

        for node, emb in zip(embeddable, embeddings):
            await self._store.set_node_embedding(node.uid, node.label, emb)

        return len(embeddings)

    def _is_indexable_file(self, file_path: str) -> bool:
        """Check if a file is indexable (code or document)."""
        parts = Path(file_path).parts
        if any(part in _get_exclude_dirs() for part in parts):
            return False
        suffix = Path(file_path).suffix.lower()
        return self._builder.detect_language(file_path) is not None or suffix in _DOC_EXTENSIONS

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
