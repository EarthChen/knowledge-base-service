from __future__ import annotations

import pytest

from wiki.nodes.links import create_links_node


@pytest.mark.asyncio
async def test_create_links_resolves_composite_domain_title_wikilink() -> None:
    """[[domain/title]] resolves when business_domain and title are set on the target page."""
    topic_path = "/__domains__/billing/topics/Invoicing.md"
    state = {
        "pages": [
            {
                "path": "/__domains__/billing/_overview",
                "title": "Billing",
                "content": "See [[billing/Invoicing]] for details.",
                "page_type": "domain_overview",
                "business_domain": "billing",
            },
            {
                "path": topic_path,
                "title": "Invoicing",
                "content": "# Invoicing",
                "page_type": "topic",
                "business_domain": "billing",
            },
        ],
        "domain_tree": [],
    }
    result = await create_links_node(state)
    overview_path = "/__domains__/billing/_overview"
    links = result["resolved_links"][overview_path]
    assert len(links) == 1
    assert links[0]["from_text"] == "billing/Invoicing"
    assert links[0]["target_path"] == topic_path


@pytest.mark.asyncio
async def test_create_links_still_resolves_plain_title_wikilink() -> None:
    topic_path = "/__domains__/billing/topics/Invoicing.md"
    state = {
        "pages": [
            {
                "path": "/__domains__/billing/_overview",
                "title": "Billing",
                "content": "See [[Invoicing]] for details.",
                "page_type": "domain_overview",
            },
            {
                "path": topic_path,
                "title": "Invoicing",
                "content": "# Invoicing",
                "page_type": "topic",
            },
        ],
        "domain_tree": [],
    }
    result = await create_links_node(state)
    links = result["resolved_links"]["/__domains__/billing/_overview"]
    assert links[0]["target_path"] == topic_path
