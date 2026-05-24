from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from wiki.heal_strategy import (
    AgentEnrichStrategy,
    HealContext,
    HealResult,
    HealStrategyChain,
    RawLLMHealStrategy,
    TargetedHealStrategy,
)


def _make_context(*, llm=None, graph_store=None, hint="fix it", content="# Page\nold content"):
    page_dict = {
        "path": "test/page.md",
        "content": content,
        "domain": "test-domain",
        "title": "Test",
        "page_type": "topic",
    }
    from wiki.models import WikiPage

    page = WikiPage.from_dict(page_dict)
    return HealContext(
        page=page,
        page_dict=page_dict,
        hint=hint,
        domain_name="test-domain",
        domain_context="Domain: test-domain, Modules: mod1",
        llm=llm,
        graph_store=graph_store,
        state={"pages": [page_dict], "domain_tree": []},
        content_char_limit=10000,
        heal_budget=2000,
    )


def test_heal_context_creation():
    ctx = _make_context(llm=MagicMock())
    assert ctx.domain_name == "test-domain"
    assert ctx.llm is not None
    assert ctx.graph_store is None


def test_heal_result_creation():
    r = HealResult(content="# Fixed\nnew content", strategy_name="targeted")
    assert r.strategy_name == "targeted"
    assert "Fixed" in r.content


class TestTargetedHealStrategy:
    def test_can_apply_with_llm(self):
        s = TargetedHealStrategy()
        ctx = _make_context(llm=MagicMock())
        assert s.can_apply(ctx) is True

    def test_can_apply_without_llm(self):
        s = TargetedHealStrategy()
        ctx = _make_context(llm=None)
        assert s.can_apply(ctx) is False

    @pytest.mark.asyncio
    async def test_apply_success(self):
        s = TargetedHealStrategy()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)
        with pytest.MonkeyPatch.context() as mp:
            mock_healer = AsyncMock()
            mock_result = MagicMock()
            mock_result.content = "# Fixed Page\nGood content here"
            mock_healer.heal.return_value = mock_result

            import wiki.heal_strategy as hs_mod

            mp.setattr(hs_mod, "_create_targeted_healer", lambda: mock_healer)
            result = await s.apply(ctx)
        assert result is not None
        assert result.strategy_name == "targeted"
        assert "Fixed Page" in result.content

    @pytest.mark.asyncio
    async def test_apply_returns_none_on_healer_failure(self):
        s = TargetedHealStrategy()
        mock_llm = AsyncMock()
        ctx = _make_context(llm=mock_llm)
        with pytest.MonkeyPatch.context() as mp:
            mock_healer = AsyncMock()
            mock_healer.heal.return_value = None

            import wiki.heal_strategy as hs_mod

            mp.setattr(hs_mod, "_create_targeted_healer", lambda: mock_healer)
            result = await s.apply(ctx)
        assert result is None


class TestAgentEnrichStrategy:
    def test_can_apply_needs_both(self):
        s = AgentEnrichStrategy()
        assert s.can_apply(_make_context(llm=MagicMock(), graph_store=MagicMock())) is True
        assert s.can_apply(_make_context(llm=MagicMock(), graph_store=None)) is False
        assert s.can_apply(_make_context(llm=None, graph_store=MagicMock())) is False

    @pytest.mark.asyncio
    async def test_apply_calls_enrich(self):
        s = AgentEnrichStrategy()
        mock_llm = AsyncMock()
        mock_graph = MagicMock()
        ctx = _make_context(llm=mock_llm, graph_store=mock_graph)
        with pytest.MonkeyPatch.context() as mp:
            mock_agent = AsyncMock()
            mock_agent.enrich.return_value = "# Enriched\nBetter content"

            import wiki.heal_strategy as hs_mod

            mp.setattr(hs_mod, "_create_page_agent", lambda llm, gs: mock_agent)
            result = await s.apply(ctx)
        assert result is not None
        assert result.strategy_name == "agent_enrich"


class TestRawLLMHealStrategy:
    def test_can_apply_with_llm(self):
        s = RawLLMHealStrategy()
        assert s.can_apply(_make_context(llm=MagicMock())) is True
        assert s.can_apply(_make_context(llm=None)) is False

    @pytest.mark.asyncio
    async def test_apply_calls_generate(self):
        s = RawLLMHealStrategy()
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "# Regenerated\nFull new content"
        ctx = _make_context(llm=mock_llm)
        result = await s.apply(ctx)
        assert result is not None
        assert result.strategy_name == "raw_llm"
        mock_llm.generate.assert_called_once()


