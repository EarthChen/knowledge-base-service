"""Generation-stage wiki export bundling (facade over :class:`WikiExporter`)."""

from __future__ import annotations

from typing import Any

from wiki.exporter import WikiExporter
from wiki.models import WikiPage, WikiStructure


class WikiExportService:
    """Facades :class:`WikiExporter` for pipeline responses (markdown single-page vs JSON bundle)."""

    def __init__(self, exporter: WikiExporter | None = None) -> None:
        self._exporter = exporter or WikiExporter()

    def bundle_generation_result(
        self,
        pages: list[WikiPage],
        structure: WikiStructure,
        *,
        export_format: str,
        degraded: bool,
    ) -> dict[str, Any]:
        """Match legacy ``WikiService.generate`` / streaming completion bundle shape."""
        if export_format == "markdown" and len(pages) == 1:
            return {
                "content": self._exporter.export_markdown_single(pages[0]),
                "format": "markdown",
                "degraded": degraded,
            }
        bundle = self._exporter.export_json(pages, structure)
        bundle["degraded"] = degraded
        return bundle
