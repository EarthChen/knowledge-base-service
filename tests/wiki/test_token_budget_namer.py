"""Tests for rank-based token budget context pruning in graph domain namer."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from wiki.graph_domain_namer import GraphDomainNamer, budget_module_details


def _module(name: str, *, path: str = "", summary: str = "") -> dict[str, str]:
    return {"name": name, "path": path, "summary": summary}


class TestBudgetModuleDetails:
    def test_budget_all_modules_below_limit(self) -> None:
        """Small list within max_lines returns full detail for every module."""
        infos = [
            _module("Alpha", path="a/Alpha.java", summary="Alpha service"),
            _module("Beta", path="b/Beta.java", summary="Beta handler"),
        ]
        lines = budget_module_details(infos, max_lines=40, full_ratio=1.0, names_ratio=0.0)
        assert len(lines) == 2
        assert "Alpha" in lines[0]
        assert "a/Alpha.java" in lines[0]
        assert "Alpha service" in lines[0]
        assert "Beta" in lines[1]
        assert "b/Beta.java" in lines[1]

    def test_budget_prunes_large_list(self) -> None:
        """Large list respects max_lines with tiered pruning."""
        infos = [_module(f"Mod{i}", path=f"p/Mod{i}.java", summary=f"summary {i}") for i in range(20)]
        lines = budget_module_details(infos, max_lines=10)
        assert len(lines) <= 11  # up to 10 detail lines + optional omitted summary
        assert len(lines) >= 10
        full_lines = [line for line in lines if "(" in line and ": summary" in line]
        assert len(full_lines) == 6  # top 30% of 20

    def test_budget_rank_ordering(self) -> None:
        """High-rank modules get full detail; low-rank modules are omitted."""
        infos = [
            _module("LowRank", path="low/L.java", summary="low importance"),
            _module("HighRank", path="high/H.java", summary="high importance"),
            _module("MidRank", path="mid/M.java", summary="mid importance"),
            _module("AlsoLow", path="also/A.java", summary="also low"),
        ]
        ranks = {"HighRank": 1.0, "MidRank": 0.5, "LowRank": 0.1, "AlsoLow": 0.05}
        lines = budget_module_details(
            infos,
            module_ranks=ranks,
            max_lines=40,
            full_ratio=0.25,
            names_ratio=0.25,
        )
        joined = "\n".join(lines)
        assert "HighRank" in joined
        assert "high/H.java" in joined
        assert "high importance" in joined
        assert "AlsoLow" not in joined
        assert "LowRank" not in joined

    def test_budget_names_only_tier(self) -> None:
        """Mid-rank modules appear as name-only lines without path or summary."""
        infos = [
            _module("Top", path="t/T.java", summary="top module"),
            _module("Middle", path="m/M.java", summary="middle module"),
            _module("Bottom", path="b/B.java", summary="bottom module"),
            _module("AlsoLow", path="a/A.java", summary="also low"),
        ]
        ranks = {"Top": 1.0, "Middle": 0.5, "Bottom": 0.1, "AlsoLow": 0.05}
        lines = budget_module_details(
            infos,
            module_ranks=ranks,
            max_lines=40,
            full_ratio=0.25,
            names_ratio=0.25,
        )
        assert any("Top" in line and "t/T.java" in line for line in lines)
        assert "- Middle" in lines
        assert not any("m/M.java" in line for line in lines)
        assert "Bottom" not in "\n".join(lines)
        assert "AlsoLow" not in "\n".join(lines)

    def test_budget_without_ranks(self) -> None:
        """Without ranks, original order is preserved and max_lines is enforced."""
        infos = [_module(f"Mod{i}", path=f"p/{i}.java") for i in range(15)]
        lines = budget_module_details(infos, max_lines=5)
        assert len(lines) == 6  # 5 detail lines + omitted summary
        assert lines[0].startswith("- Mod0")
        assert "Mod1" in lines[1]
        assert any("... and" in line for line in lines)

    def test_budget_shows_omitted_count(self) -> None:
        """When modules are omitted, a summary line is appended."""
        infos = [_module(f"Mod{i}") for i in range(10)]
        lines = budget_module_details(
            infos,
            max_lines=40,
            full_ratio=0.2,
            names_ratio=0.2,
        )
        assert any("... and 6 more modules" in line for line in lines)

    def test_budget_empty_list(self) -> None:
        assert budget_module_details([]) == []


class TestNamerUsesBudget:
    @pytest.mark.asyncio
    async def test_namer_uses_budget(self) -> None:
        """name_community uses budget_module_details for module_infos."""
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value='{"slug": "test", "display_name": "测试", "description": ""}',
        )
        namer = GraphDomainNamer(llm)
        infos = [_module("FooService", path="foo/Foo.java", summary="foo svc")]

        with patch(
            "wiki.graph_domain_namer.budget_module_details",
            return_value=["- FooService (foo/Foo.java): foo svc"],
        ) as mock_budget:
            await namer.name_community(module_infos=infos, module_ranks={"FooService": 1.0})

        mock_budget.assert_called_once_with(
            infos,
            module_ranks={"FooService": 1.0},
            max_lines=40,
        )

    @pytest.mark.asyncio
    async def test_namer_prompt_contains_budgeted_lines(self) -> None:
        """Prompt includes output from budget_module_details."""
        llm = AsyncMock()
        llm.generate = AsyncMock(
            return_value='{"slug": "test", "display_name": "测试", "description": ""}',
        )
        namer = GraphDomainNamer(llm)
        infos = [_module("Alpha", path="a/A.java", summary="alpha")]

        await namer.name_community(module_infos=infos)

        prompt = llm.generate.call_args[0][0]
        assert "Alpha" in prompt
        assert "a/A.java" in prompt