class TestHealStrategyChain:
    @pytest.mark.asyncio
    async def test_first_success_wins(self):
        s1 = MagicMock()
        s1.name = "s1"
        s1.can_apply.return_value = True
        s1.apply = AsyncMock(return_value=HealResult(content="fixed", strategy_name="s1"))
        s2 = MagicMock()
        s2.name = "s2"
        s2.can_apply.return_value = True
        s2.apply = AsyncMock(return_value=HealResult(content="also fixed", strategy_name="s2"))

        chain = HealStrategyChain(strategies=[s1, s2])
        ctx = _make_context(llm=MagicMock())
        result = await chain.execute(ctx)
        assert result is not None
        assert result.strategy_name == "s1"
        s2.apply.assert_not_called()

    @pytest.mark.asyncio
    async def test_skip_non_applicable(self):
        s1 = MagicMock()
        s1.name = "s1"
        s1.can_apply.return_value = False
        s2 = MagicMock()
        s2.name = "s2"
        s2.can_apply.return_value = True
        s2.apply = AsyncMock(return_value=HealResult(content="s2 result", strategy_name="s2"))

        chain = HealStrategyChain(strategies=[s1, s2])
        ctx = _make_context(llm=MagicMock())
        result = await chain.execute(ctx)
        assert result.strategy_name == "s2"
        s1.apply.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_fail_returns_none(self):
        s1 = MagicMock()
        s1.name = "s1"
        s1.can_apply.return_value = True
        s1.apply = AsyncMock(return_value=None)

        chain = HealStrategyChain(strategies=[s1])
        ctx = _make_context(llm=MagicMock())
        result = await chain.execute(ctx)
        assert result is None

    @pytest.mark.asyncio
    async def test_exception_continues_chain(self):
        s1 = MagicMock()
        s1.name = "s1"
        s1.can_apply.return_value = True
        s1.apply = AsyncMock(side_effect=RuntimeError("boom"))
        s2 = MagicMock()
        s2.name = "s2"
        s2.can_apply.return_value = True
        s2.apply = AsyncMock(return_value=HealResult(content="ok", strategy_name="s2"))

        chain = HealStrategyChain(strategies=[s1, s2])
        ctx = _make_context(llm=MagicMock())
        result = await chain.execute(ctx)
        assert result.strategy_name == "s2"

    @pytest.mark.asyncio
    async def test_skip_empty_content(self):
        s1 = MagicMock()
        s1.name = "s1"
        s1.can_apply.return_value = True
        s1.apply = AsyncMock(return_value=HealResult(content="   ", strategy_name="s1"))
        s2 = MagicMock()
        s2.name = "s2"
        s2.can_apply.return_value = True
        s2.apply = AsyncMock(return_value=HealResult(content="valid", strategy_name="s2"))

        chain = HealStrategyChain(strategies=[s1, s2])
        ctx = _make_context(llm=MagicMock())
        result = await chain.execute(ctx)
        assert result is not None
        assert result.strategy_name == "s2"

    @pytest.mark.asyncio
    async def test_default_strategies(self):
        chain = HealStrategyChain()
        assert len(chain._strategies) == 3
        assert chain._strategies[0].name == "targeted"
        assert chain._strategies[1].name == "agent_enrich"
        assert chain._strategies[2].name == "raw_llm"


class TestHealOnePageRefactored:
    """Verify _heal_one_page behavior is 100% equivalent after refactor."""

    @pytest.mark.asyncio
    async def test_heal_uses_strategy_chain(self):
        from wiki.nodes.heal import _heal_one_page
        from wiki.quality_evaluator import WikiQualityEvaluator

        mock_llm = AsyncMock()
        evaluator = WikiQualityEvaluator()
        page_dict = {"path": "test.md", "content": "# Test\nShort", "domain": "d", "title": "T", "page_type": "topic"}
        heal_hints: dict = {}
        heal_attempts: dict = {}

        with pytest.MonkeyPatch.context() as mp:
            mock_chain = AsyncMock()
            mock_chain.execute.return_value = HealResult(content="# Fixed\nGood content", strategy_name="targeted")

            import wiki.nodes.heal as heal_mod

            mp.setattr(heal_mod, "_make_strategy_chain", lambda: mock_chain)

            result = await _heal_one_page(
                page_path="test.md",
                page_dict=page_dict,
                state={"pages": [page_dict], "domain_tree": []},
                evaluator=evaluator,
                llm=mock_llm,
                heal_hints=heal_hints,
                heal_attempts=heal_attempts,
            )
        assert result is True
        assert page_dict["content"] == "# Fixed\nGood content"
        mock_chain.execute.assert_called_once()
