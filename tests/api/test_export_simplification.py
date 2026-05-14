"""Test export endpoint simplification."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


def test_export_body_rejects_zip_format() -> None:
    """Standalone 'zip' format should no longer be accepted."""
    from api.models.wiki_models import BusinessWikiExportBody

    with pytest.raises(ValidationError):
        BusinessWikiExportBody(
            business_id="default",
            format="zip",
        )


def test_export_body_accepts_markdown_without_view_tier() -> None:
    """Markdown format should work without view_type or min_tier."""
    from api.models.wiki_models import BusinessWikiExportBody

    body = BusinessWikiExportBody(
        business_id="default",
        format="markdown",
    )
    assert body.format == "markdown"
    assert not hasattr(body, "view_type")
    assert not hasattr(body, "min_tier")


def test_export_body_accepts_all_valid_formats() -> None:
    """All valid formats should be accepted."""
    from api.models.wiki_models import BusinessWikiExportBody

    for fmt in ("markdown", "obsidian", "mkdocs", "git"):
        body = BusinessWikiExportBody(business_id="default", format=fmt)
        assert body.format == fmt
