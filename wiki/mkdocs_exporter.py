"""MkDocs export — generates mkdocs.yml with navigation config."""

from __future__ import annotations

from typing import Any

from wiki.business_wiki_exporter import BusinessWikiExporter, ExportFile, ExportPlan


def _yaml_quote(value: str) -> str:
    """Quote a YAML scalar if it contains metacharacters."""
    if any(ch in value for ch in (":", "#", "'", '"', "\n", "{", "}", "[", "]")):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return value


class MkDocsExporter(BusinessWikiExporter):
    """Exports business wiki in MkDocs-ready format."""

    def __init__(self, store: Any | None) -> None:
        super().__init__(store=store, link_mode="markdown")

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        plan = await super().build_export_plan(business_id, view, min_tier)
        yml = self.generate_mkdocs_yml(business_id, plan.domain_names)

        docs_files: list[ExportFile] = []
        if not plan.files:
            docs_files.append(ExportFile(
                relative_path="docs/README.md",
                content=f"# {business_id}\n\nNo wiki pages generated yet.\n",
                is_index=True,
            ))
        else:
            for f in plan.files:
                docs_files.append(ExportFile(
                    relative_path=f"docs/{f.relative_path}",
                    content=f.content,
                    content_hash=f.content_hash,
                    is_index=f.is_index,
                ))
        docs_files.append(ExportFile(
            relative_path="mkdocs.yml",
            content=yml,
            is_index=True,
        ))
        plan.files = docs_files
        return plan

    def generate_mkdocs_yml(self, site_name: str, domain_names: list[str]) -> str:
        safe_name = _yaml_quote(site_name)
        nav_items = []
        for name in domain_names:
            safe_label = _yaml_quote(name)
            nav_items.append(f"    - {safe_label}: {name}/README.md")
        nav_section = "\n".join(nav_items) if nav_items else "    - Home: README.md"

        return (
            f"site_name: {safe_name}\n"
            "theme:\n"
            "  name: material\n"
            "  features:\n"
            "    - navigation.tabs\n"
            "    - navigation.sections\n"
            "    - search.suggest\n"
            "markdown_extensions:\n"
            "  - pymdownx.superfences:\n"
            "      custom_fences:\n"
            "        - name: mermaid\n"
            "          class: mermaid\n"
            "          format: !!python/name:pymdownx.superfences.fence_code_format\n"
            "  - pymdownx.tabbed:\n"
            "      alternate_style: true\n"
            "nav:\n"
            "  - Home: README.md\n"
            "  - Domains:\n"
            f"{nav_section}\n"
        )
