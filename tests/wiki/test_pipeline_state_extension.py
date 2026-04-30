from __future__ import annotations

from wiki.pipeline_state import WikiPipelineState


def test_new_fields_exist_in_typeddict():
    """Verify WikiPipelineState has the new fields from the proposal."""
    hints = WikiPipelineState.__annotations__
    assert "entity_roles" in hints
    assert "role_stats" in hints
    assert "is_incremental" in hints
    assert "reorg_type" in hints
    assert "affected_domains" in hints
    assert "review_status" in hints
    assert "review_notes" in hints


def test_phase3_phase4_fields_exist():
    """Sprint 2 fields for content gen and synthesis."""
    hints = WikiPipelineState.__annotations__
    assert "generated_topic_pages" in hints
    assert "overview_pages" in hints
    assert "system_overview_uid" in hints
    assert "resolved_links" in hints
