"""Tests for P2.1: agent history preservation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from wiki.page_agent import WikiPageAgent


class TestHistoryPreservation:
    def test_max_history_messages_constant(self):
        assert WikiPageAgent._MAX_HISTORY_MESSAGES == 30

    @pytest.mark.asyncio
    async def test_preserves_tool_call_history(self):
        """After one round of tool calls, messages should contain the tool call history."""
        call_count = 0
        captured_messages = []

        async def mock_complete(messages, tools, **kwargs):
            nonlocal call_count, captured_messages
            call_count += 1
            captured_messages.append(list(messages))
            if call_count == 1:
                return {
                    "content": None,
                    "tool_calls": [{"function": {"name": "query_callers", "arguments": '{"name":"X"}'}, "id": "c1"}],
                }
            # Second call - return final content
            return {"content": "Final enriched page.", "tool_calls": None}

        llm = MagicMock()
        llm.complete_with_tools = mock_complete
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)

        content = "## Test\n<!-- CONTEXT_GAP: who calls X -->"
        result = await agent.enrich(content, domain_name="test")

        # The second call should see the tool_call history
        assert call_count == 2
        second_call_msgs = captured_messages[1]
        # Should have more than just system + user (should include assistant + tool messages)
        assert len(second_call_msgs) > 2
        # Should contain a tool role message
        has_tool_msg = any(m.get("role") == "tool" for m in second_call_msgs)
        assert has_tool_msg, "Second LLM call should see tool result history"
        assert result == "Final enriched page."

    @pytest.mark.asyncio
    async def test_compresses_when_too_many_messages(self):
        """When messages exceed _MAX_HISTORY_MESSAGES, should compress."""
        call_count = 0

        async def mock_complete(messages, tools, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 5:
                # Return many tool calls to inflate message count
                return {
                    "content": None,
                    "tool_calls": [
                        {"function": {"name": "query_callers", "arguments": '{"name":"A"}'}, "id": f"c{call_count}a"},
                        {"function": {"name": "query_callees", "arguments": '{"name":"B"}'}, "id": f"c{call_count}b"},
                        {
                            "function": {
                                "name": "search_entities",
                                "arguments": '{"keyword":"C"}',
                            },
                            "id": f"c{call_count}c",
                        },
                        {"function": {"name": "query_callers", "arguments": '{"name":"D"}'}, "id": f"c{call_count}d"},
                        {"function": {"name": "query_callees", "arguments": '{"name":"E"}'}, "id": f"c{call_count}e"},
                    ],
                }
            return {"content": "Done.", "tool_calls": None}

        llm = MagicMock()
        llm.complete_with_tools = mock_complete
        gs = MagicMock()
        gs.execute_query = AsyncMock(return_value=MagicMock(data=[]))
        agent = WikiPageAgent(llm, gs)
        # Lower max tool calls to let all 5 rounds complete
        agent.max_tool_calls = 30

        content = "## Test\n<!-- CONTEXT_GAP: complex gap -->"
        result = await agent.enrich(content, domain_name="test")

        # Should have completed without error
        assert call_count >= 3
        assert result == "Done."
