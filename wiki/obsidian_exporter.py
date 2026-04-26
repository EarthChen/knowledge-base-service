"""Obsidian vault export — preserves [[wikilinks]] and generates .obsidian/ config."""

from __future__ import annotations

import json
from typing import Any

from wiki.business_wiki_exporter import BusinessWikiExporter, ExportFile, ExportPlan


class ObsidianExporter(BusinessWikiExporter):
    """Exports business wiki as an Obsidian vault."""

    def __init__(self, store: Any | None) -> None:
        super().__init__(store=store, link_mode="obsidian")

    async def build_export_plan(
        self,
        business_id: str,
        view: str = "business_domain",
        min_tier: str = "standard",
    ) -> ExportPlan:
        plan = await super().build_export_plan(business_id, view, min_tier)
        plan.files.append(ExportFile(
            relative_path=".obsidian/app.json",
            content=self.generate_app_config(),
            is_index=True,
        ))
        plan.files.append(ExportFile(
            relative_path=".obsidian/graph.json",
            content=self.generate_graph_config(),
            is_index=True,
        ))
        return plan

    def generate_app_config(self) -> str:
        config = {
            "useMarkdownLinks": False,
            "newFileLocation": "folder",
            "attachmentFolderPath": "_attachments",
            "alwaysUpdateLinks": True,
        }
        return json.dumps(config, indent=2, ensure_ascii=False)

    def generate_graph_config(self) -> str:
        config = {
            "collapse-filter": True,
            "search": "",
            "showTags": False,
            "showAttachments": False,
            "hideUnresolved": False,
            "colorGroups": [],
        }
        return json.dumps(config, indent=2, ensure_ascii=False)
