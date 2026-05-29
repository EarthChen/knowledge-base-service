from __future__ import annotations

from wiki.agents.context_compactor import micro_compact, snip_compact


class TestMicroCompact:
    def test_keeps_recent_3_tool_results(self):
        msgs = [{"role": "system", "content": "s"}]
        for i in range(6):
            msgs.append({"role": "assistant", "content": "", "tool_calls": [{"id": f"t{i}"}]})
            msgs.append({"role": "tool", "content": f"result_{i} " * 1000, "tool_call_id": f"t{i}"})
        result = micro_compact(msgs, keep_recent_n=3)
        tool_msgs = [m for m in result if m.get("role") == "tool"]
        full_tools = [m for m in tool_msgs if not m["content"].startswith("[已压缩")]
        assert len(full_tools) == 3

    def test_old_tools_get_placeholder(self):
        msgs = [{"role": "system", "content": "s"}]
        for i in range(5):
            msgs.append({"role": "tool", "content": f"data_{i}" * 100, "tool_call_id": f"t{i}"})
        result = micro_compact(msgs, keep_recent_n=2)
        compressed = [m for m in result if m.get("role") == "tool" and "[已压缩" in m["content"]]
        assert len(compressed) == 3  # 5 - 2 = 3 compressed

    def test_removes_orphan_tool_calls(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "orphan"}]},
            {"role": "assistant", "content": "reasoning"},
        ]
        result = micro_compact(msgs, keep_recent_n=3)
        has_orphan = any(m.get("tool_calls") and any(tc["id"] == "orphan" for tc in m["tool_calls"]) for m in result)
        assert not has_orphan

    def test_preserves_system_and_user(self):
        msgs = [{"role": "system", "content": "sys"}, {"role": "user", "content": "task"}]
        result = micro_compact(msgs, keep_recent_n=3)
        assert result == msgs

    def test_preserves_assistant_text(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "assistant", "content": "I think we should..."},
            {"role": "tool", "content": "data"},
        ]
        result = micro_compact(msgs, keep_recent_n=1)
        assistant_msgs = [m for m in result if m.get("role") == "assistant"]
        assert len(assistant_msgs) == 1
        assert assistant_msgs[0]["content"] == "I think we should..."


class TestSnipCompact:
    def test_truncates_long_tool_results(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "tool", "content": "x" * 60000, "tool_call_id": "t1"},
        ]
        result = snip_compact(msgs, max_tool_chars=2000)
        tool_msg = [m for m in result if m.get("role") == "tool"][0]
        assert len(tool_msg["content"]) < 5000
        assert "...[snipped" in tool_msg["content"]

    def test_short_tool_results_unchanged(self):
        msgs = [
            {"role": "system", "content": "s"},
            {"role": "tool", "content": "short result", "tool_call_id": "t1"},
        ]
        result = snip_compact(msgs, max_tool_chars=2000)
        assert result[1]["content"] == "short result"

    def test_preserves_non_tool_messages(self):
        msgs = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "task"},
            {"role": "assistant", "content": "reasoning"},
        ]
        result = snip_compact(msgs, max_tool_chars=2000)
        assert result == msgs
