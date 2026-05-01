from __future__ import annotations

from wiki.rag.events import rag_sse_append, sse_thinking_start


def test_sse_thinking_start_shape():
    e = sse_thinking_start(round_no=2, max_rounds=7)
    assert e["type"] == "thinking_start"
    assert e["round"] == 2


def test_rag_sse_append_preserves_list():
    base = {"sse_events": [{"type": "x"}]}
    out = rag_sse_append(base, "draft", {"round": 1})
    assert len(out) == 2
