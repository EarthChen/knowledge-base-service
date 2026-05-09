# tests/wiki/test_cleanup_all_paths.py
from wiki.context_gap import cleanup_context_gaps


def test_cleanup_after_heal_content():
    """Simulate heal writing content with CONTEXT_GAP that needs cleanup."""
    page = {"content": "healed <!-- CONTEXT_GAP: missing --> text"}
    page["content"] = cleanup_context_gaps(page["content"])
    assert "<!-- CONTEXT_GAP" not in page["content"]
    assert page["content"].strip() == "healed text"


def test_cleanup_after_aggregate_content():
    """Simulate aggregate writing content with CONTEXT_GAP."""
    content = "overview <!-- CONTEXT_GAP：中文标记 --> rest"
    cleaned = cleanup_context_gaps(content)
    assert "<!-- CONTEXT_GAP" not in cleaned
