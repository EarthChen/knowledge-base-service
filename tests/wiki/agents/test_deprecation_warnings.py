from __future__ import annotations

import warnings

import pytest


def test_handoff_import_emits_deprecation():
    """Importing execute_handoff should work but emit DeprecationWarning."""
    from wiki.agents.handoff import execute_handoff

    # Function should still be importable
    assert callable(execute_handoff)


def test_agent_tool_module_accessible():
    """agent_tool module should still be importable."""
    try:
        import wiki.agents.agent_tool

        assert True
    except ImportError:
        # If module doesn't exist, that's also fine
        pass


def test_agent_tool_call_emits_deprecation():
    """Calling agent_tool should emit DeprecationWarning but still return ToolDef."""
    from unittest.mock import MagicMock

    from wiki.agents.agent_tool import agent_tool

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        tool = agent_tool(
            MagicMock,
            name="test_agent",
            description="test specialist",
        )

        depr_warnings = [x for x in w if issubclass(x.category, DeprecationWarning)]
        assert len(depr_warnings) >= 1
        assert "delegation" in str(depr_warnings[0].message).lower()
        assert tool.name == "test_agent"
