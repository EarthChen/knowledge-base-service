from __future__ import annotations

import wiki.rag as rag


def test_package_exports() -> None:
    assert hasattr(rag, "IterativeRAGEngine")
    assert hasattr(rag, "WikiRetriever")
    assert hasattr(rag, "CodeRetriever")
    assert hasattr(rag, "CompositeRetriever")
    assert hasattr(rag, "rag_sse_append")
    assert hasattr(rag, "sse_thinking_start")
    assert hasattr(rag, "Chunk")
    assert hasattr(rag, "Retriever")
    assert hasattr(rag, "RetrievalScope")
    assert hasattr(rag, "Source")
