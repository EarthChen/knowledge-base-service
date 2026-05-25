import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from wiki.incremental_diff import WikiDiff
from wiki.incremental_generator import IncrementalWikiGenerator
from wiki.persistence import WikiPagePersistence


def _incremental_gen(wiki_store: AsyncMock) -> IncrementalWikiGenerator:
    store = MagicMock()
    store.execute_query = AsyncMock()
    return IncrementalWikiGenerator(
        store=store,
        graph=MagicMock(),
        wiki_cfg=MagicMock(code_budget_enabled=False),
        wiki_store=wiki_store,
        persistence=MagicMock(spec=WikiPagePersistence),
        collector=MagicMock(),
        page_composer=MagicMock(),
        budget_resolver=MagicMock(),
        composer_factory=MagicMock(),
        config_for=MagicMock(),
        ensure_repo=AsyncMock(),
        persist_pages=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_incremental_no_baseline_returns_no_baseline() -> None:
    """When no previous generation exists, return no_baseline."""
    mock_ws = AsyncMock()
    mock_ws.get_wiki_generation_version = AsyncMock(return_value=None)

    from wiki.service import WikiService

    service = MagicMock(spec=WikiService)
    service._incremental_generator = MagicMock(return_value=_incremental_gen(mock_ws))
    service.generate_incremental = WikiService.generate_incremental.__get__(service)

    result = await service.generate_incremental("test-repo")
    assert result["status"] == "no_baseline"


@pytest.mark.asyncio
async def test_incremental_no_changes_returns_no_changes() -> None:
    """When no code changes detected, return no_changes."""
    mock_ws = AsyncMock()
    mock_ws.get_wiki_generation_version = AsyncMock(return_value=1)

    with patch("wiki.incremental_generator.compute_wiki_diff", new_callable=AsyncMock) as mock_diff:
        mock_diff.return_value = WikiDiff(set(), set())

        from wiki.service import WikiService

        service = MagicMock(spec=WikiService)
        service._incremental_generator = MagicMock(return_value=_incremental_gen(mock_ws))
        service.generate_incremental = WikiService.generate_incremental.__get__(service)

        result = await service.generate_incremental("test-repo")
        assert result["status"] == "no_changes"
