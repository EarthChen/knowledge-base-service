"""Document indexing capabilities for the MCP knowledge base handler."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Callable
from typing import Any

from core.log import get_logger
from indexer.config_indexer import _config_file_extension
from indexer.doc_indexer import DocumentIndexer
from indexer.embedding_generator import doc_dict_for_embedding
from utils.git_utils import looks_like_git_url

from api.mcp_helpers import _mcp_error

log = get_logger(__name__)


class DocumentIndexerMixin:
    """Mixin providing document indexing capabilities for MCP handler."""

    async def handle_rag_index(
        self, args: dict[str, Any], progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, Any]:
        git_url = str(args.get("git_url") or "").strip()
        directory = str(args.get("directory") or "").strip()
        mode_raw = args.get("mode", "full")
        mode = str(mode_raw) if mode_raw is not None else "full"
        repository = args.get("repository")

        if git_url:
            if not looks_like_git_url(git_url):
                return _mcp_error("invalid_params", "git_url must be an https, ssh, git@, or .git remote URL")

            from pathlib import Path as _Path

            from core.config import get_settings
            from services.git_manager import GitManager

            branch_arg = args.get("branch")
            branch = str(branch_arg).strip() if branch_arg not in (None, "") else None

            settings = get_settings()
            mgr = GitManager(settings.git)
            clone_result = await mgr.ensure_repo(git_url, branch=branch)
            if clone_result["status"] in ("clone_failed", "pull_failed"):
                detail = clone_result.get("detail", "") or "git operation failed"
                return _mcp_error("git_operation_failed", detail)

            directory = str(clone_result.get("directory") or "").strip()
            if not directory:
                return _mcp_error("git_operation_failed", "No directory resolved after clone/pull")

            base_path = _Path(settings.git.clone_base_path).resolve()
            resolved_dir = _Path(directory).resolve()
            if not resolved_dir.is_relative_to(base_path):
                return _mcp_error("invalid_params", "Clone directory escapes allowed base path")

            if repository is None or (isinstance(repository, str) and not repository.strip()):
                repository = clone_result.get("repository")

            if clone_result["status"] == "cloned" and mode == "incremental":
                mode = "full"

        elif not directory:
            return _mcp_error(
                "invalid_params",
                "Provide directory (local path) or git_url for remote indexing.",
            )

        effective_mode = mode
        if effective_mode == "incremental" and repository and self._store:
            from store.graph_queries import GraphQueryRepository

            queries = GraphQueryRepository(self._store)
            repo_key = str(repository).strip()
            sample = await queries.get_repository_sample_file(repo_key)
            if sample is None:
                effective_mode = "full"

        if effective_mode == "incremental":
            base_ref = args.get("base_ref", "HEAD~1")
            head_ref = args.get("head_ref", "HEAD")
            stats = await self._indexer.index_incremental(
                directory,
                base_ref,
                head_ref,
                progress_callback=progress_callback,
                repository=repository,
            )
            doc_stats = {}
        else:
            stats = await self._indexer.index_full(
                directory, progress_callback=progress_callback, repository=repository,
            )
            doc_stats = await self._index_docs_full(
                directory, progress_callback=progress_callback, repository=repository,
            )

        stats.update(doc_stats)
        return {"mode": effective_mode, "directory": directory, "stats": stats}

    async def _index_docs_full(
        self,
        directory: str,
        progress_callback: Callable[..., None] | None = None,
        *,
        repository: str | None = None,
    ) -> dict[str, int]:
        """Index all documents (.md, .rst, .txt) — one file at a time."""
        if not self._doc_indexer or not self._store:
            return {}

        from pathlib import Path

        from indexer.incremental_indexer import _stamp_repository_metadata, _try_git_head_sha

        base = Path(directory)
        commit_sha = _try_git_head_sha(directory)
        total_nodes = 0
        total_edges = 0
        total_embeds = 0

        exclude_dirs = set(self._doc_indexer._exclude_dirs)
        doc_paths: list[Path] = []
        for fpath in DocumentIndexer.iter_supported_paths(base):
            if any(part in exclude_dirs for part in fpath.parts):
                continue
            doc_paths.append(fpath)

        if progress_callback:
            progress_callback(phase="indexing_docs", total_files=len(doc_paths))

        processed = 0
        for fpath in doc_paths:
            try:
                rel = str(fpath.relative_to(base))
                doc = self._doc_indexer.parse_document(str(fpath), store_path=rel)
                nodes, edges = self._doc_indexer.build_graph(doc)
                _stamp_repository_metadata(nodes, repository, commit_sha=commit_sha)
                await self._store.batch_upsert(nodes, edges)
                total_nodes += len(nodes)
                total_edges += len(edges)

                if self._embedding:
                    embeddable = [n for n in nodes if n.properties.get("content")]
                    if embeddable:
                        items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                        embeddings = await self._embedding.generate_for_docs(items)
                        for node, emb in zip(embeddable, embeddings):
                            await self._store.set_node_embedding(node.uid, node.label, emb)
                        total_embeds += len(embeddings)
                processed += 1
                if progress_callback:
                    progress_callback(
                        current_file=str(fpath),
                        processed_files=processed,
                        doc_nodes=total_nodes,
                        doc_edges=total_edges,
                        doc_embeddings=total_embeds,
                    )
            except Exception as exc:
                log.warning("doc_index_error", file=str(fpath), error=str(exc))

        return {
            "doc_nodes": total_nodes,
            "doc_edges": total_edges,
            "doc_embeddings": total_embeds,
        }

    async def _index_docs_incremental(
        self,
        directory: str,
        base_ref: str,
        head_ref: str,
        progress_callback: Callable[..., None] | None = None,
    ) -> dict[str, int]:
        """Incrementally index changed document files based on git diff."""
        if not self._doc_indexer or not self._store:
            return {}

        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["git", "diff", "--name-status", base_ref, head_ref],
                    capture_output=True, text=True, cwd=directory, timeout=30,
                ),
            )
            if result.returncode != 0:
                return {}

            doc_exts = DocumentIndexer.SUPPORTED_EXTENSIONS
            changed: list[tuple[str, str]] = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("\t", 1)
                if len(parts) == 2:
                    status, fpath = parts
                    if _config_file_extension(Path(fpath)) in doc_exts:
                        changed.append((fpath, status[0]))

            if not changed:
                return {"doc_nodes": 0, "doc_edges": 0, "doc_embeddings": 0}

            if progress_callback:
                progress_callback(phase="indexing_docs", total_files=len(changed))

            total_nodes = 0
            total_edges = 0
            total_embeds = 0

            processed = 0
            for fpath, status in changed:
                await self._store.delete_by_file(fpath)
                if status != "D":
                    full_path = str(Path(directory) / fpath)
                    if Path(full_path).exists():
                        doc = self._doc_indexer.parse_document(full_path, store_path=fpath)
                        nodes, edges = self._doc_indexer.build_graph(doc)
                        await self._store.batch_upsert(nodes, edges)
                        total_nodes += len(nodes)
                        total_edges += len(edges)

                        if self._embedding:
                            embeddable = [n for n in nodes if n.properties.get("content")]
                            if embeddable:
                                items = [doc_dict_for_embedding(n.properties) for n in embeddable]
                                embeddings = await self._embedding.generate_for_docs(items)
                                for node, emb in zip(embeddable, embeddings):
                                    await self._store.set_node_embedding(node.uid, node.label, emb)
                                total_embeds += len(embeddings)

                processed += 1
                if progress_callback:
                    progress_callback(
                        current_file=fpath,
                        processed_files=processed,
                        doc_nodes=total_nodes,
                        doc_edges=total_edges,
                        doc_embeddings=total_embeds,
                    )

            return {
                "doc_nodes": total_nodes,
                "doc_edges": total_edges,
                "doc_embeddings": total_embeds,
            }

        except (subprocess.TimeoutExpired, FileNotFoundError):
            return {}
