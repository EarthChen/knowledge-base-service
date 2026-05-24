import pytest


def test_finalize_node_importable():
    from wiki.nodes.finalize import finalize_node

    assert callable(finalize_node)


@pytest.mark.asyncio
async def test_finalize_node_returns_empty_dict():
    from wiki.nodes.finalize import finalize_node

    state = {
        "pages": [{"path": "a"}, {"path": "b"}],
        "stage_timings": {"classify": 100, "compose": 200},
        "llm_call_count": 5,
        "errors": ["one_error"],
    }
    result = await finalize_node(state)
    assert result == {}
