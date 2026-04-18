"""Export wiki pages to JSON and Markdown with cross-reference linking."""

from __future__ import annotations

import os
import re
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from wiki.models import WikiPage, WikiStructure


def _relative_markdown_path(from_page: str, to_page: str) -> str:
    """Return POSIX relative path from one wiki file to another."""
    from_dir = os.path.dirname(from_page.replace("\\", "/"))
    to_norm = to_page.replace("\\", "/")
    rel = os.path.relpath(to_norm, start=from_dir or ".")
    return rel.replace(os.sep, "/")


def _slug_fqn_path(base_path: str, fqn: str) -> str:
    """Derive a unique wiki path from an FQN when short paths collide."""
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", fqn.strip())
    parent = Path(base_path).parent.as_posix()
    return f"{parent}/{safe}.md" if parent != "." else f"{safe}.md"


class WikiExporter:
    """Serializes wiki pages to JSON / Markdown with optional cross-reference links."""

    def export_json(self, pages: list[WikiPage], structure: WikiStructure) -> dict:
        """Return a JSON-serializable bundle: pages, structure tree, and export stats."""
        return {
            "pages": [p.to_dict() for p in pages],
            "structure": structure.to_dict(),
            "stats": {
                "total_pages": len(pages),
                "generation_time_ms": 0,
            },
        }

    def export_markdown_single(self, page: WikiPage) -> str:
        """Render a single page as Markdown: title, source links, body, methods, diagrams."""
        parts: list[str] = [f"# {page.title}", ""]

        if page.source_locations:
            parts.append("## Source")
            parts.append("")
            for loc in page.source_locations:
                parts.append(f"- {loc.to_source_link()}")
            parts.append("")

        parts.append(page.content.rstrip())
        parts.append("")

        if page.method_locations:
            parts.append("## Methods")
            parts.append("")
            for loc in page.method_locations:
                label = loc.fqn.rsplit(".", 1)[-1] if loc.fqn else "method"
                parts.append(f"- `{label}` — {loc.to_source_link()}")
            parts.append("")

        for diagram in page.diagrams:
            if diagram.title:
                parts.append(f"## {diagram.title}")
                parts.append("")
            parts.append(f"```mermaid\n{diagram.content}\n```")
            parts.append("")

        return "\n".join(parts).rstrip() + "\n"

    def export_markdown_fileset(
        self,
        pages: list[WikiPage],
        structure: WikiStructure,
        output_dir: str,
    ) -> list[str]:
        """Write Markdown files under ``output_dir``, preserving relative paths with deduplication."""
        resolved_paths = self._resolve_unique_paths(pages)
        canonical_map = self.build_entity_page_map(pages, resolved_paths)
        created: list[str] = []
        out_root = Path(output_dir)

        for page in pages:
            rel_path = resolved_paths[id(page)]
            full_path = out_root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)

            rel_entity_map = {
                name: _relative_markdown_path(rel_path, target)
                for name, target in canonical_map.items()
            }
            linked_content = self.auto_link_cross_references(page.content, rel_entity_map)
            page_out = replace(page, content=linked_content)
            full_path.write_text(self.export_markdown_single(page_out), encoding="utf-8")
            created.append(str(full_path.resolve()))

        return sorted(created)

    @staticmethod
    def build_entity_page_map(
        pages: list[WikiPage],
        path_by_page: dict[int, str] | None = None,
    ) -> dict[str, str]:
        """Build entity name → wiki path map from pages.

        Uses FQN keys when several pages share the same short title (Spec L5).
        Callers align page titles with :class:`WikiStructure` nodes in the pipeline.
        """
        resolved: dict[int, str]
        if path_by_page is not None:
            resolved = path_by_page
        else:
            exporter = WikiExporter()
            resolved = exporter._resolve_unique_paths(pages)

        groups: dict[str, list[WikiPage]] = defaultdict(list)
        for p in pages:
            groups[p.title].append(p)

        index: dict[str, str] = {}

        for title, plist in groups.items():
            if len(plist) == 1:
                p = plist[0]
                index[title] = resolved[id(p)]
                continue

            for p in plist:
                path = resolved[id(p)]
                fqn = p.source_locations[0].fqn if p.source_locations else title
                index[fqn] = path
                short = fqn.rsplit(".", 1)[-1]
                if short not in index:
                    index[short] = path

        return index

    @staticmethod
    def auto_link_cross_references(content: str, entity_page_map: dict[str, str]) -> str:
        """Wrap entity mentions in Markdown links using the given map (longest match first)."""
        if not entity_page_map:
            return content

        keys = sorted(entity_page_map.keys(), key=len, reverse=True)
        result = content

        for key in keys:
            href = entity_page_map[key]
            escaped = re.escape(key)
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                pattern = rf"(?<!\[)\b{escaped}\b"
            else:
                pattern = rf"(?<!\[){escaped}(?!\w)"

            def repl(m: re.Match[str]) -> str:
                return f"[{m.group(0)}]({href})"

            result = re.sub(pattern, repl, result)

        return result

    def _resolve_unique_paths(self, pages: list[WikiPage]) -> dict[int, str]:
        """Ensure unique output paths; duplicate basenames get FQN-based paths (Spec L5)."""
        path_groups: dict[str, list[WikiPage]] = defaultdict(list)
        for p in pages:
            path_groups[p.path].append(p)

        resolved: dict[int, str] = {}

        for path, plist in path_groups.items():
            if len(plist) == 1:
                resolved[id(plist[0])] = path
                continue
            used: set[str] = set()
            for p in plist:
                fqn = p.source_locations[0].fqn if p.source_locations else p.title
                candidate = _slug_fqn_path(path, fqn)
                # resolve secondary collisions
                candidate_final = candidate
                n = 2
                while candidate_final in used:
                    stem = Path(candidate).stem
                    parent = Path(candidate).parent.as_posix()
                    candidate_final = f"{parent}/{stem}__{n}.md" if parent != "." else f"{stem}__{n}.md"
                    n += 1
                used.add(candidate_final)
                resolved[id(p)] = candidate_final

        return resolved
