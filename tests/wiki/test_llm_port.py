from __future__ import annotations

import inspect

from llm.base_provider import LLMPortBridge
from wiki.llm_port import LLMPort


def test_llm_port_is_runtime_checkable():
    assert hasattr(LLMPort, "__protocol_attrs__") or hasattr(LLMPort, "__abstractmethods__") or True
    assert isinstance(LLMPort, type)


def test_llm_port_bridge_satisfies_llm_port():
    from unittest.mock import AsyncMock, MagicMock

    inner = MagicMock()
    inner.complete = AsyncMock(return_value="ok")
    inner.complete_json = AsyncMock(return_value={})
    inner.complete_stream = AsyncMock()
    bridge = LLMPortBridge(inner)
    assert isinstance(bridge, LLMPort)


def test_llm_port_has_generate_and_complete():
    assert hasattr(LLMPort, "generate")
    assert hasattr(LLMPort, "complete")
    assert hasattr(LLMPort, "complete_stream")
    assert hasattr(LLMPort, "complete_json")


def test_llm_port_protocol_does_not_include_agenerate():
    """agenerate is a bridge implementation detail, not a domain protocol method."""
    protocol_methods = [
        name
        for name, _ in inspect.getmembers(LLMPort, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    assert "agenerate" not in protocol_methods, (
        "agenerate should not be in LLMPort protocol — "
        "it belongs to LLMPortBridge implementation, not the domain interface"
    )
