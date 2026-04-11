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
from typing import TYPE_CHECKING

from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator
from log import get_logger
from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel

if TYPE_CHECKING:
    from indexer.enrichment import CodeSummaryEnricher

log = get_logger(__name__)

_DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}

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
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen
        self._doc_indexer = doc_indexer or DocumentIndexer()
        self._enricher = enricher

    async def index_full(
        self, directory: str, progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Full reindex — three phases: parse, enrich (1 ACP task), embed."""
        log.info("full_index_start", directory=directory)

        total_nodes = 0
        total_edges = 0
        total_embeds = 0
        processed = 0
        all_file_nodes: list[list] = []

        if progress_callback:
            progress_callback(phase="indexing_code")

        for fpath, nodes, edges in self._builder.iter_directory(directory):
            await self._store.batch_upsert(nodes, edges)
            total_nodes += len(nodes)
            total_edges += len(edges)
            all_file_nodes.append(nodes)
            processed += 1
            if progress_callback:
                progress_callback(
                    current_file=fpath,
                    processed_files=processed,
                    nodes=total_nodes,
                    edges=total_edges,
                )

        if progress_callback:
            progress_callback(phase="enriching")
        await self._batch_enrich_all(all_file_nodes)

        if progress_callback:
            progress_callback(phase="embedding")
        for nodes in all_file_nodes:
            total_embeds += await self._generate_and_store_embeddings(nodes, skip_enrich=True)

        if progress_callback:
            progress_callback(phase="resolving_references")
        xref = await self._store.resolve_cross_file_edges()

        stats = {
            "nodes": total_nodes,
            "edges": total_edges,
            "embeddings": total_embeds,
            "inherits": xref.get("inherits", 0),
            "imports": xref.get("imports", 0),
            "references": xref.get("references", 0),
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
        """Incremental index — three phases: parse changed files, enrich (1 task), embed."""
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
        all_code_nodes: list[list] = []
        all_doc_nodes: list[list] = []

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
                    all_doc_nodes.append(doc_nodes)
                    total_doc_nodes += len(doc_nodes)
                    total_doc_edges += len(doc_edges)
                except Exception as exc:
                    log.warning("incremental_doc_index_error", file=full_path, error=str(exc))
            else:
                nodes, edges = self._builder.build_from_file(full_path, store_path=fpath)
                await self._store.batch_upsert(nodes, edges)
                all_code_nodes.append(nodes)
                total_nodes += len(nodes)
                total_edges += len(edges)

            processed_count += 1
            if progress_callback:
                progress_callback(
                    current_file=fpath,
                    processed_files=processed_count,
                    nodes=total_nodes,
                    edges=total_edges,
                )

        if progress_callback:
            progress_callback(phase="enriching")
        await self._batch_enrich_all(all_code_nodes)

        if progress_callback:
            progress_callback(phase="embedding")
        total_embeds = 0
        for nodes in all_code_nodes:
            total_embeds += await self._generate_and_store_embeddings(nodes, skip_enrich=True)
        for doc_nodes in all_doc_nodes:
            total_embeds += await self._generate_and_store_embeddings(doc_nodes, skip_enrich=True)

        if progress_callback:
            progress_callback(phase="resolving_references")
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
        }
        log.info("incremental_index_complete", **stats)
        return stats

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

    async def _batch_enrich_all(self, all_file_nodes: list[list]) -> int:
        """Enrich all code entities across all files in a single ACP task."""
        if not self._enricher:
            return 0

        code_node_list: list[tuple] = []
        items_for_enrich: list[dict[str, str]] = []

        for nodes in all_file_nodes:
            for n in nodes:
                if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS):
                    code_node_list.append(n)
                    items_for_enrich.append({
                        "name": n.properties.get("name", ""),
                        "signature": n.properties.get("signature", ""),
                        "docstring": n.properties.get("docstring", ""),
                        "code_snippet": n.properties.get("code_snippet", ""),
                        "file": n.properties.get("file", ""),
                    })

        if not items_for_enrich:
            return 0

        log.info("batch_enrich_start", total_entities=len(items_for_enrich))
        summaries = await self._enricher.enrich_batch(items_for_enrich)

        if len(summaries) != len(items_for_enrich):
            log.warning(
                "batch_enrich_length_mismatch",
                expected=len(items_for_enrich),
                got=len(summaries),
            )

        enriched = 0
        for node, summary in zip(code_node_list, summaries):
            if summary:
                node.properties["business_summary"] = summary
                await self._store.update_node_property(
                    node.label, node.uid, "business_summary", summary,
                )
                enriched += 1

        log.info("batch_enrich_complete", enriched=enriched, total=len(items_for_enrich))
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
