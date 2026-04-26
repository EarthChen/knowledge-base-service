"""Reads actual source code for wiki page generation."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from store.schema import GraphNode
from wiki.models import CodeSnippet

logger = logging.getLogger(__name__)


class SourceCodeReader:
    """Reads code from Chunk nodes, file fallback, or signature degradation."""

    def __init__(self, wiki_store: Any) -> None:
        self._store = wiki_store

    async def read(
        self,
        node: GraphNode,
        budget_tokens: int = 8000,
        repo_path: str | None = None,
    ) -> list[CodeSnippet]:
        snippets = await self._read_from_chunks(node)
        if not snippets and repo_path:
            snippets = self._read_from_file(node, repo_path)
        if not snippets:
            snippets = self._fallback_to_signature(node)

        return self._apply_budget(snippets, budget_tokens)

    async def _read_from_chunks(self, node: GraphNode) -> list[CodeSnippet]:
        result = await self._store.find_chunks_by_parent_uid(node.uid)
        if not result or not result.result_set:
            return []

        texts: list[tuple[str, str, int, int]] = []
        for row in result.result_set:
            text, file_path, start_line, end_line, _idx = row
            if text:
                texts.append((str(text), str(file_path), int(start_line), int(end_line)))

        if not texts:
            return []

        merged_source = "\n".join(t[0] for t in texts)
        file_path = texts[0][1]
        start_line = texts[0][2]
        end_line = texts[-1][3]

        return [CodeSnippet(
            source=merged_source,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            origin="chunk",
        )]

    def _read_from_file(self, node: GraphNode, repo_path: str) -> list[CodeSnippet]:
        file_rel = str(node.properties.get("file", ""))
        start_line = int(node.properties.get("start_line", 0))
        end_line = int(node.properties.get("end_line", 0))

        if not file_rel or start_line <= 0:
            return []

        full_path = Path(repo_path) / file_rel
        if not full_path.is_file():
            logger.debug("File not found for code read: %s", full_path)
            return []

        try:
            lines = full_path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[max(0, start_line - 1):end_line]
            source = "\n".join(selected)
            return [CodeSnippet(
                source=source,
                file_path=file_rel,
                start_line=start_line,
                end_line=end_line,
                origin="file",
            )]
        except OSError:
            logger.debug("Failed to read file: %s", full_path, exc_info=True)
            return []

    def _fallback_to_signature(self, node: GraphNode) -> list[CodeSnippet]:
        sig = str(node.properties.get("signature", ""))
        doc = str(node.properties.get("docstring", ""))
        file_path = str(node.properties.get("file", ""))
        start_line = int(node.properties.get("start_line", 0))
        end_line = int(node.properties.get("end_line", 0))

        parts = [p for p in [sig, doc] if p]
        if not parts:
            return []

        return [CodeSnippet(
            source="\n".join(parts),
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            origin="signature",
        )]

    def _apply_budget(self, snippets: list[CodeSnippet], budget_tokens: int) -> list[CodeSnippet]:
        result = []
        remaining = budget_tokens
        for snippet in snippets:
            tokens = self.estimate_tokens(snippet.source)
            if tokens <= remaining:
                result.append(snippet)
                remaining -= tokens
            else:
                truncated_source = self.truncate_code(snippet.source, remaining)
                result.append(CodeSnippet(
                    source=truncated_source,
                    file_path=snippet.file_path,
                    start_line=snippet.start_line,
                    end_line=snippet.end_line,
                    origin=snippet.origin,
                ))
                break
        return result

    def estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def truncate_code(self, code: str, max_tokens: int) -> str:
        max_chars = max_tokens * 4
        if len(code) <= max_chars:
            return code
        lines = code.splitlines()
        total_lines = len(lines)
        head_budget = int(max_chars * 0.6)
        tail_budget = max_chars - head_budget - 80

        head_lines: list[str] = []
        head_chars = 0
        for line in lines:
            if head_chars + len(line) + 1 > head_budget:
                break
            head_lines.append(line)
            head_chars += len(line) + 1

        tail_lines: list[str] = []
        tail_chars = 0
        for line in reversed(lines):
            if tail_chars + len(line) + 1 > tail_budget:
                break
            tail_lines.insert(0, line)
            tail_chars += len(line) + 1

        skipped = total_lines - len(head_lines) - len(tail_lines)
        marker = f"\n... [truncated {skipped} lines] ...\n"

        return "\n".join(head_lines) + marker + "\n".join(tail_lines)
