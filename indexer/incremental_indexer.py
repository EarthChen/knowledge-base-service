"""Incremental indexer — indexes only changed files based on git diff.

Supports both full reindexing and incremental updates triggered by
git push events or manual requests.  Handles both code files and
document files (.md, .rst, .txt) in incremental mode.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from log import get_logger

from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import EmbeddingGenerator

log = get_logger(__name__)

_DOC_EXTENSIONS = {".md", ".markdown", ".rst", ".txt"}


class IncrementalIndexer:
    """Orchestrates code + document indexing — full or incremental."""

    def __init__(
        self,
        store: FalkorDBStore,
        graph_builder: CodeGraphBuilder,
        embedding_gen: EmbeddingGenerator,
        doc_indexer: DocumentIndexer | None = None,
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen
        self._doc_indexer = doc_indexer or DocumentIndexer()

    async def index_full(self, directory: str) -> dict[str, int]:
        """Full reindex — processes files one at a time to cap memory usage."""
        log.info("full_index_start", directory=directory)

        total_nodes = 0
        total_edges = 0
        total_embeds = 0

        for fpath, nodes, edges in self._builder.iter_directory(directory):
            await self._store.batch_upsert(nodes, edges)
            total_nodes += len(nodes)
            total_edges += len(edges)
            total_embeds += await self._generate_and_store_embeddings(nodes)

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
    ) -> dict[str, int]:
        """Incremental index based on git diff between two refs.

        Handles both code files (via CodeGraphBuilder) and document files
        (.md, .rst, .txt via DocumentIndexer).
        """
        changed_files = await self._get_changed_files(directory, base_ref, head_ref)
        if not changed_files:
            log.info("incremental_index_no_changes")
            return {"added": 0, "modified": 0, "deleted": 0, "nodes": 0, "edges": 0}

        deleted_files = [f for f, status in changed_files if status == "D"]
        modified_files = [f for f, status in changed_files if status in ("A", "M")]

        deleted_count = 0
        for fpath in deleted_files:
            full_path = str(Path(directory) / fpath)
            deleted_count += await self._store.delete_by_file(full_path)

        total_nodes = 0
        total_edges = 0
        total_doc_nodes = 0
        total_doc_edges = 0

        for fpath in modified_files:
            full_path = str(Path(directory) / fpath)
            await self._store.delete_by_file(full_path)
            if not Path(full_path).exists():
                continue

            suffix = Path(fpath).suffix.lower()

            if suffix in _DOC_EXTENSIONS:
                try:
                    doc = self._doc_indexer.parse_document(full_path)
                    doc_nodes, doc_edges = self._doc_indexer.build_graph(doc)
                    await self._store.batch_upsert(doc_nodes, doc_edges)
                    await self._generate_and_store_embeddings(doc_nodes)
                    total_doc_nodes += len(doc_nodes)
                    total_doc_edges += len(doc_edges)
                except Exception as exc:
                    log.warning("incremental_doc_index_error", file=full_path, error=str(exc))
            else:
                nodes, edges = self._builder.build_from_file(full_path)
                await self._store.batch_upsert(nodes, edges)
                await self._generate_and_store_embeddings(nodes)
                total_nodes += len(nodes)
                total_edges += len(edges)

        xref = await self._store.resolve_cross_file_edges()

        stats = {
            "added": len([f for _, s in changed_files if s == "A"]),
            "modified": len([f for _, s in changed_files if s == "M"]),
            "deleted": len(deleted_files),
            "deleted_nodes": deleted_count,
            "nodes": total_nodes,
            "edges": total_edges,
            "doc_nodes": total_doc_nodes,
            "doc_edges": total_doc_edges,
            "inherits": xref.get("inherits", 0),
            "imports": xref.get("imports", 0),
            "references": xref.get("references", 0),
        }
        log.info("incremental_index_complete", **stats)
        return stats

    async def index_file(self, file_path: str, content: str | None = None) -> dict[str, int]:
        """Index or reindex a single file."""
        await self._store.delete_by_file(file_path)
        nodes, edges = self._builder.build_from_file(file_path, content)
        await self._store.batch_upsert(nodes, edges)
        embed_count = await self._generate_and_store_embeddings(nodes)
        return {"nodes": len(nodes), "edges": len(edges), "embeddings": embed_count}

    async def _generate_and_store_embeddings(self, nodes: list) -> int:
        """Generate and store embeddings for Function, Class, and Document nodes."""
        embeddable = [
            n for n in nodes
            if n.label in (NodeLabel.FUNCTION, NodeLabel.CLASS, NodeLabel.DOCUMENT)
        ]
        if not embeddable:
            return 0

        items = [
            {
                "name": n.properties.get("name", ""),
                "signature": n.properties.get("signature", ""),
                "docstring": n.properties.get("docstring", ""),
                "code_snippet": n.properties.get("code_snippet", n.properties.get("content", "")),
            }
            for n in embeddable
        ]

        embeddings = await self._embedding.generate_for_code(items)

        for node, emb in zip(embeddable, embeddings):
            await self._store.set_node_embedding(node.uid, node.label, emb)

        return len(embeddings)

    def _is_indexable_file(self, file_path: str) -> bool:
        """Check if a file is indexable (code or document)."""
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
                log.warning("git_diff_failed", stderr=result.stderr.strip())
                return []

            files: list[tuple[str, str]] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, fpath = parts
                    if self._is_indexable_file(fpath):
                        files.append((fpath, status[0]))
            return files

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.warning("git_diff_error", error=str(exc))
            return []
