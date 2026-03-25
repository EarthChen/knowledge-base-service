"""Incremental indexer — indexes only changed files based on git diff.

Supports both full reindexing and incremental updates triggered by
git push events or manual requests.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from log import get_logger

from store.falkordb_store import FalkorDBStore
from store.schema import NodeLabel
from indexer.code_graph_builder import CodeGraphBuilder
from indexer.embedding_generator import EmbeddingGenerator

log = get_logger(__name__)


class IncrementalIndexer:
    """Orchestrates code indexing — full or incremental."""

    def __init__(
        self,
        store: FalkorDBStore,
        graph_builder: CodeGraphBuilder,
        embedding_gen: EmbeddingGenerator,
    ) -> None:
        self._store = store
        self._builder = graph_builder
        self._embedding = embedding_gen

    async def index_full(self, directory: str) -> dict[str, int]:
        """Full reindex of all supported files in a directory."""
        log.info("full_index_start", directory=directory)

        nodes, edges = self._builder.build_from_directory(directory)
        await self._store.batch_upsert(nodes, edges)

        embed_count = await self._generate_and_store_embeddings(nodes)

        stats = {"nodes": len(nodes), "edges": len(edges), "embeddings": embed_count}
        log.info("full_index_complete", **stats)
        return stats

    async def index_incremental(
        self,
        directory: str,
        base_ref: str = "HEAD~1",
        head_ref: str = "HEAD",
    ) -> dict[str, int]:
        """Incremental index based on git diff between two refs."""
        changed_files = await self._get_changed_files(directory, base_ref, head_ref)
        if not changed_files:
            log.info("incremental_index_no_changes")
            return {"added": 0, "modified": 0, "deleted": 0, "nodes": 0, "edges": 0}

        deleted_files = [f for f, status in changed_files if status == "D"]
        modified_files = [f for f, status in changed_files if status in ("A", "M")]

        deleted_count = 0
        for fpath in deleted_files:
            deleted_count += await self._store.delete_by_file(fpath)

        total_nodes = 0
        total_edges = 0
        for fpath in modified_files:
            await self._store.delete_by_file(fpath)
            full_path = str(Path(directory) / fpath)
            if not Path(full_path).exists():
                continue

            nodes, edges = self._builder.build_from_file(full_path)
            await self._store.batch_upsert(nodes, edges)
            await self._generate_and_store_embeddings(nodes)
            total_nodes += len(nodes)
            total_edges += len(edges)

        stats = {
            "added": len([f for _, s in changed_files if s == "A"]),
            "modified": len([f for _, s in changed_files if s == "M"]),
            "deleted": len(deleted_files),
            "deleted_nodes": deleted_count,
            "nodes": total_nodes,
            "edges": total_edges,
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

    async def _get_changed_files(
        self, directory: str, base_ref: str, head_ref: str,
    ) -> list[tuple[str, str]]:
        """Run git diff to find changed files with their status."""
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
                    if self._builder.detect_language(fpath) is not None:
                        files.append((fpath, status[0]))
            return files

        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            log.warning("git_diff_error", error=str(exc))
            return []
