from __future__ import annotations
import pytest
from unittest.mock import MagicMock


def test_wiki_deps_has_required_fields():
    from wiki.agents.context import WikiDeps

    graph = MagicMock()
    deps = WikiDeps(graph_store=graph)
    assert deps.graph_store is graph
    assert deps.search_service is None
    assert deps.repo_path is None
    assert deps.business_id == ""
    assert deps.delegation_depth == 0
    assert deps.delegation_count == 0


def test_run_context_wraps_deps():
    from wiki.agents.context import RunContext, WikiDeps

    graph = MagicMock()
    deps = WikiDeps(graph_store=graph, business_id="test-biz")
    ctx = RunContext(deps=deps, trace_id="abc123")

    assert ctx.deps.graph_store is graph
    assert ctx.deps.business_id == "test-biz"
    assert ctx.trace_id == "abc123"
    assert ctx.metadata == {}


def test_run_context_metadata_is_mutable():
    from wiki.agents.context import RunContext, WikiDeps

    ctx = RunContext(deps=WikiDeps(graph_store=MagicMock()))
    ctx.metadata["key"] = "value"
    assert ctx.metadata["key"] == "value"
