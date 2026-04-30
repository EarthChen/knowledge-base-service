"""Integration test: run the stub pipeline end-to-end."""
import pytest


@pytest.mark.asyncio
async def test_stub_pipeline_runs_to_completion():
    from wiki.pipeline_graph import build_wiki_pipeline

    pipeline = build_wiki_pipeline()

    initial_state = {
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
        "heal_hints": {},
        "stage_timings": {},
        "llm_call_count": 0,
        "errors": [],
    }

    result = await pipeline.ainvoke(
        initial_state,
        config={"configurable": {"thread_id": "test-run-1"}},
    )

    assert result is not None
    assert result["business_id"] == "test-biz"
    assert isinstance(result.get("errors", []), list)
