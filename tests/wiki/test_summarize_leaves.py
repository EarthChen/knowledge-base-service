import pytest
from wiki.pipeline_nodes import summarize_leaves_node


def _make_page(path, content, page_type="topic", executive_summary=None):
    metadata = {}
    if executive_summary:
        metadata["executive_summary"] = executive_summary
    return {
        "path": path,
        "title": path.split("/")[-1],
        "content": content,
        "page_type": page_type,
        "metadata": metadata,
    }


@pytest.mark.asyncio
async def test_summarize_from_executive_summary():
    state = {
        "pages": {
            "wiki/orders": _make_page(
                "wiki/orders", "Long content...",
                executive_summary="Order domain handles e-commerce order lifecycle."
            ),
        },
        "domain_tree": [{"name": "orders", "modules": ["OrderService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert "orders" in summaries
    assert summaries["orders"]["summary_text"] == "Order domain handles e-commerce order lifecycle."
    assert summaries["orders"]["source"] == "llm"


@pytest.mark.asyncio
async def test_summarize_fallback_first_paragraph():
    content = "# Order Domain\n\nThis domain manages the complete order lifecycle including creation and fulfillment.\n\n## Details\n\nMore text here."
    state = {
        "pages": {
            "wiki/orders": _make_page("wiki/orders", content),
        },
        "domain_tree": [{"name": "orders", "modules": ["OrderService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert "orders" in summaries
    assert "order lifecycle" in summaries["orders"]["summary_text"].lower()
    assert summaries["orders"]["source"] == "rule_extracted"


@pytest.mark.asyncio
async def test_summarize_fallback_overview_section():
    content = "# Payment\n\nIntro paragraph.\n\n## 业务概述\n\nPayment domain handles all payment processing including refunds.\n\n## Architecture\n\nDetails..."
    state = {
        "pages": {
            "wiki/payment": _make_page("wiki/payment", content),
        },
        "domain_tree": [{"name": "payment", "modules": ["PaymentService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert "payment" in summaries
    assert "payment" in summaries["payment"]["summary_text"].lower()


@pytest.mark.asyncio
async def test_summarize_fallback_truncate():
    content = "A" * 500
    state = {
        "pages": {
            "wiki/big": _make_page("wiki/big", content),
        },
        "domain_tree": [{"name": "big", "modules": ["BigService"], "children": []}],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert len(summaries["big"]["summary_text"]) <= 300


@pytest.mark.asyncio
async def test_summarize_no_pages():
    state = {
        "pages": {},
        "domain_tree": [{"name": "empty", "modules": [], "children": []}],
    }
    result = await summarize_leaves_node(state)
    assert result["leaf_summaries"] == {}


@pytest.mark.asyncio
async def test_summarize_multiple_domains():
    state = {
        "pages": {
            "wiki/orders": _make_page("wiki/orders", "Order content",
                                       executive_summary="Order summary"),
            "wiki/users": _make_page("wiki/users", "User content",
                                      executive_summary="User summary"),
        },
        "domain_tree": [
            {"name": "orders", "modules": ["OrderService"], "children": []},
            {"name": "users", "modules": ["UserService"], "children": []},
        ],
    }
    result = await summarize_leaves_node(state)
    summaries = result["leaf_summaries"]
    assert len(summaries) == 2
    assert "orders" in summaries
    assert "users" in summaries
