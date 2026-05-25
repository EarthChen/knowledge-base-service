import pytest


def test_finalize_node_importable():
    from wiki.nodes.finalize import finalize_node

    assert callable(finalize_node)


@pytest.mark.asyncio
async def test_finalize_node_returns_empty_dict():
    from wiki.nodes.finalize import finalize_node

    state = {
        "pages": [{"path": "a"}, {"path": "b"}],
        "errors": ["one_error"],
    }
    result = await finalize_node(state)
    assert result == {}
