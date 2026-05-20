"""Tests for GenericAgent output_type structured output (Layer 1b)."""
from __future__ import annotations
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from pydantic import BaseModel


class SimpleOutput(BaseModel):
    title: str
    summary: str


class TestOutputType:
    @pytest.mark.asyncio
    async def test_output_type_none_uses_text_generation(self):
        """When output_type is None, run_generation uses plain text."""
        from wiki.agents.base_agent import GenericAgent
        from tests.wiki.agents.test_base_agent import ConcreteAgent

        mock_llm = MagicMock()
        mock_llm.generate = AsyncMock(return_value="plain text output")

        agent = ConcreteAgent(mock_llm)
        assert agent.output_type is None

        result = await agent.run_generation("system", "user")
        assert result == "plain text output"
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_type_set_uses_structured(self):
        """When output_type is set, run_generation tries complete_json first."""
        from tests.wiki.agents.test_base_agent import ConcreteAgent

        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={"title": "T", "summary": "S"})

        agent = ConcreteAgent(mock_llm)
        agent.output_type = SimpleOutput

        result = await agent.run_generation("system", "user")
        # Should contain the structured data rendered as JSON
        parsed = json.loads(result)
        assert parsed["title"] == "T"
        assert parsed["summary"] == "S"
        mock_llm.complete_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_output_type_fallback_on_failure(self):
        """When complete_json fails, falls back to text generation."""
        from tests.wiki.agents.test_base_agent import ConcreteAgent

        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(side_effect=RuntimeError("parse error"))
        mock_llm.generate = AsyncMock(return_value="fallback text")

        agent = ConcreteAgent(mock_llm)
        agent.output_type = SimpleOutput

        result = await agent.run_generation("system", "user")
        assert result == "fallback text"
        mock_llm.generate.assert_called_once()

    @pytest.mark.asyncio
    async def test_render_output_override(self):
        """Subclasses can override _render_output for custom rendering."""
        from wiki.agents.base_agent import GenericAgent

        class CustomAgent(GenericAgent):
            output_type = SimpleOutput

            def incorporate(self, tool_name, result, memory):
                pass

            def memory_to_prompt(self, memory):
                return ""

            def _render_output(self, structured: dict) -> str:
                return f"# {structured['title']}\n\n{structured['summary']}"

        mock_llm = MagicMock()
        mock_llm.complete_json = AsyncMock(return_value={"title": "Hello", "summary": "World"})

        agent = CustomAgent(mock_llm)
        result = await agent.run_generation("sys", "usr")
        assert result == "# Hello\n\nWorld"
