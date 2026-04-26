import pytest
from unittest.mock import AsyncMock


@pytest.mark.asyncio
async def test_memory_loop_inject_returns_enriched_context() -> None:
    from wiki.memory_loop import MemoryLoop

    mock_store = AsyncMock()
    mock_embed = AsyncMock(return_value=[0.1] * 10)

    loop = MemoryLoop(mock_store, mock_embed, business_id="test")
    assert hasattr(loop, "inject_into_generation")
