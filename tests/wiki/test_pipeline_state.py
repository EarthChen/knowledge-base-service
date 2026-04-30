"""Tests for WikiPipelineState type definition."""


def test_pipeline_state_is_typed_dict():
    from wiki.pipeline_state import WikiPipelineState
    import typing
    assert hasattr(WikiPipelineState, "__annotations__")
    annotations = typing.get_type_hints(WikiPipelineState)
    assert "business_id" in annotations
    assert "repositories" in annotations
    assert "modules" in annotations
    assert "domain_mapping" in annotations
    assert "pages" in annotations
    assert "quality_scores" in annotations
    assert "stage_timings" in annotations
    assert "errors" in annotations


def test_pipeline_state_can_be_instantiated():
    from wiki.pipeline_state import WikiPipelineState
    state: WikiPipelineState = {
        "business_id": "test-biz",
        "repositories": ["repo-a"],
        "config": {},
        "modules": {},
        "domain_mapping": {},
        "domain_tree": None,
        "topic_structure": None,
        "pages": [],
        "quality_scores": {},
        "pages_to_heal": [],
        "heal_attempts": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }
    assert state["business_id"] == "test-biz"
    assert state["pages"] == []
