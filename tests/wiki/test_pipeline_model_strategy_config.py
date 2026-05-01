from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wiki.pipeline_orchestrator import run_langgraph_pipeline


class _FakeStrategy:
    """Dummy model strategy for config passthrough verification."""
    pass


@pytest.mark.asyncio
async def test_model_strategy_passed_in_configurable() -> None:
    captured: dict = {}

    async def fake_ainvoke(state, config=None):
        captured["config"] = config
        return {
            "domain_mapping": {},
            "domain_tree": [],
            "pages": [],
            "resolved_links": {},
            "entity_roles": {},
            "errors": [],
        }

    fake_pipeline = AsyncMock()
    fake_pipeline.ainvoke = fake_ainvoke

    with patch("wiki.pipeline_orchestrator.build_wiki_pipeline", return_value=fake_pipeline):
        await run_langgraph_pipeline(
            business_id="biz-1",
            repositories=["repo-a"],
            all_modules={"repo-a": []},
            llm="fake-llm",
            model_strategy=_FakeStrategy(),
        )

    cfg = captured["config"]["configurable"]
    assert "model_strategy" in cfg
    assert isinstance(cfg["model_strategy"], _FakeStrategy)


@pytest.mark.asyncio
async def test_model_strategy_absent_when_none() -> None:
    captured: dict = {}

    async def fake_ainvoke(state, config=None):
        captured["config"] = config
        return {
            "domain_mapping": {},
            "domain_tree": [],
            "pages": [],
            "resolved_links": {},
            "entity_roles": {},
            "errors": [],
        }

    fake_pipeline = AsyncMock()
    fake_pipeline.ainvoke = fake_ainvoke

    with patch("wiki.pipeline_orchestrator.build_wiki_pipeline", return_value=fake_pipeline):
        await run_langgraph_pipeline(
            business_id="biz-1",
            repositories=["repo-a"],
            all_modules={"repo-a": []},
            llm="fake-llm",
        )

    cfg = captured["config"]["configurable"]
    assert "model_strategy" not in cfg
