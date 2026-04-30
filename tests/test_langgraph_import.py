"""Verify LangGraph and langchain-core are importable."""


def test_langgraph_importable():
    from langgraph.graph import StateGraph
    assert StateGraph is not None


def test_langchain_core_importable():
    from langchain_core.language_models import BaseChatModel
    from langchain_core.prompts import ChatPromptTemplate
    assert BaseChatModel is not None
    assert ChatPromptTemplate is not None
