"""Tests for tool guardrail pre/post hooks."""

import pytest

from wiki.tool_guardrail import DefaultToolGuardrail


class TestDefaultToolGuardrail:
    @pytest.fixture
    def guardrail(self):
        return DefaultToolGuardrail()

    @pytest.mark.asyncio
    async def test_pre_call_rejects_empty_method_name(self, guardrail):
        result = await guardrail.pre_call("query_call_chain", {"method_name": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_rejects_missing_method_name(self, guardrail):
        result = await guardrail.pre_call("query_call_chain", {})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_rejects_empty_grep_pattern(self, guardrail):
        result = await guardrail.pre_call("grep_code", {"pattern": ""})
        assert result is None

    @pytest.mark.asyncio
    async def test_pre_call_passes_valid_args(self, guardrail):
        args = {"method_name": "doSomething"}
        result = await guardrail.pre_call("query_call_chain", args)
        assert result == args

    @pytest.mark.asyncio
    async def test_pre_call_passes_unknown_tool(self, guardrail):
        args = {"foo": "bar"}
        result = await guardrail.pre_call("unknown_tool", args)
        assert result == args

    @pytest.mark.asyncio
    async def test_post_call_truncates_large_result(self, guardrail):
        big_result = "x" * 10000
        result = await guardrail.post_call("read_code", {}, big_result)
        assert len(result) <= DefaultToolGuardrail.MAX_RESULT_CHARS + 20
        assert "[TRUNCATED]" in result

    @pytest.mark.asyncio
    async def test_post_call_marks_empty_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "")
        assert "[EMPTY_RESULT]" in result

    @pytest.mark.asyncio
    async def test_post_call_marks_whitespace_only_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "   \n  ")
        assert "[EMPTY_RESULT]" in result

    @pytest.mark.asyncio
    async def test_post_call_passes_normal_result(self, guardrail):
        result = await guardrail.post_call("read_code", {}, "some code here")
        assert result == "some code here"
