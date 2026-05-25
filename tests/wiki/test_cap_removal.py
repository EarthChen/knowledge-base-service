"""Cap removal and anchor propagation for domain classification v2."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner


def _make_module(name: str) -> GraphNode:
    return GraphNode(
        uid=f"Module:test:{name}",
        label=NodeLabel.MODULE,
        properties={
            "name": name,
            "path": f"/interfaces/{name}.java",
        },
    )


class TestCapRemoval:
    """200-module cap removed; anchors reach each per-repo sub-batch."""

    @pytest.mark.asyncio
    async def test_multi_batch_passes_anchor_context_to_business_planner(self) -> None:
        """Per-repo BusinessDomainPlanner.classify must receive anchor_context on multi-batch path."""
        llm = AsyncMock(spec=["generate"])
        anchor = "Existing domains (prefer reusing these):\n  - gifts (Gifts)"

        planner_kwargs: list[dict] = []

        async def capture_per_repo(repo_id: str, modules: list[GraphNode], **kwargs: object) -> dict[str, list[str]]:  # noqa: ARG001
            planner_kwargs.append(dict(kwargs))
            return {"D": [str(m.properties.get("name")) for m in modules if m.properties.get("name")]}

        with patch("wiki.cross_repo_domain_planner.BusinessDomainPlanner") as mock_bp:
            mock_bp.return_value.classify = AsyncMock(side_effect=capture_per_repo)
            llm.generate = AsyncMock(
                return_value='{"Unified": {"r1": "D", "r2": "D"}}',
            )
            planner = CrossRepoBusinessDomainPlanner(llm, batch_threshold=2)
            all_modules = {
                "r1": [_make_module("a1"), _make_module("a2")],
                "r2": [_make_module("b1")],
            }
            await planner.classify("biz-mb", all_modules, anchor_context=anchor)

        assert len(planner_kwargs) >= 2
        assert all(k.get("anchor_context") == anchor for k in planner_kwargs)

    @pytest.mark.asyncio
    async def test_business_planner_prompt_includes_anchor_per_sub_batch(self) -> None:
        """Sub-batches in BusinessDomainPlanner must include anchor text in the LLM prompt."""
        prompts: list[str] = []

        async def capture(prompt: str, system: str = "") -> str:  # noqa: ARG001
            prompts.append(prompt)
            return '{"Dom": ["m0"]}'

        llm = AsyncMock(spec=["generate"])
        llm.generate = AsyncMock(side_effect=capture)
        planner = BusinessDomainPlanner(llm)
        modules = [_make_module(f"m{i}") for i in range(5)]
        await planner.classify(
            "repo-sub",
            modules,
            sub_batch_size=2,
            max_concurrency=2,
            anchor_context="ANCHOR_HINT_XYZ",
        )
        assert prompts
        assert all("ANCHOR_HINT_XYZ" in p for p in prompts)
