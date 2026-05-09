from wiki.pipeline_state import WikiPipelineState


def test_pipeline_state_has_module_tree_field():
    """Verify the TypedDict accepts the new graph-decomposition fields."""
    state: WikiPipelineState = {
        "business_id": "test",
        "repositories": [],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
        "entity_roles": {},
        "role_stats": {},
        "is_incremental": False,
        "reorg_type": "",
        "affected_domains": [],
        "review_status": {},
        "review_notes": {},
        "generated_topic_pages": [],
        "overview_pages": [],
        "system_overview_uid": "",
        "resolved_links": {},
        # New fields:
        "module_tree": [],
        "canonical_keys": {},
        "domain_cache": {},
    }
    assert "module_tree" in state
    assert "canonical_keys" in state
    assert "domain_cache" in state
    assert isinstance(state["module_tree"], list)
    assert isinstance(state["canonical_keys"], dict)
    assert isinstance(state["domain_cache"], dict)
