"""Cap removal and anchor propagation for domain classification v2."""

from __future__ import annotations

import inspect
from unittest.mock import AsyncMock, patch

import pytest

from store.schema import GraphNode, NodeLabel
from wiki.business_domain_planner import BusinessDomainPlanner
from wiki.cross_repo_domain_planner import CrossRepoBusinessDomainPlanner
from wiki.entity_role_classifier import WikiEntityRole


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

    def test_no_hard_cap_constant_in_classify_node(self) -> None:
        """classify_domains_node must not define a small fixed module ceiling."""
        from wiki.nodes.classify import classify_domains_node

        source = inspect.getsource(classify_domains_node)
        assert "_MAX_MODULES_FOR_CLASSIFICATION" not in source
        assert "classify_domains_capped" not in source

    @pytest.mark.asyncio
    async def test_classify_domains_passes_all_modules_over_200(self) -> None:
        """More than 200 eligible modules should all reach CrossRepoBusinessDomainPlanner."""
        from wiki.nodes.classify import classify_domains_node

        n = 250
        modules_list: list[dict] = []
        entity_roles: dict[str, WikiEntityRole] = {}
        for i in range(n):
            uid = f"Module::Svc{i}:0"
            entity_roles[uid] = WikiEntityRole.HAS_BUSINESS_LOGIC
            modules_list.append({
                "uid": uid,
                "label": "Module",
                "properties": {
                    "name": f"Svc{i}",
                    "path": f"/interfaces/Svc{i}.java",
                },
            })
        state: dict = {
            "business_id": "biz-cap",
            "entity_roles": entity_roles,
            "modules": {"repo1": modules_list},
            "is_incremental": False,
        }
        config = {"configurable": {"llm": AsyncMock(spec=["generate"])}}

        with patch("wiki.nodes.classify.CrossRepoBusinessDomainPlanner") as mock_cls:
            instance = mock_cls.return_value
            instance.classify = AsyncMock(return_value={})
            await classify_domains_node(state, config)
            planner_modules = instance.classify.call_args[0][1]
            assert sum(len(v) for v in planner_modules.values()) == n

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
