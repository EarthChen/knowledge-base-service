import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.mark.asyncio
async def test_initial_state_has_v2_fields():
    """Verify that run_langgraph_pipeline passes module_tree/canonical_keys/domain_cache to the pipeline."""
    from wiki.pipeline_orchestrator import run_langgraph_pipeline
    from store.schema import GraphNode

    captured_state = {}

    async def mock_ainvoke(state, config=None):
        captured_state.update(state)
        return {
            "domain_mapping": {},
            "domain_tree": None,
            "pages": [],
            "resolved_links": {},
            "entity_roles": {},
            "errors": [],
            "module_tree": [],
            "canonical_keys": {},
            "domain_cache": {},
        }

    with patch("wiki.pipeline_orchestrator.build_wiki_pipeline") as mock_build:
        mock_pipeline = MagicMock()
        mock_pipeline.ainvoke = mock_ainvoke
        mock_build.return_value = mock_pipeline

        await run_langgraph_pipeline(
            business_id="test",
            repositories=["repo1"],
            all_modules={"repo1": []},
            llm=AsyncMock(),
        )

    assert "module_tree" in captured_state
    assert "canonical_keys" in captured_state
    assert "domain_cache" in captured_state
    assert captured_state["module_tree"] == []
    assert captured_state["canonical_keys"] == {}
    assert captured_state["domain_cache"] == {}
