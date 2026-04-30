"""Tests for configurable checkpoint backend in pipeline builder."""
import pytest


def test_build_pipeline_default_memory():
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline()
    assert graph is not None
    assert hasattr(graph, "ainvoke")


def test_build_pipeline_memory_backend():
    from langgraph.checkpoint.memory import MemorySaver
    from wiki.pipeline_graph import build_wiki_pipeline
    graph = build_wiki_pipeline(checkpointer=MemorySaver())
    assert graph is not None


@pytest.mark.asyncio
async def test_build_pipeline_sqlite_backend(tmp_path):
    from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    from wiki.pipeline_graph import build_wiki_pipeline

    db_path = str(tmp_path / "test_checkpoints.db")

    async with AsyncSqliteSaver.from_conn_string(db_path) as saver:
        graph = build_wiki_pipeline(checkpointer=saver)
        assert graph is not None

        result = await graph.ainvoke(
            {
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
            },
            config={"configurable": {"thread_id": "test-sqlite-1"}},
        )
        assert result["business_id"] == "test-biz"
