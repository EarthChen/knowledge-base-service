"""Export business-level Wiki tree to file system directory structure."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from wiki.wikilink_converter import WikiLinkConverter


@dataclass
class ExportFile:
    """A single file to write during export."""
    relative_path: str
    content: str
    content_hash: str = ""
    is_index: bool = False


@dataclass
class ExportPlan:
    """Complete export plan for a business wiki."""
    business_id: str
    view: str = "business_domain"
    files: list[ExportFile] = field(default_factory=list)
    domain_names: list[str] = field(default_factory=list)
    total_pages: int = 0


class BusinessWikiExporter:
    """Exports business-level Wiki tree to directory structure.

    Maps WikiSpace → root, WikiSection → directory, WikiPage → .md file.
    Uses WikiLinkConverter to convert [[path]] markers in content.
    """

    def __init__(
        self,
        store: Any | None,
        link_mode: str = "markdown",
    ) -> None:
        self._store = store
        self._link_converter = WikiLinkConverter()
        self._link_mode = link_mode

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        """Build an export plan by querying the wiki tree and pages."""
        plan = ExportPlan(business_id=business_id, view=view)
        if self._store is None:
            return plan

        tree_result = await self._store.get_wiki_tree(
            business_id, view_type=view
        )
        tree_nodes = tree_result.data if tree_result else []
        if not tree_nodes:
            return plan

        pages = await self._store.get_wiki_pages_for_business(
            business_id, min_tier=min_tier
        )
        plan.total_pages = len(pages)

        domain_names: list[str] = []
        for node in tree_nodes:
            label = node.get("label", "")
            if label == "WikiSection" and node.get("depth", 0) == 1:
                domain_names.append(str(node.get("title", "")))
        plan.domain_names = domain_names

        page_files = self._map_pages_to_files(pages)
        plan.files.extend(page_files)

        readme = self.generate_readme(business_id, domain_names)
        plan.files.insert(0, ExportFile(
            relative_path="README.md",
            content=readme,
            is_index=True,
        ))

        domain_index = self.generate_domain_index(
            self._group_pages_by_domain(pages)
        )
        plan.files.append(ExportFile(
            relative_path="_index/by-domain.md",
            content=domain_index,
            is_index=True,
        ))

        return plan

    def _map_pages_to_files(self, pages: list[dict[str, Any]]) -> list[ExportFile]:
        """Map WikiPage records to ExportFile instances."""
        files: list[ExportFile] = []
        for page in pages:
            wiki_path = page.get("path", "").strip("/")
            if not wiki_path:
                continue
            page_type = page.get("page_type", "")
            content = page.get("content", "")

            if page_type == "domain_overview" or wiki_path.endswith("/_overview"):
                dir_part = wiki_path.rsplit("/_overview", 1)[0] if "/_overview" in wiki_path else wiki_path
                rel_path = f"{dir_part}/README.md"
            else:
                rel_path = f"{wiki_path}.md"

            converted = self._convert_content(content, wiki_path)
            files.append(ExportFile(
                relative_path=rel_path,
                content=converted,
                content_hash=page.get("content_hash", ""),
            ))
        return files

    def _convert_content(self, content: str, current_path: str) -> str:
        """Convert wikilinks in content based on link_mode."""
        if self._link_mode == "obsidian":
            return self._link_converter.to_obsidian(content)
        return self._link_converter.to_markdown(content, current_path=f"/{current_path}")

    def _group_pages_by_domain(self, pages: list[dict[str, Any]]) -> dict[str, list[str]]:
        """Group page filenames by their top-level domain directory."""
        groups: dict[str, list[str]] = {}
        for page in pages:
            path = page.get("path", "").strip("/")
            if not path:
                continue
            parts = path.split("/")
            domain = parts[0] if parts else "uncategorized"
            filename = parts[-1] + ".md"
            groups.setdefault(domain, []).append(filename)
        return groups

    def generate_readme(self, business_id: str, domain_names: list[str]) -> str:
        """Generate README.md content for the wiki root."""
        lines = [
            f"# {business_id} Knowledge Base",
            "",
            "## Business Domains",
            "",
        ]
        for name in domain_names:
            lines.append(f"- [{name}]({name}/README.md)")
        lines.extend(["", "---", "", "*Auto-generated by Knowledge Base Service.*", ""])
        return "\n".join(lines)

    def generate_domain_index(self, domains: dict[str, list[str]]) -> str:
        """Generate _index/by-domain.md with tree-shaped index."""
        lines = ["# Domain Index", ""]
        if not domains:
            lines.append("No domains found.")
            return "\n".join(lines)
        for domain, pages in sorted(domains.items()):
            lines.append(f"## {domain}")
            lines.append("")
            for page in sorted(pages):
                lines.append(f"- [{page}](../{domain}/{page})")
            lines.append("")
        return "\n".join(lines)

    async def export_to_directory(self, plan: ExportPlan, output_dir: str) -> list[str]:
        """Write all files in the export plan to output_dir."""
        created: list[str] = []
        out = Path(output_dir)
        for f in plan.files:
            full = out / f.relative_path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(f.content, encoding="utf-8")
            created.append(str(full))
        return created
