"""Tests for HarnessGuardRails."""
import pytest


class TestGuardRails:
    def test_first_call_passes(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        assert result is None

    def test_duplicate_call_blocked(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        assert result is not None
        assert result.action == "block"

    def test_different_params_not_duplicate(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        gr.check_tool_call("query_module_detail", {"module_name": "Mod1"})
        result = gr.check_tool_call("query_module_detail", {"module_name": "Mod2"})
        assert result is None

    def test_output_too_short_warns(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("short")
        assert len(violations) == 1
        assert violations[0].rule == "too_short"
        assert violations[0].action == "warn"

    def test_output_too_long_truncates(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("x" * 20000)
        assert any(v.rule == "too_long" for v in violations)

    def test_output_normal_no_violations(self):
        from wiki.harness_guardrails import HarnessGuardRails
        gr = HarnessGuardRails()
        violations = gr.check_output("x" * 1000)
        assert len(violations) == 0
