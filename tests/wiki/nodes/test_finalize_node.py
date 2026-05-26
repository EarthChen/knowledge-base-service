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
    assert result == {"pages": [{"path": "a"}, {"path": "b"}]}


@pytest.mark.asyncio
async def test_finalize_node_sanitizes_content():
    from wiki.nodes.finalize import finalize_node

    state = {
        "pages": [
            {
                "path": "wiki/test",
                "content": "# Title\n<!-- CONTEXT_GAP: gap -->\nBody",
            }
        ],
        "errors": [],
    }
    result = await finalize_node(state)
    assert "CONTEXT_GAP" not in result["pages"][0]["content"]
    assert "Body" in result["pages"][0]["content"]
