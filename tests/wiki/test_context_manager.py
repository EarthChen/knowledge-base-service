"""Tests for context manager message trimming."""

import pytest

from wiki.context_manager import ContextManager


class TestContextManager:
    @pytest.fixture
    def manager(self):
        return ContextManager(max_context_chars=5000, keep_recent_rounds=2)

    def test_no_trim_when_under_threshold(self, manager):
        messages = [
            {"role": "system", "content": "You are helpful."},
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = manager.trim(messages)
        assert result == messages

    def test_preserves_system_prompt(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        assert result[0]["role"] == "system"
        assert result[0]["content"] == "System prompt"

    def test_preserves_recent_rounds(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        last_user = [m for m in result if m["role"] == "user"]
        assert any("recent" in m["content"] for m in last_user)

    def test_compresses_old_tool_results(self, manager):
        messages = self._build_large_messages(manager)
        result = manager.trim(messages)
        old_tools = [m for m in result if m["role"] == "tool" and "[compressed]" in m.get("content", "")]
        assert len(old_tools) > 0

    def test_total_chars_reduced(self, manager):
        messages = self._build_large_messages(manager)
        original_chars = sum(len(m.get("content", "")) for m in messages)
        result = manager.trim(messages)
        trimmed_chars = sum(len(m.get("content", "")) for m in result)
        assert trimmed_chars < original_chars

    def test_short_tool_results_not_compressed(self):
        mgr = ContextManager(max_context_chars=50000, keep_recent_rounds=2)
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "tool_call_id": "1", "content": "short result"},
            {"role": "user", "content": "recent"},
        ]
        result = mgr.trim(messages)
        tool_msgs = [m for m in result if m["role"] == "tool"]
        assert tool_msgs[0]["content"] == "short result"

    def _build_large_messages(self, manager) -> list[dict]:
        msgs = [{"role": "system", "content": "System prompt"}]
        for i in range(10):
            msgs.append({"role": "user", "content": f"question {i}"})
            msgs.append({
                "role": "assistant", "content": f"thinking {i}",
                "tool_calls": [{"id": f"tc_{i}", "function": {"name": "read_code", "arguments": "{}"}}],
            })
            msgs.append({
                "role": "tool", "tool_call_id": f"tc_{i}",
                "content": "x" * 800,
            })
        msgs.append({"role": "user", "content": "recent question"})
        msgs.append({"role": "assistant", "content": "recent answer"})
        return msgs
